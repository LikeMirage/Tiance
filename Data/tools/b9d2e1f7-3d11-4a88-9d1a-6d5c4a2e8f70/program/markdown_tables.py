from __future__ import annotations

import re
from dataclasses import dataclass


class MarkdownTableError(ValueError):
    pass


@dataclass(frozen=True)
class ParsedTable:
    title: str | None
    rows: list[list[str]]
    start_line: int


_HIDDEN_FORMAT = re.compile(
    r"<!--\s*md2xlsx-format\s*\n(?P<body>.*?)\n\s*-->",
    re.IGNORECASE | re.DOTALL,
)
_SEPARATOR = re.compile(r":?-{3,}:?")


def split_row(line: str) -> list[str]:
    value = line.strip()
    if not value.startswith("|") or not value.endswith("|"):
        raise MarkdownTableError("表格行必须以 | 开头并以 | 结尾。")
    cells: list[str] = []
    current: list[str] = []
    escaped = False
    for char in value[1:-1]:
        if escaped:
            current.append(char if char == "|" else "\\" + char)
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == "|":
            cells.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    if escaped:
        current.append("\\")
    cells.append("".join(current).strip())
    return cells


def is_separator(line: str) -> bool:
    try:
        cells = split_row(line)
    except MarkdownTableError:
        return False
    return bool(cells) and all(_SEPARATOR.fullmatch(cell.replace(" ", "")) for cell in cells)


def parse_tables(markdown: str) -> list[ParsedTable]:
    lines = markdown.splitlines()
    tables: list[ParsedTable] = []
    index = 0
    while index < len(lines):
        if (
            index + 1 >= len(lines)
            or not lines[index].strip().startswith("|")
            or not lines[index].strip().endswith("|")
            or not is_separator(lines[index + 1])
        ):
            index += 1
            continue
        header = split_row(lines[index])
        separator = split_row(lines[index + 1])
        if len(header) != len(separator):
            raise MarkdownTableError(f"表头和分隔线列数不一致（第 {index + 1} 行）。")
        rows = [header]
        width = len(header)
        start_line = index + 1
        index += 2
        while index < len(lines):
            text = lines[index].strip()
            if not text or not text.startswith("|") or not text.endswith("|"):
                break
            row = split_row(lines[index])
            if len(row) > width:
                raise MarkdownTableError(f"表格列数超过表头列数（第 {index + 1} 行）。")
            rows.append(row + [""] * (width - len(row)))
            index += 1
        title = _title_before(lines, start_line - 1)
        tables.append(ParsedTable(title=title, rows=rows, start_line=start_line))
    return tables


def extract_hidden_format(markdown: str) -> str | None:
    matches = list(_HIDDEN_FORMAT.finditer(markdown))
    if not matches:
        return None
    return "\n\n".join(match.group("body").strip() for match in matches)


def strip_hidden_format(markdown: str) -> str:
    """Remove format blocks before parsing the visible content tables."""
    return _HIDDEN_FORMAT.sub("", markdown)


def _title_before(lines: list[str], table_index: int) -> str | None:
    index = table_index - 1
    while index >= 0 and not lines[index].strip():
        index -= 1
    if index < 0:
        return None
    value = lines[index].strip()
    heading = re.match(r"^#{1,6}\s+(.+?)\s*#*\s*$", value)
    return heading.group(1).strip() if heading else value
