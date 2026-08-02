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
from app.infra.llm.chat_adapters.common import _build_headers, _optional_str
from app.infra.llm.chat_adapters.openai_responses_parsing import (
    _extract_responses_text,
    _parse_responses_usage,
    _responses_error_message,
    _responses_incomplete_message,
    _responses_output_items,
)
from app.infra.llm.provider_capabilities.base import build_web_search_prompt
from app.infra.llm.provider_profiles import resolve_provider_profile


class OpenAIResponsesWebSearchAdapter:
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
        request_body: dict[str, object] = {
            "model": model_id,
            "input": build_web_search_prompt(query),
            "store": False,
            "tools": [{"type": "web_search"}],
        }
        provider_profile = resolve_provider_profile(provider_template)
        if provider_profile.include_responses_web_search_sources:
            request_body["include"] = ["web_search_call.action.sources"]
        payload = await post_json(
            runtime_config.api_base_url,
            _build_headers(provider_template.auth_scheme, api_key),
            request_body,
        )
        status = str(payload.get("status") or "").strip()
        if status == "incomplete":
            raise UpstreamProviderError(
                _responses_incomplete_message(payload),
                code="upstream_response_incomplete",
            )
        if status == "failed" or payload.get("error"):
            raise UpstreamProviderError(_responses_error_message(payload))

        output_items = _responses_output_items(payload)
        web_search_items = tuple(
            dict(item)
            for item in output_items
            if item.get("type") == "web_search_call"
        )
        if not web_search_items:
            raise UpstreamProviderError(
                "当前模型没有执行供应商内置网络搜索。",
                code="provider_web_search_not_used",
            )

        search_queries: list[str] = []
        sources: list[ProviderWebSearchSource] = []
        actions: list[dict[str, Any]] = []
        for item in web_search_items:
            action = item.get("action")
            if not isinstance(action, dict):
                continue
            action_copy = dict(action)
            actions.append(action_copy)
            _append_openai_queries(search_queries, action)
            _append_openai_action_sources(sources, action)
        _append_openai_citations(sources, output_items)

        answer = _extract_responses_text(payload)
        if not answer:
            raise UpstreamProviderError(
                "供应商完成了网络搜索，但没有返回可用答案。",
                code="provider_web_search_empty_answer",
            )
        provider_usage = payload.get("usage")
        return ProviderWebSearchResult(
            provider_id=provider_template.provider_id,
            model_id=model_id,
            answer=answer,
            search_queries=tuple(search_queries),
            sources=tuple(sources),
            actions=tuple(actions),
            provider_metadata=web_search_items,
            provider_usage=dict(provider_usage) if isinstance(provider_usage, dict) else {},
            usage=_parse_responses_usage(provider_usage),
            response_id=_optional_str(payload.get("id")),
            status=status or None,
        )


def _append_openai_queries(target: list[str], action: dict[str, Any]) -> None:
    query = action.get("query")
    if isinstance(query, str) and query:
        target.append(query)
    queries = action.get("queries")
    if isinstance(queries, list):
        target.extend(item for item in queries if isinstance(item, str) and item)


def _append_openai_action_sources(
    target: list[ProviderWebSearchSource],
    action: dict[str, Any],
) -> None:
    raw_sources = action.get("sources")
    if not isinstance(raw_sources, list):
        return
    for source in raw_sources:
        if not isinstance(source, dict):
            continue
        url = source.get("url")
        if not isinstance(url, str) or not url:
            continue
        target.append(
            ProviderWebSearchSource(
                url=url,
                title=_optional_str(source.get("title")),
                source_kind="search_result",
                metadata=dict(source),
            )
        )


def _append_openai_citations(
    target: list[ProviderWebSearchSource],
    output_items: list[dict[str, object]],
) -> None:
    for item in output_items:
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict):
                continue
            annotations = part.get("annotations")
            if not isinstance(annotations, list):
                continue
            for annotation in annotations:
                if not isinstance(annotation, dict):
                    continue
                url = annotation.get("url")
                if not isinstance(url, str) or not url:
                    continue
                target.append(
                    ProviderWebSearchSource(
                        url=url,
                        title=_optional_str(annotation.get("title")),
                        source_kind="citation",
                        metadata=dict(annotation),
                    )
                )
