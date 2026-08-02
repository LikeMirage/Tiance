from collections.abc import AsyncGenerator
from functools import lru_cache

from app.core.errors import BadRequestError
from app.domain.llm.chat import ChatCompletionRequest, ChatCompletionResult, ChatStreamEvent
from app.domain.llm.provider_catalog import ProviderCatalogEntry, ProviderProtocolFamily
from app.domain.llm.provider_runtime import ProviderRuntimeConfig
from app.infra.http_client import get_http_timeout, get_shared_http_client
from app.infra.llm.chat_adapters import (
    AnthropicMessagesChatAdapter,
    ChatAdapter,
    GeminiGenerateContentChatAdapter,
    OpenAICompatibleChatAdapter,
    OpenAIResponsesChatAdapter,
)


class ChatRemoteClient:
    def __init__(self) -> None:
        self._adapters: dict[ProviderProtocolFamily, ChatAdapter] = {
            ProviderProtocolFamily.OPENAI_COMPATIBLE: OpenAICompatibleChatAdapter(),
            ProviderProtocolFamily.OPENAI_RESPONSES: OpenAIResponsesChatAdapter(),
            ProviderProtocolFamily.ANTHROPIC_MESSAGES: AnthropicMessagesChatAdapter(),
            ProviderProtocolFamily.GEMINI_GENERATE_CONTENT: GeminiGenerateContentChatAdapter(),
        }

    async def complete(
        self,
        *,
        provider_template: ProviderCatalogEntry,
        runtime_config: ProviderRuntimeConfig,
        api_key: str,
        request: ChatCompletionRequest,
    ) -> ChatCompletionResult:
        adapter = self._adapters.get(provider_template.protocol_family)
        if adapter is None:
            raise BadRequestError(
                f"Protocol family '{provider_template.protocol_family.value}' does not support chat completions yet."
            )
        return await adapter.complete(
            provider_template=provider_template,
            runtime_config=runtime_config,
            api_key=api_key,
            request=request,
            post_json=self._post_json,
        )

    async def stream(
        self,
        *,
        provider_template: ProviderCatalogEntry,
        runtime_config: ProviderRuntimeConfig,
        api_key: str,
        request: ChatCompletionRequest,
    ) -> AsyncGenerator[ChatStreamEvent, None]:
        adapter = self._adapters.get(provider_template.protocol_family)
        if adapter is None:
            raise BadRequestError(
                f"Protocol family '{provider_template.protocol_family.value}' does not support chat completions yet."
            )
        async for event in adapter.stream(
            provider_template=provider_template,
            runtime_config=runtime_config,
            api_key=api_key,
            request=request,
            stream_body=self._stream_body,
        ):
            yield event

    async def _post_json(
        self,
        url: str,
        headers: dict[str, str],
        body: dict[str, object],
    ) -> dict[str, object]:
        client = get_shared_http_client()
        response = await client.post(url, headers=headers, json=body)
        response.raise_for_status()
        if not response.content:
            return {}
        payload = response.json()
        return payload if isinstance(payload, dict) else {}

    async def _stream_body(
        self,
        url: str,
        headers: dict[str, str],
        body: dict[str, object],
    ) -> AsyncGenerator[bytes, None]:
        client = get_shared_http_client()
        async with client.stream(
            "POST",
            url,
            headers=headers,
            json=body,
            timeout=get_http_timeout(stream=True),
        ) as response:
            if response.is_error:
                await response.aread()
            response.raise_for_status()
            async for chunk in response.aiter_bytes():
                yield chunk


@lru_cache
def get_chat_remote_client() -> ChatRemoteClient:
    return ChatRemoteClient()
