from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.domain.llm.chat import ChatCompletionRequest


FunctionalConversationRunner = Callable[
    [ChatCompletionRequest],
    Awaitable[None],
]

TRANSIENT_FUNCTION_ERROR_CODES = {
    "upstream_overloaded",
    "upstream_provider_error",
    "upstream_rate_limited",
    "upstream_response_incomplete",
    "upstream_server_error",
    "conversation_run_failed",
}


class FunctionalConversationRunError(RuntimeError):
    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code
