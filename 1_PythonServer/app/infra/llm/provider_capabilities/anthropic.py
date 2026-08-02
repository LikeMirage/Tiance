from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from app.core.errors import UpstreamProviderError
from app.domain.llm.chat import ChatUsage
from app.domain.llm.provider_capabilities import (
    ProviderWebSearchResult,
    ProviderWebSearchSource,
)
from app.domain.llm.provider_catalog import ProviderCatalogEntry
from app.domain.llm.provider_runtime import ProviderRuntimeConfig
from app.infra.llm.anthropic_auth import build_anthropic_request_headers
from app.infra.llm.request_auth import apply_auth_to_url
from app.infra.llm.chat_adapters.anthropic import _parse_anthropic_usage
from app.infra.llm.chat_adapters.base import PostJson
from app.infra.llm.chat_adapters.common import _optional_str
from app.infra.llm.provider_capabilities.base import build_web_search_prompt


ANTHROPIC_WEB_SEARCH_MAX_OUTPUT_TOKENS = 4096


class AnthropicWebSearchAdapter:
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
        messages: list[dict[str, object]] = [
            {
                "role": "user",
                "content": build_web_search_prompt(query),
            }
        ]
        responses: list[dict[str, object]] = []
        while True:
            payload = await post_json(
                apply_auth_to_url(
                    runtime_config.api_base_url,
                    provider_template.auth_scheme,
                    api_key,
                ),
                build_anthropic_request_headers(
                    provider_template.auth_scheme,
                    api_key,
                    stream=False,
                ),
                {
                    "model": model_id,
                    "messages": messages,
                    "max_tokens": ANTHROPIC_WEB_SEARCH_MAX_OUTPUT_TOKENS,
                    "tools": [
                        {
                            "type": "web_search_20250305",
                            "name": "web_search",
                        }
                    ],
                },
            )
            responses.append(payload)
            stop_reason = str(payload.get("stop_reason") or "").strip()
            if stop_reason == "pause_turn":
                content = payload.get("content")
                if not isinstance(content, list):
                    raise UpstreamProviderError(
                        "Anthropic 暂停了网络搜索，但没有返回可继续的内容。",
                        code="provider_web_search_invalid_pause",
                    )
                messages.append({"role": "assistant", "content": content})
                continue
            if stop_reason == "max_tokens":
                raise UpstreamProviderError(
                    "Anthropic 网络搜索答案达到 4096 输出 Token，未返回不完整结果。",
                    code="upstream_response_incomplete",
                )
            break

        return _parse_anthropic_web_search_result(
            provider_id=runtime_config.provider_id,
            model_id=model_id,
            responses=responses,
        )


def _parse_anthropic_web_search_result(
    *,
    provider_id: str,
    model_id: str,
    responses: list[dict[str, object]],
) -> ProviderWebSearchResult:
    text_chunks: list[str] = []
    search_queries: list[str] = []
    sources: list[ProviderWebSearchSource] = []
    actions: list[dict[str, Any]] = []
    metadata: list[dict[str, Any]] = []
    usage_items: list[dict[str, Any]] = []
    usages: list[ChatUsage] = []
    did_search = False

    for response in responses:
        usage_payload = response.get("usage")
        if isinstance(usage_payload, dict):
            usage_items.append(dict(usage_payload))
            parsed_usage = _parse_anthropic_usage(usage_payload)
            if parsed_usage is not None:
                usages.append(parsed_usage)
        content = response.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            block_type = str(block.get("type") or "")
            if block_type == "text":
                text = block.get("text")
                if isinstance(text, str):
                    text_chunks.append(text)
                _append_anthropic_citations(sources, block)
            elif block_type == "server_tool_use" and block.get("name") == "web_search":
                did_search = True
                block_copy = dict(block)
                metadata.append(block_copy)
                action = block.get("input")
                if isinstance(action, dict):
                    action_copy = dict(action)
                    actions.append(action_copy)
                    search_query = action.get("query")
                    if isinstance(search_query, str) and search_query:
                        search_queries.append(search_query)
            elif block_type == "web_search_tool_result":
                did_search = True
                block_copy = dict(block)
                metadata.append(block_copy)
                _append_anthropic_search_results(sources, block)

    if not did_search:
        raise UpstreamProviderError(
            "当前模型没有执行供应商内置网络搜索。",
            code="provider_web_search_not_used",
        )
    answer = "".join(text_chunks)
    if not answer:
        raise UpstreamProviderError(
            "供应商完成了网络搜索，但没有返回可用答案。",
            code="provider_web_search_empty_answer",
        )
    final_response = responses[-1]
    return ProviderWebSearchResult(
        provider_id=provider_id,
        model_id=model_id,
        answer=answer,
        search_queries=tuple(search_queries),
        sources=tuple(sources),
        actions=tuple(actions),
        provider_metadata=tuple(metadata),
        provider_usage={"requests": usage_items},
        usage=_sum_usage(usages),
        response_id=_optional_str(final_response.get("id")),
        status=_optional_str(final_response.get("stop_reason")),
    )


def _append_anthropic_search_results(
    target: list[ProviderWebSearchSource],
    block: dict[str, Any],
) -> None:
    content = block.get("content")
    if isinstance(content, dict):
        error_code = content.get("error_code")
        if isinstance(error_code, str) and error_code:
            raise UpstreamProviderError(
                f"Anthropic 网络搜索失败：{error_code}",
                code="provider_web_search_failed",
                details={"provider_error_code": error_code},
            )
        return
    if not isinstance(content, list):
        return
    for result in content:
        if not isinstance(result, dict):
            continue
        url = result.get("url")
        if not isinstance(url, str) or not url:
            continue
        target.append(
            ProviderWebSearchSource(
                url=url,
                title=_optional_str(result.get("title")),
                source_kind="search_result",
                page_age=_optional_str(result.get("page_age")),
                metadata=dict(result),
            )
        )


def _append_anthropic_citations(
    target: list[ProviderWebSearchSource],
    block: dict[str, Any],
) -> None:
    citations = block.get("citations")
    if not isinstance(citations, list):
        return
    for citation in citations:
        if not isinstance(citation, dict):
            continue
        url = citation.get("url")
        if not isinstance(url, str) or not url:
            continue
        target.append(
            ProviderWebSearchSource(
                url=url,
                title=_optional_str(citation.get("title")),
                source_kind="citation",
                cited_text=_optional_str(citation.get("cited_text")),
                metadata=dict(citation),
            )
        )


def _sum_usage(usages: list[ChatUsage]) -> ChatUsage | None:
    if not usages:
        return None
    return ChatUsage(
        prompt_tokens=_sum_optional(item.prompt_tokens for item in usages),
        completion_tokens=_sum_optional(item.completion_tokens for item in usages),
        total_tokens=_sum_optional(item.total_tokens for item in usages),
        prompt_cache_hit_tokens=_sum_optional(
            item.prompt_cache_hit_tokens for item in usages
        ),
        prompt_cache_miss_tokens=_sum_optional(
            item.prompt_cache_miss_tokens for item in usages
        ),
        reasoning_tokens=_sum_optional(item.reasoning_tokens for item in usages),
    )


def _sum_optional(values: Iterable[int | None]) -> int | None:
    present_values = [value for value in values if value is not None]
    return sum(present_values) if present_values else None
