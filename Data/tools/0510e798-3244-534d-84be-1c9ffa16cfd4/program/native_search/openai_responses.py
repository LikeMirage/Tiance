from __future__ import annotations

from typing import Any

from .common import ProviderWebSearchResult, ProviderWebSearchSource, SearchError, _optional_str, build_web_search_prompt


def search(source, query, post):
    request_body: dict[str, object] = {
        "model": source.model_id,
        "input": build_web_search_prompt(query),
        "store": False,
        "tools": [{"type": source.responses_tool}],
    }
    if source.include_sources:
        request_body["include"] = ["web_search_call.action.sources"]
    payload = post(request_body)
    status = str(payload.get("status") or "").strip()
    if status == "incomplete":
        raise SearchError(
            _responses_incomplete_message(payload),
            code="upstream_response_incomplete",
        )
    if status == "failed" or payload.get("error"):
        raise SearchError(_responses_error_message(payload))

    output_items = _responses_output_items(payload)
    web_search_items = tuple(
        dict(item)
        for item in output_items
        if item.get("type") == "web_search_call"
    )
    if not web_search_items:
        raise SearchError(
            f"{source.provider_id} / {source.model_id} 的本次响应没有返回搜索调用记录（web_search_call）。",
            code="provider_web_search_not_used",
        )
    if all(item.get("status") == "failed" for item in web_search_items):
        error = web_search_items[-1].get("error")
        reason = (error.get("message") or error.get("code")) if isinstance(error, dict) else error
        raise SearchError(f"上游搜索失败：{reason or '未提供原因'}", code="provider_web_search_failed")

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
        raise SearchError(
            "供应商完成了网络搜索，但没有返回可用答案。",
            code="provider_web_search_empty_answer",
        )
    provider_usage = payload.get("usage")
    return ProviderWebSearchResult(
        provider_id=source.provider_id,
        model_id=source.model_id,
        answer=answer,
        search_queries=tuple(search_queries),
        sources=tuple(sources),
        actions=tuple(actions),
        provider_metadata=web_search_items,
        provider_usage=dict(provider_usage) if isinstance(provider_usage, dict) else {},
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


def _extract_responses_text(payload: dict[str, object]) -> str:
    output = payload.get("output")
    if not isinstance(output, list):
        return str(payload.get("output_text") or "")
    chunks: list[str] = []
    for item in output:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") in {"output_text", "text"} and part.get("text"):
                chunks.append(str(part["text"]))
            elif part.get("type") == "refusal" and part.get("refusal"):
                chunks.append(str(part["refusal"]))
    return "".join(chunks)


def _responses_output_items(payload: dict[str, object]) -> list[dict[str, object]]:
    output = payload.get("output")
    if not isinstance(output, list):
        return []
    return [item for item in output if isinstance(item, dict)]


def _responses_incomplete_message(value: object) -> str:
    response = value if isinstance(value, dict) else {}
    details = response.get("incomplete_details")
    reason = str(details.get("reason") or "").strip() if isinstance(details, dict) else ""
    reason_messages = {
        "max_output_tokens": "达到最大输出 Token 上限",
        "content_filter": "内容过滤器中止了生成",
    }
    detail = reason_messages.get(reason, reason or "上游未返回完整结果")
    return f"上游响应未完整生成：{detail}。"


def _responses_error_message(value: object) -> str:
    payload = value if isinstance(value, dict) else {}
    response = payload.get("response")
    if isinstance(response, dict):
        message = _extract_error_message(response)
        if message != "上游供应商返回错误。":
            return message
    return _extract_error_message(payload)


def _extract_error_message(payload: dict[str, object]) -> str:
    error_payload = payload.get("error")
    if isinstance(error_payload, dict):
        message = error_payload.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()
    message = payload.get("message")
    if isinstance(message, str) and message.strip():
        return message.strip()
    return "上游供应商返回错误。"
