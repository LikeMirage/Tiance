from __future__ import annotations


class WordOperationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def with_context(self, context: str) -> "WordOperationError":
        return WordOperationError(self.code, f"{context}：{self.message}")
