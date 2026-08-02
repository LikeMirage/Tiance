from __future__ import annotations

import re
from dataclasses import dataclass

from smart_quotes import normalize_double_quotes
from text_scanning import is_escaped


BACKTICK_RUN_RE = re.compile(r"`+")
INLINE_TOKEN_RE = re.compile(
    r"\[\^(?:end:)?[^\]\n]+\]"
    r"|\*\*[^*\n]+?\*\*"
    r"|__[^_\n]+?__"
    r"|~~[^~\n]+?~~"
    r"|(?<!\*)\*[^\s*](?:[^*\n]*?[^\s*])?\*(?!\*)"
)
HTML_TAG_RE = re.compile(r"</?\s*[A-Za-z][\w:-]*(?:\s+[^<>]*)?/?>")
HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
MARKDOWN_ESCAPE_RE = re.compile(r"\\([!\"#$%&'()*+,\-./:;<=>?@\[\\\]^_`{|}~])")


@dataclass(frozen=True, slots=True)
class InlineToken:
    start: int
    end: int
    kind: str
    raw: str
    value: str


def tokenize_inline(text: str, start: int = 0):
    position = max(0, start)
    plain_start = position
    while position < len(text):
        token = _match_token_at(text, position)
        if token is None:
            position += 1
            continue
        if plain_start < position:
            yield InlineToken(
                start=plain_start,
                end=position,
                kind="plain",
                raw=text[plain_start:position],
                value=text[plain_start:position],
            )
        yield token
        position = token.end
        plain_start = position
    if plain_start < len(text):
        yield InlineToken(
            start=plain_start,
            end=len(text),
            kind="plain",
            raw=text[plain_start:],
            value=text[plain_start:],
        )


def find_next_inline_token(text: str, start: int) -> tuple[int, int, str, str, str] | None:
    for token in tokenize_inline(text, start):
        if token.kind != "plain":
            return token.start, token.end, token.kind, token.raw, token.value
    return None


def parse_image_token(token: str) -> tuple[str, str] | None:
    match = re.match(r"^!\[([^\]]*)\]\((.*)\)$", token, flags=re.DOTALL)
    if match is None:
        return None
    destination = _link_destination(match.group(2))
    return (match.group(1), destination) if destination else None


def parse_link_token(token: str) -> tuple[str, str] | None:
    match = re.match(r"^\[([^\]]+)\]\((.*)\)$", token, flags=re.DOTALL)
    if match is None:
        return None
    destination = _link_destination(match.group(2))
    return (match.group(1), destination) if destination else None


def strip_html_tags(text: str) -> str:
    return HTML_TAG_RE.sub("", HTML_COMMENT_RE.sub("", text))


def unescape_markdown(text: str) -> str:
    return MARKDOWN_ESCAPE_RE.sub(r"\1", text)


def normalize_typographic_double_quotes(text: str) -> str:
    """Normalize straight quotes only where Markdown renders visible prose."""
    if '"' not in text:
        return text
    eligible = [False] * len(text)
    for token in tokenize_inline(text):
        if token.kind == "plain":
            _mark_plain_text_quotes(eligible, token)
            continue
        if token.kind != "format":
            continue
        _mark_format_text_quotes(eligible, token)
    return normalize_double_quotes(text, eligible=eligible)


def _mark_plain_text_quotes(eligible: list[bool], token: InlineToken) -> None:
    _mark_range(eligible, token.start, token.end)
    for pattern in (HTML_COMMENT_RE, HTML_TAG_RE):
        for match in pattern.finditer(token.raw):
            _clear_range(
                eligible,
                token.start + match.start(),
                token.start + match.end(),
            )


def _mark_format_text_quotes(eligible: list[bool], token: InlineToken) -> None:
    raw = token.raw
    if raw.startswith("[^"):
        return
    if raw.startswith("![") or raw.startswith("["):
        label_start = 2 if raw.startswith("![") else 1
        label_end = _find_balanced_closer(raw, label_start - 1, "[", "]")
        if label_end >= label_start:
            _mark_range(
                eligible,
                token.start + label_start,
                token.start + label_end,
            )
        return
    delimiter_size = 2 if raw.startswith(("**", "__", "~~")) else 1
    if len(raw) > delimiter_size * 2:
        _mark_range(
            eligible,
            token.start + delimiter_size,
            token.end - delimiter_size,
        )


def _mark_range(eligible: list[bool], start: int, end: int) -> None:
    for index in range(max(0, start), min(len(eligible), end)):
        eligible[index] = True


def _clear_range(eligible: list[bool], start: int, end: int) -> None:
    for index in range(max(0, start), min(len(eligible), end)):
        eligible[index] = False


