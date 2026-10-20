"""Bounded, streaming inspection. Called only in the disposable preview process."""
from pathlib import Path
import posixpath
import re
import xml.etree.ElementTree as ET
from zipfile import ZipFile

from . import policy

CELL_ADDRESS = re.compile(r"^([A-Z]{1,3})([1-9][0-9]{0,6})$")


def cell_position(address: str) -> tuple[int, int]:
    match = CELL_ADDRESS.fullmatch(address)
    if not match:
        raise ValueError("工作簿包含无效的单元格地址。")
    column = 0
    for char in match[1]:
        column = column * 26 + ord(char) - 64
    row = int(match[2])
    if row > 1_048_576 or column > 16_384:
        raise ValueError("工作簿单元格地址超出格式范围。")
    return row - 1, column - 1


def tag_name(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


class Package:
    def __init__(self, path: Path):
        self.archive = ZipFile(path)
        self.read_bytes = 0
        self.nodes = 0
        try:
            infos = self.archive.infolist()
            self.expanded_bytes = sum(item.file_size for item in infos)
            if len(infos) > policy.MAX_PACKAGE_ENTRIES:
                raise policy.PreviewLimit(f"压缩包超过 {policy.MAX_PACKAGE_ENTRIES} 个条目，停止内置预览。")
            if self.expanded_bytes > policy.MAX_EXPANDED_BYTES:
                raise policy.PreviewLimit("解压后超过 256 MiB，停止内置预览。")
            if len({item.filename for item in infos}) != len(infos):
                raise ValueError("压缩包包含重复条目。")
            if any(item.flag_bits & 1 for item in infos):
                raise ValueError("暂不支持预览加密文档。")
        except BaseException:
            self.archive.close()
            raise

    def close(self):
        self.archive.close()

    def events(self, name: str):
        """Feed small chunks; reject entities and enforce actual inflated bytes."""
        parser = ET.XMLPullParser(events=("start", "end"))
        tail = b""
        bytes_without_event = 0
        with self.archive.open(name) as stream:
            while chunk := stream.read(32 * 1024):
                self.read_bytes += len(chunk)
                if self.read_bytes > policy.MAX_EXPANDED_BYTES:
                    raise policy.PreviewLimit("实际解压读取超过 256 MiB，停止预览。")
                checked = (tail + chunk).replace(b"\x00", b"").upper()
                if b"<!DOCTYPE" in checked or b"<!ENTITY" in checked:
                    raise ValueError("文档 XML 不允许包含 DTD 或实体声明。")
                tail = chunk[-64:]
                bytes_without_event += len(chunk)
                if bytes_without_event > policy.MAX_XML_TOKEN_BYTES:
                    raise policy.PreviewLimit("XML 单个文本或属性超过 1 MiB，停止预览。")
                parser.feed(chunk)
                for event, element in parser.read_events():
                    bytes_without_event = 0
                    if event == "start":
                        self.nodes += 1
                        if self.nodes > policy.MAX_XML_NODES:
                            raise policy.PreviewLimit("文档结构超过 200 万个 XML 节点，停止预览。")
                    yield event, element
            parser.close()

    def small_xml(self, name: str) -> ET.Element:
        if self.archive.getinfo(name).file_size > policy.MAX_RENDER_XML_BYTES:
            raise policy.PreviewLimit("文档索引超过 4 MiB，停止预览。")
        root = None
        for event, element in self.events(name):
            if root is None and event == "start":
                root = element
        if root is None:
            raise ValueError("文档索引为空。")
        return root


def workbook_sheets(package: Package) -> tuple[list[dict], bool]:
    relationships = package.small_xml("xl/_rels/workbook.xml.rels")
    targets = {
        item.get("Id"): posixpath.normpath(
            item.get("Target", "").lstrip("/") if item.get("Target", "").startswith("/")
            else "xl/" + item.get("Target", "")
        )
        for item in relationships
        if item.get("TargetMode") != "External"
    }
    workbook = package.small_xml("xl/workbook.xml")
    sheets = []
    date1904 = False
    for element in workbook.iter():
        if tag_name(element) == "workbookPr":
            date1904 = element.get("date1904") in ("1", "true")
        if tag_name(element) != "sheet":
            continue
        relation = next((v for k, v in element.attrib.items() if k.endswith("}id")), None)
        target = targets.get(relation)
        if not target or not target.startswith("xl/worksheets/"):
            raise ValueError("工作簿的工作表关系无效或不受支持。")
        sheets.append({"name": element.get("name", f"Sheet{len(sheets) + 1}"), "part": target})
    if not sheets:
        raise ValueError("工作簿没有工作表。")
    return sheets, date1904


def inspect_workbook(package: Package) -> dict:
    sheets, _ = workbook_sheets(package)
    total_cells = total_merges = 0
    for sheet in sheets:
        rows = columns = cells = merges = 0
        stack = []
        for event, element in package.events(sheet["part"]):
            if event == "start":
                stack.append(element)
                continue
            tag = tag_name(element)
            if tag == "c":
                row, column = cell_position(element.get("r", ""))
                rows, columns = max(rows, row + 1), max(columns, column + 1)
                cells += 1
            elif tag == "mergeCell":
                last = element.get("ref", "").split(":")[-1]
                row, column = cell_position(last)
                rows, columns = max(rows, row + 1), max(columns, column + 1)
                merges += 1
            element.clear()
            stack.pop()
            if stack:
                stack[-1].remove(element)
        sheet.update(rows=max(1, rows), columns=max(1, columns))
        total_cells += cells
        total_merges += merges
        del sheet["part"]
    paged = (total_cells > policy.MAX_INLINE_CELLS or total_merges > policy.MAX_INLINE_MERGES
             or package.expanded_bytes > policy.MAX_RENDER_XML_BYTES
             or sum(s["rows"] * s["columns"] for s in sheets) > policy.MAX_INLINE_CELLS)
    return {
        "mode": "paged" if paged else "inline",
        "sheets": sheets, "cells": total_cells, "merges": total_merges,
        "page_rows": policy.PAGE_ROWS, "page_columns": policy.PAGE_COLUMNS,
    }


def inspect_image(path_or_stream) -> tuple[int, int]:
    from PIL import Image
    with Image.open(path_or_stream) as image:
        width, height = image.size
        if width * height > policy.MAX_IMAGE_PIXELS:
            raise policy.PreviewLimit("图片超过 2400 万像素，停止内置解码。")
        # Animated files may retain many decoded frames.
        if width * height * getattr(image, "n_frames", 1) > policy.MAX_IMAGE_PIXELS * 2:
            raise policy.PreviewLimit("动画累计帧像素超过 4800 万，停止内置解码。")
        return width, height


def inspect_file(path: Path) -> dict:
    size = path.stat().st_size
    extension = path.suffix.lower()
    result = {"mode": "inline", "size_bytes": size}
    if extension in (".xlsx", ".docx", ".pptx"):
        if size > policy.MAX_PACKAGE_BYTES:
            raise policy.PreviewLimit("Office 文件超过 64 MiB，停止内置预览。")
        package = Package(path)
        try:
            if extension == ".xlsx":
                result.update(inspect_workbook(package))
            else:
                xml_bytes = sum(i.file_size for i in package.archive.infolist() if i.filename.lower().endswith((".xml", ".svg")))
                if xml_bytes > policy.MAX_RENDER_XML_BYTES or package.expanded_bytes > policy.MAX_RENDER_PACKAGE_BYTES:
                    raise policy.PreviewLimit("文档超过内置排版预算（XML 4 MiB / 解压后 32 MiB），请用默认应用打开。")
                slides = sum(bool(re.fullmatch(r"ppt/slides/slide\d+\.xml", n)) for n in package.archive.namelist())
                if slides > policy.MAX_PRESENTATION_SLIDES:
                    raise policy.PreviewLimit("演示文稿超过 40 页，请用默认应用打开。")
                image_pixels = 0
                paragraphs = table_cells = 0
                for info in package.archive.infolist():
                    if info.filename.lower().endswith((".xml", ".svg")):
                        root = None
                        for event, element in package.events(info.filename):
                            if root is None:
                                root = element
                            if event == "start" and extension == ".docx":
                                paragraphs += tag_name(element) == "p"
                                table_cells += tag_name(element) == "tc"
                                if paragraphs > policy.MAX_WORD_PARAGRAPHS or table_cells > policy.MAX_WORD_TABLE_CELLS:
                                    raise policy.PreviewLimit("Word 超过内置排版预算（1500 段 / 2000 个表格单元格），请用默认应用打开。")
                            if event == "end":
                                element.clear()
                                root.clear()
                            if package.nodes > policy.MAX_RENDER_NODES:
                                raise policy.PreviewLimit("文档超过 2 万个排版节点，请用默认应用打开。")
                    elif "/media/" in info.filename:
                        with package.archive.open(info) as stream:
                            try:
                                width, height = inspect_image(stream)
                                image_pixels += width * height
                            except policy.PreviewLimit:
                                raise
                            except (OSError, ValueError):
                                raise policy.PreviewLimit("文档含无法估算解码开销的媒体，请用默认应用打开。") from None
                        if image_pixels > policy.MAX_IMAGE_PIXELS * 2:
                            raise policy.PreviewLimit("文档内图片累计超过 4800 万像素，请用默认应用打开。")
            result["expanded_bytes"] = package.expanded_bytes
        finally:
            package.close()
    elif extension == ".xls":
        raise policy.PreviewLimit("旧版 XLS 格式请用默认应用打开，或另存为 XLSX 后预览。")
    elif extension in (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".ico"):
        if size > policy.MAX_IMAGE_BYTES:
            raise policy.PreviewLimit("图片文件超过 32 MiB，请用默认应用打开。")
        result["width"], result["height"] = inspect_image(path)
    elif extension == ".svg":
        # SVG remains a browser-rendered image, with no scripts.
        if size > policy.MAX_SVG_BYTES:
            raise policy.PreviewLimit("SVG 超过 1 MiB，请用默认应用打开。")
    # PDF is paged by PDF.js, video streams in the native media element, SQLite
    # has a paginated query API. Their file size is not their resident size.
    return result
