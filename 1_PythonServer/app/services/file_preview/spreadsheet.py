"""Read only the requested rectangle; never construct a full workbook model."""
from datetime import datetime, timedelta
from pathlib import Path
import re

from . import policy
from .inspection import Package, cell_position, tag_name, workbook_sheets

_DATE_FORMATS = {14, 15, 16, 17, 18, 19, 20, 21, 22, 27, 30, 36, 45, 46, 47, 50, 57}


def _records(package: Package, part: str, record_tag: str):
    """Retain one record's descendants, remove completed records from parents."""
    stack = []
    inside = 0
    for event, element in package.events(part):
        tag = tag_name(element)
        if event == "start":
            stack.append(element)
            if tag == record_tag:
                inside += 1
        else:
            if tag == record_tag:
                yield element
                inside -= 1
            stack.pop()
            if inside == 0:
                element.clear()
                if stack:
                    stack[-1].remove(element)


def _date_styles(package: Package) -> set[int]:
    if "xl/styles.xml" not in package.archive.namelist():
        return set()
    root = package.small_xml("xl/styles.xml")
    custom = {}
    for element in root.iter():
        if tag_name(element) == "numFmt":
            custom[int(element.get("numFmtId", "0"))] = element.get("formatCode", "")
    styles = set()
    for element in root:
        if tag_name(element) != "cellXfs":
            continue
        for index, style in enumerate(element):
            number = int(style.get("numFmtId", "0"))
            fmt = re.sub(r'"[^"]*"|\\.|_.|\[[^\]]*\]' , "", custom.get(number, "")).lower()
            if number in _DATE_FORMATS or re.search(r"[ymdhis]", fmt):
                styles.add(index)
    return styles


def spreadsheet_page(path: Path, sheet_index: int, row_start: int, column_start: int) -> dict:
    if sheet_index < 0 or not 0 <= row_start < 1_048_576 or not 0 <= column_start < 16_384:
        raise ValueError("工作表或分页坐标无效。")
    package = Package(path)
    try:
        sheets, date1904 = workbook_sheets(package)
        if sheet_index >= len(sheets):
            raise ValueError("工作表不存在。")
        sheet = sheets[sheet_index]
        date_styles = _date_styles(package)
        rows = min(policy.PAGE_ROWS, 1_048_576 - row_start)
        columns = min(policy.PAGE_COLUMNS, 16_384 - column_start)
        values = [["" for _ in range(columns)] for _ in range(rows)]
        shared_indices: dict[int, list[tuple[int, int]]] = {}
        text_chars = 0
        for cell in _records(package, sheet["part"], "c"):
            row, column = cell_position(cell.get("r", ""))
            if row < row_start or row >= row_start + rows or not column_start <= column < column_start + columns:
                continue
            text = "".join(child.text or "" for child in cell.iter() if tag_name(child) in ("v", "t"))
            kind = cell.get("t")
            r, c = row - row_start, column - column_start
            if kind == "s":
                shared_indices.setdefault(int(text), []).append((r, c))
                continue
            if kind == "b":
                text = "TRUE" if text == "1" else "FALSE"
            elif kind not in ("str", "inlineStr", "e") and int(cell.get("s", "0")) in date_styles and text:
                try:
                    serial = float(text)
                    epoch = datetime(1904, 1, 1) if date1904 else datetime(1899, 12, 30)
                    # Excel's fictitious 1900 leap day is represented by its serial.
                    if not date1904 and 0 < serial < 60:
                        epoch = datetime(1899, 12, 31)
                    text = (epoch + timedelta(days=serial)).isoformat(sep=" ").removesuffix(" 00:00:00")
                except (ValueError, OverflowError):
                    pass
            text_chars += len(text)
            if text_chars > policy.MIB:
                raise policy.PreviewLimit("本页单元格文本超过 100 万字符，请用默认应用查看。")
            values[r][c] = text
        if shared_indices:
            if "xl/sharedStrings.xml" not in package.archive.namelist():
                raise ValueError("工作簿缺少共享字符串。")
            for index, item in enumerate(_records(package, "xl/sharedStrings.xml", "si")):
                targets = shared_indices.pop(index, None)
                if targets:
                    text = "".join(child.text or "" for child in item.iter() if tag_name(child) == "t")
                    text_chars += len(text) * len(targets)
                    if text_chars > policy.MIB:
                        raise policy.PreviewLimit("本页单元格文本超过 100 万字符，请用默认应用查看。")
                    for r, c in targets:
                        values[r][c] = text
            if shared_indices:
                raise ValueError("工作簿引用了不存在的共享字符串。")
        return {
            "sheet_name": sheet["name"], "row_start": row_start, "column_start": column_start,
            "values": values,
        }
    finally:
        package.close()
