"""Stream DOCX into bounded, independently renderable preview packages.

The source is never modified. Only a requested chunk and its referenced resources
cross the process boundary. Bookmarks in the projection carry original positions;
they are not persisted in the user's document.
"""
from base64 import b64encode
from copy import deepcopy
from hashlib import file_digest
from io import BytesIO
from pathlib import Path
import posixpath
import xml.etree.ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile

from . import policy
from .inspection import Package, inspect_image

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"
CT = "{http://schemas.openxmlformats.org/package/2006/content-types}"
DOCUMENT = "word/document.xml"
MARKER = "tiance_preview_p_"


def _val(element, default=None):
    return element.get(W + "val", default) if element is not None else default


def _cost(element):
    return sum(1 for _ in element.iter()), sum(len(e.text or "") for e in element.iter())


class Positions:
    def __init__(self, styles):
        self.paragraph = self.table = 0
        self.heading = ""
        self.counters = {}
        self.styles = styles

    def annotate(self, root, table=None, row=None, column=None, cell_paragraph=None):
        locations = {}
        if root.tag == W + "tbl":
            self.table += 1
            table = self.table
            for index, child in enumerate(root.findall(W + "tr"), 1):
                locations.update(self.annotate(child, table, index))
        elif root.tag == W + "tr":
            col = int(_val(root.find(W + "trPr/" + W + "gridBefore"), "0")) + 1
            for cell in root.findall(W + "tc"):
                locations.update(self.annotate(cell, table, row, col))
                col += int(_val(cell.find(W + "tcPr/" + W + "gridSpan"), "1"))
        elif root.tag == W + "tc":
            index = 0
            for child in root:
                if child.tag == W + "p":
                    index += 1
                locations.update(self.annotate(child, table, row, column, index))
        elif root.tag == W + "p":
            self.paragraph += 1
            style = _val(root.find(W + "pPr/" + W + "pStyle"), "")
            inherited = self.styles.get(style, {})
            if style.lower().startswith(("heading", "title")) or inherited.get("heading"):
                self.heading = "".join(root.itertext()).strip()[:160]
            location = {"paragraphIndex": self.paragraph, "container": "table" if table else "body"}
            if table:
                location.update(tableIndex=table, rowIndex=row, columnIndex=column, cellParagraphIndex=cell_paragraph)
            if self.heading:
                location["nearestHeading"] = self.heading
            num = root.find(W + "pPr/" + W + "numPr")
            if num is not None or inherited.get("num_id"):
                num_id = _val(num.find(W + "numId"), inherited.get("num_id")) if num is not None else inherited.get("num_id")
                level = _val(num.find(W + "ilvl"), inherited.get("level", "0")) if num is not None else inherited.get("level", "0")
                if num_id and num_id != "0":
                    key = f"{num_id}-{level}"
                    location["numbering"] = {"id": num_id, "level": level, "preceding": self.counters.get(key, 0)}
                    self.counters[key] = self.counters.get(key, 0) + 1
                    for other in list(self.counters):
                        if other.startswith(num_id + "-") and int(other.rsplit("-", 1)[1]) > int(level):
                            del self.counters[other]
            marker = ET.Element(W + "bookmarkStart", {W + "id": str(1_000_000 + self.paragraph), W + "name": MARKER + str(self.paragraph)})
            root.insert(1 if root.find(W + "pPr") is not None else 0, marker)
            locations[str(self.paragraph)] = location
        else:
            for child in root:
                locations.update(self.annotate(child, table, row, column, cell_paragraph))
        return locations


def _paragraph_styles(package):
    if "word/styles.xml" not in package.archive.namelist():
        return {}
    root = package.small_xml("word/styles.xml")
    styles = {e.get(W + "styleId"): e for e in root.findall(W + "style")}
    result = {}
    for key in styles:
        current, seen, values = key, set(), {}
        while current in styles and current not in seen:
            seen.add(current)
            style = styles[current]
            for field, tag in (("num_id", "numPr/" + W + "numId"), ("level", "numPr/" + W + "ilvl"), ("heading", "outlineLvl")):
                value = _val(style.find(W + "pPr/" + W + tag))
                if value is not None and field not in values:
                    values[field] = int(value) < 9 if field == "heading" else value
            current = _val(style.find(W + "basedOn"))
        result[key] = values
    return result


