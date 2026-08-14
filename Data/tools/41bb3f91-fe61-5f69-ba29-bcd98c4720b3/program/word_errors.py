from __future__ import annotations

from typing import Any


class WordOperationError(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    def with_context(self, context: str) -> "WordOperationError":
        return WordOperationError(self.code, f"{context}：{self.message}", self.details)
