from __future__ import annotations

import codecs
import locale
import os
from typing import Any


_CONTROL_STRING_INTRODUCERS = frozenset({"P", "X", "^", "_"})
_C1_CONTROL_STRING_INTRODUCERS = frozenset({0x90, 0x98, 0x9D, 0x9E, 0x9F})
_PRESERVED_CONTROLS = frozenset({"\t", "\n", "\r"})


def encode_stdin(text: str | None) -> bytes | None:
    if text is None:
        return None
    return text.encode("utf-8")


def prepare_process_output(
    output: Any,
    *,
    encoding_hint: str,
    max_chars: int,
) -> tuple[str, bool]:
    decoded = decode_process_output(output, encoding_hint=encoding_hint)
    cleaned = strip_terminal_controls(decoded)
    return truncate_text(cleaned, max_chars)


def decode_process_output(output: Any, *, encoding_hint: str) -> str:
    if output is None:
        return ""
    if isinstance(output, str):
        return output
    if not isinstance(output, (bytes, bytearray, memoryview)):
        return str(output)

    raw = bytes(output)
    if not raw:
        return ""

    bom_decoded = _decode_bom(raw)
    if bom_decoded is not None:
        return bom_decoded

    utf16_decoded = _decode_probable_utf16(raw)
    if utf16_decoded is not None:
        return utf16_decoded

    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        pass

    fallbacks = _fallback_encodings(encoding_hint)
    for encoding in fallbacks:
        try:
            return raw.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue

    final_encoding = fallbacks[-1] if fallbacks else "utf-8"
    try:
        return raw.decode(final_encoding, errors="replace")
    except LookupError:
        return raw.decode("utf-8", errors="replace")


def strip_terminal_controls(text: str) -> str:
    cleaned: list[str] = []
    index = 0
    while index < len(text):
        character = text[index]
        codepoint = ord(character)

        if character == "\x1b":
            index = _consume_escape_sequence(text, index)
            continue
        if codepoint == 0x9B:
            index = _consume_csi(text, index + 1)
            continue
        if codepoint in _C1_CONTROL_STRING_INTRODUCERS:
            index = _consume_control_string(
                text,
                index + 1,
                allow_bell=codepoint == 0x9D,
            )
            continue
        if (codepoint < 0x20 and character not in _PRESERVED_CONTROLS) or (
            0x7F <= codepoint <= 0x9F
        ):
            index += 1
            continue

        cleaned.append(character)
        index += 1
    return "".join(cleaned)


def truncate_text(text: str, max_chars: int) -> tuple[str, bool]:
    if len(text) <= max_chars:
        return text, False
    omitted = len(text) - max_chars
    return text[:max_chars] + f"\n...<truncated {omitted} chars>", True


def _decode_bom(raw: bytes) -> str | None:
    bom_encodings = (
        (codecs.BOM_UTF32_LE, "utf-32"),
        (codecs.BOM_UTF32_BE, "utf-32"),
        (codecs.BOM_UTF8, "utf-8-sig"),
        (codecs.BOM_UTF16_LE, "utf-16"),
        (codecs.BOM_UTF16_BE, "utf-16"),
    )
    for bom, encoding in bom_encodings:
        if raw.startswith(bom):
            return raw.decode(encoding, errors="replace")
    return None


def _decode_probable_utf16(raw: bytes) -> str | None:
    if len(raw) < 4 or len(raw) % 2:
        return None

    pair_count = len(raw) // 2
    even_nulls = raw[0::2].count(0)
    odd_nulls = raw[1::2].count(0)
    required_nulls = max(2, (pair_count + 3) // 4)

    if odd_nulls >= required_nulls and even_nulls <= max(1, pair_count // 10):
        encoding = "utf-16-le"
    elif even_nulls >= required_nulls and odd_nulls <= max(1, pair_count // 10):
        encoding = "utf-16-be"
    else:
        return None

    try:
        return raw.decode(encoding)
    except UnicodeDecodeError:
        return None


def _fallback_encodings(encoding_hint: str) -> tuple[str, ...]:
    preferred = locale.getpreferredencoding(False)
    if os.name != "nt":
        return _unique_encodings((preferred,))

    console, oem, ansi = _windows_code_page_encodings()
    if encoding_hint == "cmd":
        candidates = (console, oem, ansi, preferred)
    else:
        candidates = (console, preferred, ansi, oem)
    return _unique_encodings(candidates)


def _windows_code_page_encodings() -> tuple[str | None, str | None, str | None]:
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        code_pages = (
            int(kernel32.GetConsoleOutputCP()),
            int(kernel32.GetOEMCP()),
            int(kernel32.GetACP()),
        )
    except (AttributeError, OSError, ValueError):
        return None, None, None
    return (
        f"cp{code_pages[0]}" if code_pages[0] > 0 else None,
        f"cp{code_pages[1]}" if code_pages[1] > 0 else None,
        f"cp{code_pages[2]}" if code_pages[2] > 0 else None,
    )


def _unique_encodings(encodings: tuple[str | None, ...]) -> tuple[str, ...]:
    unique: list[str] = []
    seen: set[str] = set()
    for encoding in encodings:
        if not encoding:
            continue
        normalized = encoding.lower().replace("_", "-")
        if normalized in {"utf-8", "utf8", "cp65001"} or normalized in seen:
            continue
        seen.add(normalized)
        unique.append(encoding)
    return tuple(unique)


def _consume_escape_sequence(text: str, index: int) -> int:
    next_index = index + 1
    if next_index >= len(text):
        return len(text)

    introducer = text[next_index]
    if introducer == "[":
        return _consume_csi(text, next_index + 1)
    if introducer == "]":
        return _consume_control_string(text, next_index + 1, allow_bell=True)
    if introducer in _CONTROL_STRING_INTRODUCERS:
        return _consume_control_string(text, next_index + 1, allow_bell=False)

    cursor = next_index
    while cursor < len(text) and 0x20 <= ord(text[cursor]) <= 0x2F:
        cursor += 1
    return min(cursor + 1, len(text))


def _consume_csi(text: str, index: int) -> int:
    while index < len(text):
        codepoint = ord(text[index])
        index += 1
        if 0x40 <= codepoint <= 0x7E:
            return index
    return len(text)


def _consume_control_string(text: str, index: int, *, allow_bell: bool) -> int:
    while index < len(text):
        character = text[index]
        if allow_bell and character == "\x07":
            return index + 1
        if character == "\x9c":
            return index + 1
        if character == "\x1b" and index + 1 < len(text) and text[index + 1] == "\\":
            return index + 2
        index += 1
    return len(text)
