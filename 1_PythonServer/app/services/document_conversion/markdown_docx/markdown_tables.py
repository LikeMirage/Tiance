from __future__ import annotations

import re

from .text_scanning import is_escaped


def is_table_start(lines: list[str], index: int) -> bool:
    if index + 1 >= len(lines):
        return False
    header_line = lines[index].strip()
    separator_line = lines[index + 1].strip()
    if "|" not in header_line or "|" not in separator_line:
        return False
    if not _is_table_separator(separator_line):
        return False
    return len(parse_table_row(header_line)) == len(parse_table_row(separator_line))


def parse_table_row(line: str) -> list[str]:
    text = line.strip()
    if text.startswith("|"):
        text = text[1:]
    if text.endswith("|") and not text.endswith(r"\|"):
        text = text[:-1]
    cells: list[str] = []
    current: list[str] = []
    math_closer = ""
    code_delimiter_length = 0
    index = 0
    while index < len(text):
        char = text[index]
        if char == "\\":
            sequence = text[index : index + 2]
            if code_delimiter_length == 0 and sequence in {r"\(", r"\["} and not math_closer:
                possible_closer = r"\)" if sequence == r"\(" else r"\]"
                if _find_unescaped(text, possible_closer, index + 2) >= 0:
                    math_closer = possible_closer
                    current.append(sequence)
                    index += 2
                    continue
            if code_delimiter_length == 0 and math_closer and sequence == math_closer:
                math_closer = ""
                current.append(sequence)
                index += 2
                continue
            if index + 1 < len(text) and text[index + 1] == "|":
                current.append(r"\|" if math_closer or code_delimiter_length else "|")
                index += 2
                continue
            current.append(char)
            index += 1
            continue
        if char == "`":
            run_end = index + 1
            while run_end < len(text) and text[run_end] == "`":
                run_end += 1
            run_length = run_end - index
            if code_delimiter_length == 0:
                if _has_code_closer(text, run_end, run_length):
                    code_delimiter_length = run_length
            elif code_delimiter_length == run_length:
                code_delimiter_length = 0
            current.append(text[index:run_end])
            index = run_end
            continue
        if code_delimiter_length == 0 and char == "$":
            delimiter = "$$" if text.startswith("$$", index) else "$"
            if math_closer == delimiter:
                math_closer = ""
            elif not math_closer and _find_unescaped(
                text,
                delimiter,
                index + len(delimiter),
            ) >= 0:
                math_closer = delimiter
            current.append(delimiter)
            index += len(delimiter)
            continue
        if char == "|":
            if math_closer or code_delimiter_length:
                current.append(char)
            else:
                cells.append("".join(current).strip())
                current = []
            index += 1
            continue
        current.append(char)
        index += 1
    cells.append("".join(current).strip())
    return cells


def parse_table_alignments(line: str) -> list[str]:
    result: list[str] = []
    for cell in parse_table_row(line):
        if cell.startswith(":") and cell.endswith(":"):
            result.append("center")
        elif cell.endswith(":"):
            result.append("right")
        elif cell.startswith(":"):
            result.append("left")
        else:
            result.append("default")
    return result


def normalize_row(row: list[str], width: int) -> list[str]:
    return (row + [""] * width)[:width]


def header_alignment(alignments: list[str], column: int) -> str:
    alignment = alignments[column] if column < len(alignments) else "default"
    return "center" if alignment == "default" else alignment


def body_alignment(alignments: list[str], column: int) -> str:
    alignment = alignments[column] if column < len(alignments) else "default"
    return "left" if alignment == "default" else alignment


def _is_table_separator(line: str) -> bool:
    cells = parse_table_row(line)
    return bool(cells) and all(re.fullmatch(r":?-{2,}:?", cell.strip()) for cell in cells)


def _find_unescaped(text: str, delimiter: str, start: int) -> int:
    position = start
    while True:
        position = text.find(delimiter, position)
        if position < 0:
            return -1
        if not is_escaped(text, position):
            return position
        position += len(delimiter)


def _has_code_closer(text: str, start: int, delimiter_length: int) -> bool:
    position = start
    while match := re.search(r"`+", text[position:]):
        run_start = position + match.start()
        if len(match.group(0)) == delimiter_length and not is_escaped(text, run_start):
            return True
        position += match.end()
    return False
