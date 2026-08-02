from __future__ import annotations

import html
import os
import re
import shutil
from pathlib import Path
from tempfile import mkstemp
from zipfile import ZIP_DEFLATED, ZipFile

from docx.oxml.ns import qn
from lxml import etree

from docx_package_xml import (
    CONTENT_TYPES_NS,
    ENDNOTE_CONTENT_TYPE,
    ENDNOTE_RELATIONSHIP,
    FOOTNOTE_CONTENT_TYPE,
    FOOTNOTE_RELATIONSHIP,
    RELATIONSHIPS_NS,
    WORD_NS,
    XML_NS,
    parse_xml,
    serialize_xml,
)
from word_xml import get_or_add_ordered_child


def postprocess_docx_package(
    path: Path,
    *,
    footnotes: list[tuple[int, str]],
    endnotes: list[tuple[int, str]],
    update_fields: bool,
) -> None:
    if not footnotes and not endnotes and not update_fields:
        return
    replacements: dict[str, bytes] = {}
    with ZipFile(path, "r") as source:
        names = set(source.namelist())
        content_types = parse_xml(
            _read_required_part(source, "[Content_Types].xml"),
            "[Content_Types].xml",
        )
        relationships = parse_xml(
            _read_required_part(source, "word/_rels/document.xml.rels"),
            "word/_rels/document.xml.rels",
        )
        if footnotes:
            _add_note_part(
                replacements,
                content_types,
                relationships,
                notes=footnotes,
                note_kind="footnote",
            )
        if endnotes:
            _add_note_part(
                replacements,
                content_types,
                relationships,
                notes=endnotes,
                note_kind="endnote",
            )

        if footnotes or endnotes:
            replacements["[Content_Types].xml"] = serialize_xml(content_types)
            replacements["word/_rels/document.xml.rels"] = serialize_xml(relationships)
            styles = parse_xml(
                _read_required_part(source, "word/styles.xml"),
                "word/styles.xml",
            )
            _ensure_note_styles(
                styles,
                include_footnotes=bool(footnotes),
                include_endnotes=bool(endnotes),
            )
            replacements["word/styles.xml"] = serialize_xml(styles)
        if update_fields and "word/settings.xml" in names:
            settings = parse_xml(source.read("word/settings.xml"), "word/settings.xml")
            update = get_or_add_ordered_child(settings, "w:updateFields")
            update.set(qn("w:val"), "true")
            replacements["word/settings.xml"] = serialize_xml(settings)

    if replacements:
        _rewrite_zip(path, replacements)


def _add_note_part(
    replacements: dict[str, bytes],
    content_types,
    relationships,
    *,
    notes: list[tuple[int, str]],
    note_kind: str,
) -> None:
    is_footnote = note_kind == "footnote"
    plural = "footnotes" if is_footnote else "endnotes"
    reference_style = "FootnoteReference" if is_footnote else "EndnoteReference"
    text_style = "FootnoteText" if is_footnote else "EndnoteText"
    relationship_type = FOOTNOTE_RELATIONSHIP if is_footnote else ENDNOTE_RELATIONSHIP
    content_type = FOOTNOTE_CONTENT_TYPE if is_footnote else ENDNOTE_CONTENT_TYPE
    replacements[f"word/{plural}.xml"] = _build_notes_xml(
        root_name=plural,
        note_name=note_kind,
        ref_name=f"{note_kind}Ref",
        reference_style=reference_style,
        text_style=text_style,
        notes=notes,
    )
    _ensure_content_type_override(
        content_types,
        f"/word/{plural}.xml",
        content_type,
    )
    _ensure_document_relationship(
        relationships,
        relationship_type,
        f"{plural}.xml",
    )


def _build_notes_xml(
    *,
    root_name: str,
    note_name: str,
    ref_name: str,
    reference_style: str,
    text_style: str,
    notes: list[tuple[int, str]],
) -> bytes:
    root = etree.Element(f"{{{WORD_NS}}}{root_name}", nsmap={"w": WORD_NS})
    _append_special_note(root, note_name, note_id=-1, note_type="separator", marker="separator")
    _append_special_note(
        root,
        note_name,
        note_id=0,
        note_type="continuationSeparator",
        marker="continuationSeparator",
    )
    for note_id, text in notes:
        note = etree.SubElement(root, f"{{{WORD_NS}}}{note_name}")
        note.set(qn("w:id"), str(note_id))
        paragraph = etree.SubElement(note, qn("w:p"))
        properties = etree.SubElement(paragraph, qn("w:pPr"))
        style = etree.SubElement(properties, qn("w:pStyle"))
        style.set(qn("w:val"), text_style)
        reference_run = etree.SubElement(paragraph, qn("w:r"))
        run_properties = etree.SubElement(reference_run, qn("w:rPr"))
        run_style = etree.SubElement(run_properties, qn("w:rStyle"))
        run_style.set(qn("w:val"), reference_style)
        etree.SubElement(reference_run, qn(f"w:{ref_name}"))
        _append_text_run(paragraph, " ")
        for index, line in enumerate(_plain_note_lines(text)):
            if index:
                break_run = etree.SubElement(paragraph, qn("w:r"))
                etree.SubElement(break_run, qn("w:br"))
            _append_text_run(paragraph, line)
    return serialize_xml(root)


def _append_special_note(
    root,
    note_name: str,
    *,
    note_id: int,
    note_type: str,
    marker: str,
) -> None:
    note = etree.SubElement(root, f"{{{WORD_NS}}}{note_name}")
    note.set(qn("w:type"), note_type)
    note.set(qn("w:id"), str(note_id))
    paragraph = etree.SubElement(note, qn("w:p"))
    run = etree.SubElement(paragraph, qn("w:r"))
    etree.SubElement(run, qn(f"w:{marker}"))


