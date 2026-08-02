from app.domain.llm.chat import ChatToolCall, ChatUsage
from app.infra.llm.chat_adapters.common import (
    _extract_error_message,
    _optional_int,
    _optional_str,
)
from app.infra.llm.chat_adapters.payloads import _json_arguments


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


def _extract_responses_tool_calls(
    payload: dict[str, object],
) -> tuple[ChatToolCall, ...]:
    return tuple(
        tool_call
        for item in _responses_output_items(payload)
        if (tool_call := _responses_stream_tool_call(item)) is not None
    )


def _extract_responses_reasoning_summary(payload: dict[str, object]) -> str:
    chunks: list[str] = []
    for item in _responses_output_items(payload):
        if item.get("type") != "reasoning":
            continue
        summary = item.get("summary")
        if not isinstance(summary, list):
            continue
        for part in summary:
            if (
                isinstance(part, dict)
                and part.get("type") == "summary_text"
                and part.get("text")
            ):
                chunks.append(str(part["text"]))
    return "".join(chunks)


def _extract_provider_output_items(
    payload: dict[str, object],
) -> tuple[dict[str, object], ...]:
    return tuple(
        provider_output_item
        for item in _responses_output_items(payload)
        if (provider_output_item := _provider_output_item(item)) is not None
    )


def _provider_output_item(item: object) -> dict[str, object] | None:
    if not isinstance(item, dict):
        return None
    if item.get("type") != "reasoning":
        return None
    return dict(item)


def _output_item_identity(item: dict[str, object]) -> str:
    return str(item.get("id") or item.get("encrypted_content") or id(item))


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


def _responses_stream_tool_call(item: object) -> ChatToolCall | None:
    if not isinstance(item, dict) or item.get("type") != "function_call":
        return None
    name = str(item.get("name") or "").strip()
    if not name:
        return None
    return ChatToolCall(
        call_id=str(item.get("call_id") or item.get("id") or ""),
        name=name,
        arguments=_json_arguments(item.get("arguments")),
    )


def _parse_responses_usage(value: object) -> ChatUsage | None:
    if not isinstance(value, dict):
        return None
    input_tokens = _optional_int(value.get("input_tokens"))
    output_tokens = _optional_int(value.get("output_tokens"))
    total_tokens = _optional_int(value.get("total_tokens"))
    input_token_details = value.get("input_tokens_details")
    if not isinstance(input_token_details, dict):
        input_token_details = {}
    output_token_details = value.get("output_tokens_details")
    if not isinstance(output_token_details, dict):
        output_token_details = {}
    prompt_cache_hit_tokens = _optional_int(input_token_details.get("cached_tokens"))
    prompt_cache_miss_tokens = (
        max(input_tokens - prompt_cache_hit_tokens, 0)
        if input_tokens is not None and prompt_cache_hit_tokens is not None
        else None
    )
    reasoning_tokens = _optional_int(output_token_details.get("reasoning_tokens"))
    if (
        input_tokens is None
        and output_tokens is None
        and total_tokens is None
        and prompt_cache_hit_tokens is None
        and reasoning_tokens is None
    ):
        return None
    return ChatUsage(
        prompt_tokens=input_tokens,
        completion_tokens=output_tokens,
        total_tokens=total_tokens,
        prompt_cache_hit_tokens=prompt_cache_hit_tokens,
        prompt_cache_miss_tokens=prompt_cache_miss_tokens,
        reasoning_tokens=reasoning_tokens,
    )


def _responses_output_items(payload: dict[str, object]) -> list[dict[str, object]]:
    output = payload.get("output")
    if not isinstance(output, list):
        return []
    return [item for item in output if isinstance(item, dict)]
