from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import Protocol

from app.domain.llm.chat import (
    ChatCompletionRequest,
    ChatCompletionResult,
    ChatStreamEvent,
)
from app.domain.llm.provider_catalog import ProviderCatalogEntry
from app.domain.llm.provider_runtime import ProviderRuntimeConfig

PostJson = Callable[[str, dict[str, str], dict[str, object]], Awaitable[dict[str, object]]]
StreamBody = Callable[[str, dict[str, str], dict[str, object]], AsyncGenerator[bytes, None]]


class ChatAdapter(Protocol):
    async def complete(
        self,
        *,
        provider_template: ProviderCatalogEntry,
        runtime_config: ProviderRuntimeConfig,
        api_key: str,
        request: ChatCompletionRequest,
        post_json: PostJson,
    ) -> ChatCompletionResult: ...

    async def stream(
        self,
        *,
        provider_template: ProviderCatalogEntry,
        runtime_config: ProviderRuntimeConfig,
        api_key: str,
        request: ChatCompletionRequest,
        stream_body: StreamBody,
    ) -> AsyncGenerator[ChatStreamEvent, None]: ...