def _units(package, sections):
    """Retain one paragraph/table row, never the entire document tree."""
    stack = []
    positions = Positions(_paragraph_styles(package))
    table_id = row_index = 0
    table_props = []
    unit_index = 0
    saw_body = False
    unit_nodes = 0
    for event, element in package.events(DOCUMENT):
        if event == "start":
            stack.append(element)
            if len(stack) == 2 and element.tag == W + "body":
                saw_body = True
            if len(stack) == 3 and element.tag == W + "tbl":
                positions.table += 1
                table_id, row_index, table_props = positions.table, 0, []
            if (len(stack) == 3 and element.tag != W + "tbl") or (len(stack) == 4 and element.tag == W + "tr"):
                unit_nodes = 0
            unit_nodes += 1
            if unit_nodes > policy.MAX_WORD_UNIT_NODES:
                raise policy.PreviewLimit("Word 单个段落或表格行过于复杂，无法分块预览。")
            continue
        parent = stack[-2] if len(stack) > 1 else None
        top_table_child = len(stack) == 4 and stack[-2].tag == W + "tbl"
        if top_table_child and element.tag in (W + "tblPr", W + "tblGrid"):
            table_props.append(deepcopy(element))
            parent.remove(element)
        elif top_table_child and element.tag == W + "tr":
            row_index += 1
            nodes, chars = _cost(element)
            locations = positions.annotate(element, table_id, row_index)
            table = ET.Element(W + "tbl")
            table.extend(deepcopy(table_props))
            table.append(element)
            continuing = any(_val(e) != "restart" for e in element.iter(W + "vMerge"))
            yield {"element": table, "locations": locations, "nodes": nodes, "chars": chars,
                   "table": table_id, "keep": continuing, "index": unit_index}
            unit_index += 1
            parent.remove(element)
        elif len(stack) == 3:
            if element.tag == W + "sectPr":
                sections.append((unit_index, deepcopy(element)))
            elif element.tag != W + "tbl":
                nodes, chars = _cost(element)
                locations = positions.annotate(element)
                yield {"element": element, "locations": locations, "nodes": nodes,
                       "chars": chars, "table": None, "keep": False, "index": unit_index}
                unit_index += 1
                section = element.find(W + "pPr/" + W + "sectPr")
                if section is not None:
                    sections.append((unit_index, deepcopy(section)))
            parent.remove(element)
        stack.pop()
    if not saw_body:
        raise ValueError("Word 正文结构无效。")


def _scan(package, wanted=None):
    chunks, selected, sections = [], [], []
    nodes = chars = blocks = start = images = 0
    for unit in _units(package, sections):
        unit_images = sum(R + "embed" in e.attrib or R + "link" in e.attrib or e.tag.endswith("}imagedata") for e in unit["element"].iter())
        if blocks and not unit["keep"] and (nodes + unit["nodes"] > policy.WORD_CHUNK_NODES
                or chars + unit["chars"] > policy.WORD_CHUNK_TEXT or blocks >= policy.WORD_CHUNK_BLOCKS
                or images + unit_images > policy.WORD_CHUNK_IMAGES):
            chunks.append({"start": start, "count": blocks})
            start, nodes, chars, blocks, images = unit["index"], 0, 0, 0, 0
        if unit["nodes"] > policy.MAX_WORD_UNIT_NODES or unit["chars"] > policy.MAX_WORD_UNIT_TEXT:
            raise policy.PreviewLimit("Word 单个段落或表格行过于复杂，无法分块预览。")
        nodes += unit["nodes"]
        chars += unit["chars"]
        blocks += 1
        images += unit_images
        if nodes > policy.MAX_WORD_PART_NODES or chars > policy.MAX_WORD_UNIT_TEXT:
            raise policy.PreviewLimit("Word 连续合并的表格区域过于复杂，无法分块预览。")
        if wanted == len(chunks):
            selected.append({**unit, "element": deepcopy(unit["element"])})
    if blocks or not chunks:
        chunks.append({"start": start, "count": blocks})
    return chunks, selected, sections


def inspect_word(path: Path, package: Package):
    chunks, _, _ = _scan(package)
    with path.open("rb") as stream:
        fingerprint = "sha256:" + file_digest(stream, "sha256").hexdigest()
    return {"mode": "paged", "word": {"chunks": len(chunks), "fingerprint": fingerprint}}


