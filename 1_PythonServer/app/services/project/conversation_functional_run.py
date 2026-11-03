from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
import asyncio

from app.domain.llm.chat import ChatCompletionRequest, ChatMessage, ChatMessageRole
from app.domain.llm.generation_params import LlmGenerationParams
from app.domain.project.project_conversation import ProjectConversationSession


FunctionalConversationRunner = Callable[
    [ChatCompletionRequest],
    Awaitable[None],
]


class FunctionalConversationScheduler:
    """Shared execution ownership; policies still choose their own trigger/boundary.

    Callers must reject a mismatching blocking mode before entering serialize().
    Locks cover one source session and one function, never unrelated projects.
    Ordinary conversation runs own persistence, cancellation and stream delivery.
    """

    def __init__(self) -> None:
        self._runner: FunctionalConversationRunner | None = None
        self._locks: dict[tuple[str, str, str], tuple[asyncio.Lock, int]] = {}

    @property
    def ready(self) -> bool:
        return self._runner is not None

    def bind(self, runner: FunctionalConversationRunner) -> None:
        self._runner = runner

    @asynccontextmanager
    async def serialize(self, project_id: str, source_session_id: str, function: str):
        key = (project_id, source_session_id, function)
        lock, users = self._locks.get(key, (asyncio.Lock(), 0))
        self._locks[key] = (lock, users + 1)
        try:
            async with lock:
                yield
        finally:
            _, users = self._locks[key]
            if users == 1:
                del self._locks[key]
            else:
                self._locks[key] = (lock, users - 1)

    async def run(self, request: ChatCompletionRequest) -> None:
        if self._runner is None:
            raise RuntimeError("功能会话执行器尚未初始化。")
        await self._runner(request)


def build_functional_conversation_request(
    *, project_id: str, session: ProjectConversationSession, prompt: str,
    generation: LlmGenerationParams, feature_key: str, task_id: str,
) -> ChatCompletionRequest:
    return ChatCompletionRequest(
        provider_id=session.provider_id,
        model_id=session.model_id,
        project_id=project_id,
        session_id=session.session_id,
        messages=(ChatMessage(role=ChatMessageRole.USER, content=prompt),),
        generation=generation,
        record_usage=True,
        usage_message_id=f"system:{feature_key}:{task_id}",
        usage_feature_key=feature_key,
        max_tool_calls=session.settings.max_tool_calls,
        upstream_retry_count=session.settings.upstream_retry_count,
    )

class FunctionalConversationRunError(RuntimeError):
    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code
