from collections.abc import AsyncGenerator

from app.domain.llm.chat import (
    ChatCompletionRequest,
    ChatCompletionResult,
    ChatMessage,
    ChatMessageRole,
    ChatStreamEvent,
    ChatStreamEventKind,
    ChatToolCall,
)
from app.domain.llm.provider_catalog import ProviderCatalogEntry
from app.domain.llm.provider_runtime import ProviderRuntimeConfig
from app.infra.llm.chat_adapters.base import PostJson, StreamBody
from app.infra.llm.chat_adapters.common import (
    _build_headers,
    _build_stream_headers,
    _iter_sse_payloads,
    _optional_str,
    _protocol_error_event,
)
from app.infra.llm.chat_adapters.payloads import (
    _apply_generation_params,
    _extract_thinking_content,
    _extract_thinking_delta,
    _message_to_openai_payload,
    _parse_role,
    _parse_tool_calls,
    _tool_to_openai_payload,
)
from app.infra.llm.provider_profiles import ProviderProfile, resolve_provider_profile
from app.infra.llm.request_auth import apply_auth_to_url

class OpenAICompatibleChatAdapter:
    async def complete(
        self,
        *,
        provider_template: ProviderCatalogEntry,
        runtime_config: ProviderRuntimeConfig,
        api_key: str,
        request: ChatCompletionRequest,
        post_json: PostJson,
    ) -> ChatCompletionResult:
        provider_profile = resolve_provider_profile(provider_template, request.model_id)
        upstream_response = await post_json(
            _build_chat_completions_url(provider_template, runtime_config, api_key),
            _build_headers(provider_template.auth_scheme, api_key),
            _build_request_body(
                request,
                stream=False,
                provider_profile=provider_profile,
            ),
        )
        return _parse_response(request, upstream_response, provider_profile)

    async def stream(
        self,
        *,
        provider_template: ProviderCatalogEntry,
        runtime_config: ProviderRuntimeConfig,
        api_key: str,
        request: ChatCompletionRequest,
        stream_body: StreamBody,
    ) -> AsyncGenerator[ChatStreamEvent, None]:
        provider_profile = resolve_provider_profile(provider_template, request.model_id)
        url = _build_chat_completions_url(provider_template, runtime_config, api_key)
        headers = _build_stream_headers(provider_template.auth_scheme, api_key)
        body = _build_request_body(
            request,
            stream=True,
            provider_profile=provider_profile,
        )
        finish_reason: str | None = None
        tool_call_parts: dict[int, dict[str, str]] = {}
        did_emit_tool_call_delta = False
        did_emit_tool_calls = False
        async for payload in _iter_sse_payloads(stream_body(url, headers, body)):
            if payload is None:
                yield _protocol_error_event()
                return
            usage = provider_profile.parse_usage(payload.get("usage"))
            if usage is not None:
                yield ChatStreamEvent(
                    kind=ChatStreamEventKind.USAGE,
                    usage=usage,
                )
            choices = payload.get("choices")
            choice = choices[0] if isinstance(choices, list) and choices else {}
            if not isinstance(choice, dict):
                continue
            delta = choice.get("delta")
            if isinstance(delta, dict) and delta.get("content"):
                yield ChatStreamEvent(
                    kind=ChatStreamEventKind.DELTA,
                    content=str(delta["content"]),
                )
            tool_call_delta = delta.get("tool_calls") if isinstance(delta, dict) else None
            if isinstance(delta, dict):
                _merge_tool_call_delta(tool_call_parts, tool_call_delta)
            thinking_delta = _extract_thinking_delta(delta)
            if thinking_delta:
                yield ChatStreamEvent(
                    kind=ChatStreamEventKind.THINKING_DELTA,
                    content=thinking_delta,
                )
            if isinstance(tool_call_delta, list) and tool_call_delta:
                partial_tool_call_deltas = _streamed_tool_call_deltas(
                    tool_call_parts,
                    tool_call_delta,
                )
                if partial_tool_call_deltas:
                    for tool_call in partial_tool_call_deltas:
                        yield ChatStreamEvent(
                            kind=ChatStreamEventKind.TOOL_CALL_DELTA,
                            tool_call=tool_call,
                        )
                elif not did_emit_tool_call_delta:
                    yield ChatStreamEvent(kind=ChatStreamEventKind.TOOL_CALL_DELTA)
                    did_emit_tool_call_delta = True
            if choice.get("finish_reason"):
                finish_reason = str(choice["finish_reason"])
            if finish_reason == "tool_calls" and not did_emit_tool_calls:
                for tool_call in _streamed_tool_calls(tool_call_parts):
                    yield ChatStreamEvent(
                        kind=ChatStreamEventKind.TOOL_CALL,
                        tool_call=tool_call,
                    )
                did_emit_tool_calls = True
        yield ChatStreamEvent(kind=ChatStreamEventKind.DONE, finish_reason=finish_reason)

