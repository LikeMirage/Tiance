from __future__ import annotations

from typing import Any

from app.core.errors import UpstreamProviderError
from app.domain.llm.provider_capabilities import (
    ProviderWebSearchResult,
    ProviderWebSearchSource,
)
from app.domain.llm.provider_catalog import ProviderCatalogEntry
from app.domain.llm.provider_runtime import ProviderRuntimeConfig
from app.infra.llm.chat_adapters.base import PostJson
from app.infra.llm.chat_adapters.gemini import (
    _build_gemini_headers,
    _extract_gemini_content,
    _extract_gemini_finish_reason,
    _parse_gemini_usage,
)
from app.infra.llm.provider_capabilities.base import build_web_search_prompt
from app.infra.llm.request_auth import apply_auth_to_url
from app.infra.llm.url_utils import render_generation_url


class GeminiWebSearchAdapter:
    async def search(
        self,
        *,
        provider_template: ProviderCatalogEntry,
        runtime_config: ProviderRuntimeConfig,
        api_key: str,
        model_id: str,
        query: str,
        post_json: PostJson,
    ) -> ProviderWebSearchResult:
        payload = await post_json(
            apply_auth_to_url(
                render_generation_url(
                    runtime_config.api_base_url,
                    model_id=model_id,
                    action="generateContent",
                ),
                provider_template.auth_scheme,
                api_key,
            ),
            _build_gemini_headers(provider_template, api_key, stream=False),
            {
                "contents": [
                    {
                        "role": "user",
                        "parts": [{"text": build_web_search_prompt(query)}],
                    }
                ],
                "tools": [{"googleSearch": {}}],
            },
        )
        text, _thinking = _extract_gemini_content(payload)
        metadata_items = _gemini_grounding_metadata(payload)
        if not metadata_items:
            raise UpstreamProviderError(
                "当前模型没有执行供应商内置网络搜索。",
                code="provider_web_search_not_used",
            )
        if not text:
            raise UpstreamProviderError(
                "供应商完成了网络搜索，但没有返回可用答案。",
                code="provider_web_search_empty_answer",
            )

        search_queries: list[str] = []
        sources: list[ProviderWebSearchSource] = []
        actions: list[dict[str, Any]] = []
        for metadata in metadata_items:
            raw_queries = metadata.get("webSearchQueries")
            if isinstance(raw_queries, list):
                search_queries.extend(
                    value for value in raw_queries if isinstance(value, str) and value
                )
            raw_chunks = metadata.get("groundingChunks")
            if isinstance(raw_chunks, list):
                _append_gemini_sources(sources, raw_chunks)
            raw_supports = metadata.get("groundingSupports")
            if isinstance(raw_supports, list):
                actions.extend(dict(item) for item in raw_supports if isinstance(item, dict))

        provider_usage = payload.get("usageMetadata")
        return ProviderWebSearchResult(
            provider_id=runtime_config.provider_id,
            model_id=model_id,
            answer=text,
            search_queries=tuple(search_queries),
            sources=tuple(sources),
            actions=tuple(actions),
            provider_metadata=metadata_items,
            provider_usage=dict(provider_usage) if isinstance(provider_usage, dict) else {},
            usage=_parse_gemini_usage(provider_usage),
            status=_extract_gemini_finish_reason(payload),
        )


def _gemini_grounding_metadata(
    payload: dict[str, object],
) -> tuple[dict[str, Any], ...]:
    candidates = payload.get("candidates")
    if not isinstance(candidates, list):
        return ()
    metadata_items: list[dict[str, Any]] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        metadata = candidate.get("groundingMetadata")
        if isinstance(metadata, dict):
            metadata_items.append(dict(metadata))
    return tuple(metadata_items)


def _append_gemini_sources(
    target: list[ProviderWebSearchSource],
    chunks: list[object],
) -> None:
    for chunk_index, chunk in enumerate(chunks):
        if not isinstance(chunk, dict):
            continue
        web = chunk.get("web")
        if not isinstance(web, dict):
            continue
        uri = web.get("uri")
        if not isinstance(uri, str) or not uri:
            continue
        target.append(
            ProviderWebSearchSource(
                url=uri,
                title=web.get("title") if isinstance(web.get("title"), str) else None,
                source_kind="grounding_chunk",
                metadata={"chunk_index": chunk_index, **dict(chunk)},
            )
        )
