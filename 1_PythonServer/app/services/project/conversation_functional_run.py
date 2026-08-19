from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.domain.llm.chat import ChatCompletionRequest


FunctionalConversationRunner = Callable[
    [ChatCompletionRequest],
    Awaitable[None],
]

class FunctionalConversationRunError(RuntimeError):
    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code
