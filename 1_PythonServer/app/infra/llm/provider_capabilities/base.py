from __future__ import annotations

from typing import Protocol

from app.domain.llm.provider_capabilities import ProviderWebSearchResult
from app.domain.llm.provider_catalog import ProviderCatalogEntry
from app.domain.llm.provider_runtime import ProviderRuntimeConfig
from app.infra.llm.chat_adapters.base import PostJson


PROVIDER_WEB_SEARCH_HTTP_TIMEOUT_SECONDS = 120.0
PROVIDER_WEB_SEARCH_OPERATION_TIMEOUT_SECONDS = 150.0


class ProviderWebSearchAdapter(Protocol):
    async def search(
        self,
        *,
        provider_template: ProviderCatalogEntry,
        runtime_config: ProviderRuntimeConfig,
        api_key: str,
        model_id: str,
        query: str,
        post_json: PostJson,
    ) -> ProviderWebSearchResult: ...


def build_web_search_prompt(query: str) -> str:
    return f"Search the web for the following request and answer using the retrieved sources:\n\n{query}"
