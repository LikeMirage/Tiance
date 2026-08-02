from __future__ import annotations

from functools import lru_cache

from app.core.errors import BadRequestError, UpstreamProviderError
from app.domain.llm.provider_capabilities import ProviderWebSearchResult
from app.domain.llm.provider_catalog import ProviderCatalogEntry, ProviderProtocolFamily
from app.domain.llm.provider_runtime import ProviderRuntimeConfig
from app.infra.http_client import get_shared_http_client
from app.infra.llm.provider_capabilities.anthropic import AnthropicWebSearchAdapter
from app.infra.llm.provider_capabilities.base import ProviderWebSearchAdapter
from app.infra.llm.provider_capabilities.gemini import GeminiWebSearchAdapter
from app.infra.llm.provider_capabilities.openai_responses import (
    OpenAIResponsesWebSearchAdapter,
)


class ProviderCapabilityRemoteClient:
    def __init__(self) -> None:
        self._web_search_adapters: dict[
            ProviderProtocolFamily,
            ProviderWebSearchAdapter,
        ] = {
            ProviderProtocolFamily.OPENAI_RESPONSES: OpenAIResponsesWebSearchAdapter(),
            ProviderProtocolFamily.ANTHROPIC_MESSAGES: AnthropicWebSearchAdapter(),
            ProviderProtocolFamily.GEMINI_GENERATE_CONTENT: GeminiWebSearchAdapter(),
        }

    async def web_search(
        self,
        *,
        provider_template: ProviderCatalogEntry,
        runtime_config: ProviderRuntimeConfig,
        api_key: str,
        model_id: str,
        query: str,
    ) -> ProviderWebSearchResult:
        adapter = self._web_search_adapters.get(provider_template.protocol_family)
        if adapter is None:
            raise BadRequestError(
                f"协议 '{provider_template.protocol_family.value}' 尚未适配内置网络搜索。"
            )
        return await adapter.search(
            provider_template=provider_template,
            runtime_config=runtime_config,
            api_key=api_key,
            model_id=model_id,
            query=query,
            post_json=self._post_json,
        )

    async def _post_json(
        self,
        url: str,
        headers: dict[str, str],
        body: dict[str, object],
    ) -> dict[str, object]:
        response = await get_shared_http_client().post(
            url,
            headers=headers,
            json=body,
        )
        response.raise_for_status()
        if not response.content:
            return {}
        try:
            payload = response.json()
        except ValueError as exc:
            raise UpstreamProviderError(
                "供应商内置能力接口返回了无效 JSON。",
                code="upstream_response_invalid_json",
            ) from exc
        if not isinstance(payload, dict):
            raise UpstreamProviderError(
                "供应商内置能力接口返回的 JSON 顶层必须是对象。",
                code="upstream_response_invalid_shape",
            )
        return payload


@lru_cache
def get_provider_capability_remote_client() -> ProviderCapabilityRemoteClient:
    return ProviderCapabilityRemoteClient()
