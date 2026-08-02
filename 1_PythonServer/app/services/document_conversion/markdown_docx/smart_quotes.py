from __future__ import annotations

from collections.abc import Sequence


def normalize_double_quotes(
    text: str,
    *,
    eligible: Sequence[bool] | None = None,
) -> str:
    """Convert paired straight quotes in visible prose to typographic quotes."""
    if '"' not in text:
        return text
    if eligible is not None and len(eligible) != len(text):
        raise ValueError("eligible 必须与 text 等长。")

    characters = list(text)
    pending_opening: int | None = None
    for index, character in enumerate(text):
        if character != '"':
            continue
        if eligible is not None and not eligible[index]:
            continue
        if _is_backslash_escaped(text, index):
            continue
        if pending_opening is None:
            if _looks_like_measurement_mark(text, index):
                continue
            pending_opening = index
            continue
        characters[pending_opening] = "“"
        characters[index] = "”"
        pending_opening = None
    return "".join(characters)


def _is_backslash_escaped(text: str, index: int) -> bool:
    backslash_count = 0
    position = index - 1
    while position >= 0 and text[position] == "\\":
        backslash_count += 1
        position -= 1
    return backslash_count % 2 == 1


def _looks_like_measurement_mark(text: str, index: int) -> bool:
    return index > 0 and text[index - 1].isdigit()
