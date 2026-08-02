from __future__ import annotations

import re
from collections.abc import Iterable


MAX_WARNING_COUNT = 100
MAX_WARNING_LENGTH = 500


class WarningCollector:
    """Bounds and deduplicates non-fatal diagnostics returned to the model."""

    def __init__(self) -> None:
        self._messages: list[str] = []
        self._seen: set[str] = set()
        self._suppressed = 0

    def append(self, message: str) -> None:
        normalized = re.sub(r"\s+", " ", str(message)).strip()
        if not normalized:
            return
        if len(normalized) > MAX_WARNING_LENGTH:
            normalized = normalized[: MAX_WARNING_LENGTH - 1].rstrip() + "…"
        if normalized in self._seen or len(self._messages) >= MAX_WARNING_COUNT:
            self._suppressed += 1
            return
        self._seen.add(normalized)
        self._messages.append(normalized)

    def extend(self, messages: Iterable[str]) -> None:
        for message in messages:
            self.append(message)

    def messages(self) -> list[str]:
        result = list(self._messages)
        if self._suppressed:
            result.append(f"另有 {self._suppressed} 条重复或超出上限的警告未展开。")
        return result