def _rels_path(part):
    directory, name = posixpath.split(part)
    return posixpath.join(directory, "_rels", name + ".rels")


def _target(part, target):
    value = posixpath.normpath(target.lstrip("/") if target.startswith("/") else posixpath.join(posixpath.dirname(part), target))
    if value.startswith("../") or "\\" in value or ":" in value:
        raise ValueError("Word 资源关系路径无效。")
    return value


def _styles(root, used):
    styles = {e.get(W + "styleId"): e for e in root.findall(W + "style")}
    used.update(k for k, e in styles.items() if e.get(W + "default") in ("1", "true"))
    pending = list(used)
    while pending:
        style = styles.get(pending.pop())
        if style is None:
            continue
        for tag in ("basedOn", "link", "next"):
            key = _val(style.find(W + tag))
            if key and key not in used:
                used.add(key)
                pending.append(key)
    for child in list(root):
        if child.tag == W + "latentStyles" or (child.tag == W + "style" and child.get(W + "styleId") not in used):
            root.remove(child)


def _preview_image(data, target):
    """Bound decoded pixels and transfer size without changing the source image."""
    if target.lower().endswith(".svg"):
        return target, data, 0
    from PIL import Image
    width, height = inspect_image(BytesIO(data))
    if len(data) <= 384 * 1024 and width * height <= 1_600_000:
        return target, data, width * height
    with Image.open(BytesIO(data)) as source:
        source.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
        picture = source.convert("RGBA" if "A" in source.getbands() or "transparency" in source.info else "RGB")
        while True:
            output = BytesIO()
            picture.save(output, format="PNG")
            if output.tell() <= 384 * 1024:
                return target + ".preview.png", output.getvalue(), picture.width * picture.height
            picture.thumbnail((max(1, picture.width * 3 // 4), max(1, picture.height * 3 // 4)), Image.Resampling.LANCZOS)


def _projection(package, body):
    document = ET.Element(W + "document")
    document.append(body)
    parts = {DOCUMENT: ET.tostring(document, encoding="utf-8", xml_declaration=True)}
    queue = [(DOCUMENT, document)]
    used_styles = set()
    style_part = None
    total_nodes = 0
    image_pixels = 0
    image_targets = {}
    # The renderer only receives relationships used in this chunk. It must not
    # parse the other pages' headers/notes or eagerly decode their images.
    while queue:
        part, root = queue.pop(0)
        used_styles.update(e.get(W + "val") for e in root.iter() if e.tag in (W + "pStyle", W + "rStyle", W + "tblStyle"))
        ids = {value for e in root.iter() for key, value in e.attrib.items() if key.startswith(R)}
        rel_path = _rels_path(part)
        if rel_path not in package.archive.namelist():
            continue
        rels = package.small_xml(rel_path)
        for relation in list(rels):
            kind = relation.get("Type", "").rsplit("/", 1)[-1]
            shared = part == DOCUMENT and kind in ("styles", "numbering", "theme", "settings", "fontTable", "footnotes", "endnotes")
            if relation.get("Id") not in ids and not shared:
                rels.remove(relation)
                continue
            if relation.get("TargetMode") == "External":
                if kind != "hyperlink" or not relation.get("Target", "").lower().startswith(("https://", "http://", "mailto:")):
                    rels.remove(relation)
                continue
            target = _target(part, relation.get("Target", ""))
            if target in image_targets:
                relation.set("Target", posixpath.relpath(image_targets[target], posixpath.dirname(part)))
                continue
            if target in parts:
                continue
            if target not in package.archive.namelist():
                raise ValueError("Word 引用的资源不存在。")
            if kind in ("aFChunk", "oleObject", "package"):
                raise policy.PreviewLimit("Word 内含暂不支持分块预览的嵌入对象。")
            if target.lower().endswith(".xml"):
                child = package.small_xml(target)
                if kind in ("footnotes", "endnotes"):
                    tag = "footnoteReference" if kind == "footnotes" else "endnoteReference"
                    note_ids = {e.get(W + "id") for e in document.iter(W + tag)}
                    for note in list(child):
                        if note.get(W + "id") not in note_ids:
                            child.remove(note)
                if kind == "styles":
                    style_part = (target, child)
                else:
                    total_nodes += _cost(child)[0]
                parts[target] = ET.tostring(child, encoding="utf-8", xml_declaration=True)
                queue.append((target, child))
            else:
                info = package.archive.getinfo(target)
                if info.file_size > (policy.MAX_IMAGE_BYTES if kind == "image" else policy.MAX_WORD_PART_BYTES):
                    raise policy.PreviewLimit("单张图片超过 32 MiB，无法内置预览。" if kind == "image"
                                              else "本段嵌入资源超过 2 MiB，无法内置预览。")
                data = package.archive.read(target)
                if kind == "image":
                    if target.lower().endswith(".svg"):
                        package.small_xml(target)
                    else:
                        original_target = target
                        target, data, pixels = _preview_image(data, target)
                        image_targets[original_target] = target
                        relation.set("Target", posixpath.relpath(target, posixpath.dirname(part)))
                        image_pixels += pixels
                        if image_pixels > policy.MAX_IMAGE_PIXELS:
                            raise policy.PreviewLimit("本段图片累计像素过大，无法内置预览。")
                parts[target] = data
            if sum(len(data) for name, data in parts.items() if not style_part or name != style_part[0]) > policy.MAX_WORD_PART_BYTES:
                raise policy.PreviewLimit("本段解压内容超过 2 MiB，无法内置预览。")
        parts[rel_path] = ET.tostring(rels, encoding="utf-8", xml_declaration=True)
    if style_part:
        target, styles = style_part
        _styles(styles, used_styles)
        total_nodes += _cost(styles)[0]
        parts[target] = ET.tostring(styles, encoding="utf-8", xml_declaration=True)
    if total_nodes + _cost(document)[0] > policy.MAX_WORD_PART_NODES:
        raise policy.PreviewLimit("本段样式与正文超过排版预算。")
    if sum(map(len, parts.values())) > policy.MAX_WORD_PART_BYTES:
        raise policy.PreviewLimit("本段解压内容超过 2 MiB，无法内置预览。")
    content_types = package.small_xml("[Content_Types].xml")
    if any(name.endswith(".preview.png") for name in parts) and not any(e.get("Extension") == "png" for e in content_types):
        ET.SubElement(content_types, CT + "Default", {"Extension": "png", "ContentType": "image/png"})
    for entry in list(content_types):
        if entry.tag == CT + "Override" and entry.get("PartName", "").lstrip("/") not in parts:
            content_types.remove(entry)
    parts["[Content_Types].xml"] = ET.tostring(content_types, encoding="utf-8")
    rels = ET.Element(REL + "Relationships")
    ET.SubElement(rels, REL + "Relationship", {"Id": "rDocument", "Type": R[1:-1] + "/officeDocument", "Target": DOCUMENT})
    parts["_rels/.rels"] = ET.tostring(rels, encoding="utf-8")
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for name, data in parts.items():
            archive.writestr(name, data)
    return b64encode(output.getvalue()).decode("ascii")


def word_chunk(path: Path, chunk: int):
    if path.suffix.lower() != ".docx" or path.stat().st_size > policy.MAX_PACKAGE_BYTES:
        raise ValueError("分块预览需要 64 MiB 以内的 DOCX 文件。")
    package = Package(path)
    try:
        chunks, units, sections = _scan(package, chunk)
        if chunk < 0 or chunk >= len(chunks):
            raise ValueError("Word 内容分块不存在。")
        body, locations = ET.Element(W + "body"), {}
        last_table = None
        for unit in units:
            element = unit["element"]
            locations.update(unit["locations"])
            if unit["table"] and last_table == unit["table"]:
                body[-1].extend(element.findall(W + "tr"))
            else:
                body.append(element)
            last_table = unit["table"]
        end = chunks[chunk]["start"] + chunks[chunk]["count"]
        section_index = next((i for i, (boundary, _) in enumerate(sections) if boundary >= end), max(0, len(sections) - 1))
        section = deepcopy(sections[section_index][1]) if sections else ET.Element(W + "sectPr")
        section_start = sections[section_index - 1][0] if section_index > 0 else 0
        if chunks[chunk]["start"] > section_start:
            for title in section.findall(W + "titlePg"):
                section.remove(title)
        body.append(section)
        return {"chunk": chunk, "package_base64": _projection(package, body), "locations": locations}
    finally:
        package.close()