def _build_chat_completions_url(
    provider_template: ProviderCatalogEntry,
    runtime_config: ProviderRuntimeConfig,
    api_key: str,
) -> str:
    return apply_auth_to_url(
        runtime_config.api_base_url,
        provider_template.auth_scheme,
        api_key,
    )

def _build_request_body(
    request: ChatCompletionRequest,
    *,
    stream: bool,
    provider_profile: ProviderProfile,
) -> dict[str, object]:
    body: dict[str, object] = {
        "model": request.model_id,
        "messages": [
            _message_to_openai_payload(
                message,
                include_reasoning_content=_should_include_reasoning_content(
                    request,
                    provider_profile,
                ),
            )
            for message in request.messages
        ],
        "stream": stream,
    }
    _apply_generation_params(body, request)
    if request.tools:
        body["tools"] = [_tool_to_openai_payload(tool) for tool in request.tools]
    return provider_profile.apply_openai_compatible_body(body, request)


def _should_include_reasoning_content(
    request: ChatCompletionRequest,
    provider_profile: ProviderProfile,
) -> bool:
    if not request.return_thinking_content:
        return False
    if provider_profile.include_reasoning_content_in_messages:
        return True

    return "deepseek" in request.model_id.lower()

def _parse_response(
    request: ChatCompletionRequest,
    payload: dict[str, object],
    provider_profile: ProviderProfile,
) -> ChatCompletionResult:
    choices = payload.get("choices")
    first_choice = choices[0] if isinstance(choices, list) and choices else {}
    if not isinstance(first_choice, dict):
        first_choice = {}

    upstream_message = first_choice.get("message")
    if not isinstance(upstream_message, dict):
        upstream_message = {}

    role = _parse_role(upstream_message.get("role"))
    message = ChatMessage(
        role=role,
        content=str(upstream_message.get("content") or ""),
        tool_calls=_parse_tool_calls(upstream_message.get("tool_calls")),
        thinking_content=_extract_thinking_content(upstream_message),
    )

    return ChatCompletionResult(
        provider_id=request.provider_id,
        model_id=request.model_id,
        message=message,
        thinking_content=_extract_thinking_content(upstream_message),
        finish_reason=_optional_str(first_choice.get("finish_reason")),
        usage=provider_profile.parse_usage(payload.get("usage")),
        raw_response=payload,
    )


def _merge_tool_call_delta(
    tool_call_parts: dict[int, dict[str, str]],
    value: object,
) -> None:
    if not isinstance(value, list):
        return
    for item in value:
        if not isinstance(item, dict):
            continue
        index = item.get("index")
        if not isinstance(index, int):
            index = len(tool_call_parts)
        current = tool_call_parts.setdefault(
            index,
            {
                "id": "",
                "name": "",
                "arguments": "",
            },
        )
        if item.get("id"):
            current["id"] = str(item["id"])
        function = item.get("function")
        if not isinstance(function, dict):
            continue
        if function.get("name"):
            current["name"] += str(function["name"])
        if function.get("arguments"):
            current["arguments"] += str(function["arguments"])


def _streamed_tool_calls(tool_call_parts: dict[int, dict[str, str]]) -> tuple[ChatToolCall, ...]:
    tool_calls: list[ChatToolCall] = []
    for index in sorted(tool_call_parts.keys()):
        item = tool_call_parts[index]
        name = item.get("name", "").strip()
        if not name:
            continue
        tool_calls.append(
            ChatToolCall(
                call_id=item.get("id", "").strip() or f"tool_call_{index}",
                name=name,
                arguments=item.get("arguments", ""),
            )
        )
    return tuple(tool_calls)


def _streamed_tool_call_deltas(
    tool_call_parts: dict[int, dict[str, str]],
    value: object,
) -> tuple[ChatToolCall, ...]:
    if not isinstance(value, list):
        return ()
    tool_calls: list[ChatToolCall] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        index = item.get("index")
        if not isinstance(index, int):
            index = len(tool_call_parts)
        current = tool_call_parts.get(index)
        if current is None:
            continue
        name = current.get("name", "").strip()
        if not name:
            continue
        arguments_delta = ""
        function = item.get("function")
        if isinstance(function, dict) and function.get("arguments"):
            arguments_delta = str(function["arguments"])
        tool_calls.append(
            ChatToolCall(
                call_id=current.get("id", "").strip() or f"tool_call_{index}",
                name=name,
                arguments=arguments_delta,
            )
        )
    return tuple(tool_calls)