def _match_token_at(text: str, position: int) -> InlineToken | None:
    if is_escaped(text, position):
        return None
    if (
        text[position] == "["
        and position > 0
        and text[position - 1] == "!"
        and is_escaped(text, position - 1)
    ):
        return None
    if text[position] == "`":
        code_span = _find_code_span_at(text, position)
        if code_span is not None:
            end, value = code_span
            return InlineToken(position, end, "code", text[position:end], value)
    if text[position] == "$":
        math_span = _find_inline_math_span_at(text, position)
        if math_span is not None:
            end, value = math_span
            return InlineToken(position, end, "math", text[position:end], value)
    if text.startswith(r"\(", position):
        closer = _find_sequence_closer(text, position + 2, r"\)")
        if closer >= 0:
            end = closer + 2
            return InlineToken(position, end, "math", text[position:end], text[position + 2 : closer])
    if text[position] in {"!", "["}:
        link_end = _find_markdown_link_end(text, position)
        if link_end is not None:
            return InlineToken(
                position,
                link_end,
                "format",
                text[position:link_end],
                "",
            )
    formatting = INLINE_TOKEN_RE.match(text, position)
    if formatting is None:
        return None
    return InlineToken(
        start=position,
        end=formatting.end(),
        kind="format",
        raw=formatting.group(0),
        value="",
    )


def _find_code_span_at(text: str, opener_start: int) -> tuple[int, str] | None:
    opener = BACKTICK_RUN_RE.match(text, opener_start)
    if opener is None:
        return None
    delimiter_length = len(opener.group(0))
    closer_search_from = opener.end()
    while closer := BACKTICK_RUN_RE.search(text, closer_search_from):
        if len(closer.group(0)) == delimiter_length and not is_escaped(text, closer.start()):
            value = text[opener.end() : closer.start()].replace("\n", " ")
            if value.startswith(" ") and value.endswith(" ") and value.strip():
                value = value[1:-1]
            return closer.end(), value
        closer_search_from = closer.end()
    return None


def _find_inline_math_span_at(text: str, opener_index: int) -> tuple[int, str] | None:
    if text[opener_index] != "$" or is_escaped(text, opener_index):
        return None
    if opener_index > 0 and text[opener_index - 1] == "$" and not is_escaped(text, opener_index - 1):
        return None
    delimiter = "$$" if text.startswith("$$", opener_index) else "$"
    closer_index = _find_math_closer(text, opener_index + len(delimiter), delimiter)
    if closer_index < 0:
        return None
    content = text[opener_index + len(delimiter) : closer_index]
    end = closer_index + len(delimiter)
    if not _is_inline_math_candidate(text, content, opener_index, end, delimiter):
        return None
    return end, content


def _find_math_closer(text: str, start: int, delimiter: str) -> int:
    index = start
    while index < len(text):
        index = text.find(delimiter, index)
        if index < 0:
            return -1
        if is_escaped(text, index):
            index += len(delimiter)
            continue
        if delimiter == "$" and (
            (index > 0 and text[index - 1] == "$")
            or (index + 1 < len(text) and text[index + 1] == "$")
        ):
            index += 1
            continue
        return index
    return -1


def _is_inline_math_candidate(
    text: str,
    content: str,
    opener_index: int,
    end: int,
    delimiter: str,
) -> bool:
    if not content or "\n" in content or content != content.strip():
        return False
    if delimiter == "$$":
        return True
    if content[0].isdigit():
        if end < len(text) and text[end].isdigit():
            return False
        if re.search(r"[\u3400-\u9fff，。；！？]", content):
            return False
        if re.search(r"\s+[A-Za-z]{2,}", content):
            return False
    return opener_index == 0 or text[opener_index - 1] != "$"


def _find_sequence_closer(text: str, start: int, delimiter: str) -> int:
    position = start
    while True:
        position = text.find(delimiter, position)
        if position < 0:
            return -1
        if not is_escaped(text, position):
            return position
        position += len(delimiter)


def _find_markdown_link_end(text: str, position: int) -> int | None:
    label_start = position + 1 if text.startswith("![", position) else position
    if label_start >= len(text) or text[label_start] != "[":
        return None
    label_end = _find_balanced_closer(text, label_start, "[", "]")
    if label_end < 0 or label_end + 1 >= len(text) or text[label_end + 1] != "(":
        return None
    destination_end = _find_balanced_closer(text, label_end + 1, "(", ")")
    return destination_end + 1 if destination_end >= 0 else None


def _find_balanced_closer(text: str, opener: int, opening: str, closing: str) -> int:
    depth = 0
    position = opener
    while position < len(text):
        if is_escaped(text, position):
            position += 1
            continue
        character = text[position]
        if character == opening:
            depth += 1
        elif character == closing:
            depth -= 1
            if depth == 0:
                return position
        if character == "\n":
            return -1
        position += 1
    return -1


def _link_destination(raw_value: str) -> str:
    value = raw_value.strip()
    if not value:
        return ""
    if value.startswith("<"):
        closing = value.find(">")
        if closing < 0:
            return ""
        return unescape_markdown(value[1:closing].strip())
    title_match = re.match(r"^(.*?)(?:\s+(?:\"[^\"]*\"|'[^']*'|\([^()]*\)))\s*$", value)
    if title_match is not None:
        value = title_match.group(1).rstrip()
    return unescape_markdown(value)
