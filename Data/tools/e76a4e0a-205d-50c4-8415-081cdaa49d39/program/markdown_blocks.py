from __future__ import annotations

import re
from typing import Any

from markdown_inline import parse_image_token
from markdown_tables import is_table_start


BLOCK_HTML_TAGS = {
    "article",
    "aside",
    "blockquote",
    "center",
    "details",
    "div",
    "figure",
    "footer",
    "header",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "hr",
    "li",
    "ol",
    "p",
    "section",
    "svg",
    "summary",
    "table",
    "pre",
    "ul",
}
VOID_HTML_TAGS = {"hr"}
CODE_FENCE_RE = re.compile(r"^(`{3,}|~{3,})(.*)$")


def collect_paragraph(lines: list[str], start: int) -> tuple[str, int]:
    parts: list[tuple[str, bool]] = []
    index = start
    while index < len(lines):
        raw_line = lines[index].lstrip("\ufeff")
        stripped = raw_line.strip()
        if not stripped or (index > start and _starts_block(lines, index)):
            break
        hard_break = _has_hard_break(raw_line)
        if hard_break and stripped.endswith("\\"):
            stripped = stripped[:-1].rstrip()
        parts.append((stripped, hard_break))
        index += 1
    if not parts:
        return "", index
    paragraph = parts[0][0]
    for part_index in range(1, len(parts)):
        separator = "\n" if parts[part_index - 1][1] else " "
        paragraph += separator + parts[part_index][0]
    return paragraph, index


def collect_blockquote(lines: list[str], start: int) -> tuple[list[str], int]:
    paragraphs: list[str] = []
    parts: list[tuple[str, bool]] = []
    index = start
    while index < len(lines) and lines[index].strip().startswith(">"):
        raw_line = re.sub(r"^\s*>\s?", "", lines[index])
        stripped = raw_line.strip()
        if not stripped:
            _append_joined_lines(paragraphs, parts)
            parts = []
            index += 1
            continue
        hard_break = _has_hard_break(raw_line)
        if hard_break and stripped.endswith("\\"):
            stripped = stripped[:-1].rstrip()
        parts.append((stripped, hard_break))
        index += 1
    _append_joined_lines(paragraphs, parts)
    return paragraphs, index - 1


def read_code_block_language(fence_line: str) -> str:
    fence = parse_code_fence(fence_line)
    return fence[1] if fence is not None else ""


def parse_code_fence(fence_line: str) -> tuple[str, str] | None:
    match = CODE_FENCE_RE.match(fence_line.strip())
    if match is None:
        return None
    marker, raw_info = match.groups()
    if marker.startswith("`") and "`" in raw_info:
        return None
    info = raw_info.strip()
    language = info.split(maxsplit=1)[0].lower() if info else ""
    return marker, language


def is_code_fence_closer(line: str, opener: str) -> bool:
    marker = line.strip()
    return re.fullmatch(rf"{re.escape(opener[0])}{{{len(opener)},}}\s*", marker) is not None


def parse_html_block(lines: list[str], start: int) -> dict[str, Any] | None:
    if start >= len(lines):
        return None
    first_line = lines[start].strip()
    match = re.match(r"^<\s*([a-zA-Z][\w:-]*)\b", first_line)
    if match is None:
        return None
    root_tag = match.group(1).lower()
    if root_tag not in BLOCK_HTML_TAGS:
        return None
    if root_tag in VOID_HTML_TAGS:
        return _html_result([first_line], start, True, root_tag)
    if _is_balanced_html_block(first_line, root_tag):
        return {"content": first_line, "end_index": start, "closed": True, "root_tag": root_tag}

    block_lines = [lines[start]]
    depth = _html_tag_balance(first_line, root_tag)
    index = start + 1
    while index < len(lines):
        current = lines[index]
        if not current.strip():
            return _html_result(block_lines, index - 1, False, root_tag)
        block_lines.append(current)
        depth += _html_tag_balance(current, root_tag)
        if depth <= 0 and _contains_html_closing_tag("\n".join(block_lines), root_tag):
            return _html_result(block_lines, index, True, root_tag)
        index += 1
    return _html_result(block_lines, len(lines) - 1, False, root_tag)


def parse_list_item(line: str) -> dict[str, Any] | None:
    unordered = re.match(r"^(\s*)([-*+])\s+(.+)$", line)
    ordered = None if unordered else re.match(r"^(\s*)(\d+)[.)]\s+(.+)$", line)
    match = unordered or ordered
    if match is None:
        return None
    text = match.group(3).strip()
    task = None
    task_match = re.match(r"^\[([ xX])\]\s+(.+)$", text)
    if task_match is not None:
        task = "checked" if task_match.group(1).lower() == "x" else "unchecked"
        text = task_match.group(2).strip()
    level = min(len(match.group(1).replace("\t", "    ")) // 2, 8)
    marker = f"{match.group(2)}." if ordered is not None else _unordered_marker(level)
    return {
        "ordered": ordered is not None,
        "start": int(match.group(2)) if ordered is not None else 1,
        "level": level,
        "marker": marker,
        "text": text,
        "task": task,
    }


def _starts_block(lines: list[str], index: int) -> bool:
    stripped = lines[index].strip().lstrip("\ufeff")
    if not stripped:
        return True
    if stripped.upper() in {"[TOC]", "[[TOC]]"}:
        return True
    if stripped.startswith(("$$", r"\[")) or stripped == r"\(":
        return True
    if re.match(r"^#{1,9}\s+", stripped) or is_table_start(lines, index):
        return True
    if stripped in {"---", "***", "___"} or stripped.startswith(">"):
        return True
    if parse_code_fence(stripped) is not None:
        return True
    if parse_html_block(lines, index) is not None or parse_list_item(lines[index]) is not None:
        return True
    return parse_image_token(stripped) is not None


def _has_hard_break(line: str) -> bool:
    if line.endswith("  "):
        return True
    trailing_backslashes = len(line) - len(line.rstrip("\\"))
    return trailing_backslashes % 2 == 1


def _append_joined_lines(target: list[str], parts: list[tuple[str, bool]]) -> None:
    if not parts:
        return
    value = parts[0][0]
    for part_index in range(1, len(parts)):
        value += ("\n" if parts[part_index - 1][1] else " ") + parts[part_index][0]
    target.append(value)


def _html_result(
    lines: list[str],
    end_index: int,
    closed: bool,
    root_tag: str,
) -> dict[str, Any]:
    return {
        "content": "\n".join(lines).strip(),
        "end_index": end_index,
        "closed": closed,
        "root_tag": root_tag,
    }


def _is_balanced_html_block(line: str, tag: str) -> bool:
    return _html_tag_balance(line, tag) <= 0 and _contains_html_closing_tag(line, tag)


def _html_tag_balance(text: str, tag: str) -> int:
    opening = len(re.findall(rf"<\s*{re.escape(tag)}(?:\s|>|/)", text, flags=re.IGNORECASE))
    closing = len(re.findall(rf"</\s*{re.escape(tag)}\s*>", text, flags=re.IGNORECASE))
    return opening - closing


def _contains_html_closing_tag(text: str, tag: str) -> bool:
    return re.search(rf"</\s*{re.escape(tag)}\s*>", text, flags=re.IGNORECASE) is not None


def _unordered_marker(level: int) -> str:
    return ["•", "◦", "▪"][level % 3]
