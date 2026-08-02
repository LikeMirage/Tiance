from __future__ import annotations

import re

from .markdown_blocks import is_code_fence_closer, parse_code_fence


HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
INVALID_XML_CHARACTER_RE = re.compile(
    r"[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]"
)


def sanitize_xml_text(content: str) -> tuple[str, int]:
    matches = INVALID_XML_CHARACTER_RE.findall(content)
    if not matches:
        return content, 0
    return INVALID_XML_CHARACTER_RE.sub("\ufffd", content), len(matches)


def prepare_markdown_content(content: str) -> tuple[str, dict[str, str], dict[str, str]]:
    chunks = _split_fenced_code_blocks(content.lstrip("\ufeff").split("\n"))
    prepared_chunks: list[str] = []
    footnotes: dict[str, str] = {}
    endnotes: dict[str, str] = {}
    for is_code_block, lines in chunks:
        chunk = "\n".join(lines)
        if is_code_block:
            prepared_chunks.append(chunk)
            continue
        chunk = HTML_COMMENT_RE.sub("", chunk)
        body, chunk_footnotes, chunk_endnotes = _extract_note_definitions(chunk)
        prepared_chunks.append(body)
        footnotes.update(chunk_footnotes)
        endnotes.update(chunk_endnotes)
    return "\n".join(prepared_chunks), footnotes, endnotes


def _split_fenced_code_blocks(lines: list[str]) -> list[tuple[bool, list[str]]]:
    chunks: list[tuple[bool, list[str]]] = []
    current: list[str] = []
    opener = ""
    for line in lines:
        fence = parse_code_fence(line) if not opener else None
        if fence is not None:
            if current:
                chunks.append((False, current))
            current = [line]
            opener = fence[0]
            continue
        current.append(line)
        if opener and is_code_fence_closer(line, opener):
            chunks.append((True, current))
            current = []
            opener = ""
    if current:
        chunks.append((bool(opener), current))
    return chunks


def _extract_note_definitions(content: str) -> tuple[str, dict[str, str], dict[str, str]]:
    body_lines: list[str] = []
    footnotes: dict[str, str] = {}
    endnotes: dict[str, str] = {}
    lines = content.split("\n")
    index = 0
    while index < len(lines):
        match = re.match(r"^\[\^([^\]]+)\]:\s*(.*)$", lines[index].strip())
        if match is None:
            body_lines.append(lines[index])
            index += 1
            continue
        raw_label = match.group(1).strip()
        parts = [match.group(2).strip()]
        index += 1
        while index < len(lines):
            current = lines[index]
            if current.startswith(("    ", "\t")):
                parts.append(current.strip())
                index += 1
                continue
            if (
                not current.strip()
                and index + 1 < len(lines)
                and lines[index + 1].startswith(("    ", "\t"))
            ):
                parts.append("")
                index += 1
                continue
            break
        text = "\n".join(parts).strip()
        if raw_label.startswith("end:"):
            key = raw_label[4:].strip()
            if key:
                endnotes[key] = text
        elif raw_label:
            footnotes[raw_label] = text
    return "\n".join(body_lines), footnotes, endnotes
