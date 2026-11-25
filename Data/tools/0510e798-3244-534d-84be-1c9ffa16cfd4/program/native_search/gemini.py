from __future__ import annotations

from typing import Any

from .common import ProviderWebSearchResult, ProviderWebSearchSource, SearchError, _optional_str, build_web_search_prompt


def search(source, query, post):
    payload = post(
        {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": build_web_search_prompt(query)}],
                }
            ],
            "tools": [{"googleSearch": {}}],
        }
    )
    text, _thinking = _extract_gemini_content(payload)
    metadata_items = _gemini_grounding_metadata(payload)
    if not metadata_items:
        raise SearchError(
            "当前模型没有执行供应商内置网络搜索。",
            code="provider_web_search_not_used",
        )
    if not text:
        raise SearchError(
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
        provider_id=source.provider_id,
        model_id=source.model_id,
        answer=text,
        search_queries=tuple(search_queries),
        sources=tuple(sources),
        actions=tuple(actions),
        provider_metadata=metadata_items,
        provider_usage=dict(provider_usage) if isinstance(provider_usage, dict) else {},
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


def _extract_gemini_content(payload: dict[str, object]) -> tuple[str, str]:
    candidates = payload.get("candidates")
    first_candidate = candidates[0] if isinstance(candidates, list) and candidates else {}
    if not isinstance(first_candidate, dict):
        return "", ""
    content = first_candidate.get("content")
    if not isinstance(content, dict):
        return "", ""
    parts = content.get("parts")
    if not isinstance(parts, list):
        return "", ""
    text_chunks: list[str] = []
    thinking_chunks: list[str] = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        text = part.get("text")
        if not isinstance(text, str):
            continue
        if part.get("thought") is True:
            thinking_chunks.append(text)
        else:
            text_chunks.append(text)
    return "".join(text_chunks), "".join(thinking_chunks)


def _extract_gemini_finish_reason(payload: dict[str, object]) -> str | None:
    candidates = payload.get("candidates")
    first_candidate = candidates[0] if isinstance(candidates, list) and candidates else {}
    if not isinstance(first_candidate, dict):
        return None
    return _optional_str(first_candidate.get("finishReason"))