def _append_text_run(paragraph, value: str) -> None:
    run = etree.SubElement(paragraph, qn("w:r"))
    text = etree.SubElement(run, qn("w:t"))
    text.set(f"{{{XML_NS}}}space", "preserve")
    text.text = value


def _plain_note_lines(text: str) -> list[str]:
    cleaned = re.sub(r"<br\s*/?>", "\n", text or "", flags=re.IGNORECASE)
    cleaned = re.sub(r"<[^>]+>", "", cleaned)
    lines = [html.unescape(line.strip()) for line in cleaned.split("\n")]
    return lines or [""]


def _ensure_content_type_override(root, part_name: str, content_type: str) -> None:
    override_tag = f"{{{CONTENT_TYPES_NS}}}Override"
    for override in root.findall(override_tag):
        if override.get("PartName") == part_name:
            override.set("ContentType", content_type)
            return
    override = etree.SubElement(root, override_tag)
    override.set("PartName", part_name)
    override.set("ContentType", content_type)


def _ensure_document_relationship(root, relationship_type: str, target: str) -> None:
    relationship_tag = f"{{{RELATIONSHIPS_NS}}}Relationship"
    for relationship in root.findall(relationship_tag):
        if (
            relationship.get("Type") == relationship_type
            and relationship.get("Target") == target
        ):
            return
    relationship = etree.SubElement(root, relationship_tag)
    relationship.set("Id", _next_relationship_id(root))
    relationship.set("Type", relationship_type)
    relationship.set("Target", target)


def _next_relationship_id(root) -> str:
    values: list[int] = []
    for relationship in root:
        match = re.fullmatch(r"rId(\d+)", relationship.get("Id", ""))
        if match:
            values.append(int(match.group(1)))
    return f"rId{max(values, default=0) + 1}"


def _ensure_note_styles(styles, *, include_footnotes: bool, include_endnotes: bool) -> None:
    if include_footnotes:
        _ensure_reference_style(styles, "FootnoteReference", "footnote reference")
        _ensure_note_text_style(styles, "FootnoteText", "footnote text")
    if include_endnotes:
        _ensure_reference_style(styles, "EndnoteReference", "endnote reference")
        _ensure_note_text_style(styles, "EndnoteText", "endnote text")


def _ensure_reference_style(styles, style_id: str, display_name: str) -> None:
    if _find_style(styles, style_id) is not None:
        return
    style = etree.SubElement(styles, qn("w:style"))
    style.set(qn("w:type"), "character")
    style.set(qn("w:styleId"), style_id)
    _style_value_child(style, "w:name", display_name)
    _style_value_child(style, "w:basedOn", "DefaultParagraphFont")
    _style_value_child(style, "w:uiPriority", "99")
    etree.SubElement(style, qn("w:semiHidden"))
    etree.SubElement(style, qn("w:unhideWhenUsed"))
    properties = etree.SubElement(style, qn("w:rPr"))
    _style_value_child(properties, "w:vertAlign", "superscript")


def _ensure_note_text_style(styles, style_id: str, display_name: str) -> None:
    if _find_style(styles, style_id) is not None:
        return
    style = etree.SubElement(styles, qn("w:style"))
    style.set(qn("w:type"), "paragraph")
    style.set(qn("w:styleId"), style_id)
    _style_value_child(style, "w:name", display_name)
    _style_value_child(style, "w:basedOn", "Normal")
    _style_value_child(style, "w:uiPriority", "99")
    etree.SubElement(style, qn("w:semiHidden"))
    etree.SubElement(style, qn("w:unhideWhenUsed"))
    properties = etree.SubElement(style, qn("w:pPr"))
    spacing = etree.SubElement(properties, qn("w:spacing"))
    spacing.set(qn("w:after"), "0")
    run_properties = etree.SubElement(style, qn("w:rPr"))
    _style_value_child(run_properties, "w:sz", "20")
    _style_value_child(run_properties, "w:szCs", "20")


def _find_style(styles, style_id: str):
    for style in styles.findall(qn("w:style")):
        if style.get(qn("w:styleId")) == style_id:
            return style
    return None


def _style_value_child(parent, tag: str, value: str):
    child = etree.SubElement(parent, qn(tag))
    child.set(qn("w:val"), value)
    return child


def _rewrite_zip(path: Path, replacements: dict[str, bytes]) -> None:
    descriptor, temp_name = mkstemp(
        prefix=f".{path.stem}-package-",
        suffix=".tmp",
        dir=str(path.parent),
    )
    os.close(descriptor)
    temp_path = Path(temp_name)
    try:
        written: set[str] = set()
        with ZipFile(path, "r") as source, ZipFile(temp_path, "w") as target:
            source_names = set(source.namelist())
            for info in source.infolist():
                replacement = replacements.get(info.filename)
                if replacement is not None:
                    target.writestr(info, replacement)
                    written.add(info.filename)
                    continue
                with source.open(info, "r") as input_file, target.open(
                    info,
                    "w",
                    force_zip64=True,
                ) as output_file:
                    shutil.copyfileobj(input_file, output_file, length=1024 * 1024)
            for name, data in replacements.items():
                if name not in written and name not in source_names:
                    target.writestr(name, data, compress_type=ZIP_DEFLATED)
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def _read_required_part(archive: ZipFile, name: str) -> bytes:
    try:
        return archive.read(name)
    except KeyError as exc:
        raise ValueError(f"生成的 DOCX 缺少 {name}。") from exc
