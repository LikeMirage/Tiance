from __future__ import annotations


class EscapeIndex:
    """One linear scan per parsed text; no global retention of document bodies."""

    def __init__(self, text: str) -> None:
        self._escaped = bytearray(len(text))
        escaped = False
        for index, character in enumerate(text):
            self._escaped[index] = escaped
            escaped = not escaped if character == "\\" else False

    def __call__(self, index: int) -> bool:
        return bool(self._escaped[index])


def is_escaped(text: str, index: int) -> bool:
    backslashes = 0
    index -= 1
    while index >= 0 and text[index] == "\\":
        backslashes += 1
        index -= 1
    return backslashes % 2 == 1
