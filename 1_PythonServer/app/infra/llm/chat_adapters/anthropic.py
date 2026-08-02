from collections.abc import AsyncGenerator

from app.domain.llm.chat import (
    ChatCompletionRequest,
    ChatCompletionResult,
    ChatMessage,
    ChatMessageRole,
    ChatStreamEvent,
    ChatStreamEventKind,
    ChatToolCall,
    ChatUsage,
)
from app.domain.llm.provider_catalog import ProviderCatalogEntry
from app.domain.llm.provider_runtime import ProviderRuntimeConfig
from app.infra.llm.anthropic_auth import build_anthropic_request_headers
from app.infra.llm.request_auth import apply_auth_to_url
from app.infra.llm.chat_adapters.base import PostJson, StreamBody
from app.infra.llm.chat_adapters.common import (
    _extract_error_message,
    _iter_sse_payloads,
    _optional_int,
    _optional_str,
    _protocol_error_event,
)
from app.infra.llm.chat_adapters.payloads import (
    _extract_thinking_delta,
    _json_arguments,
    _json_object_arguments,
    _max_output_tokens,
    _message_content_to_anthropic_blocks,
    _message_content_to_anthropic_payload,
    _message_content_to_text,
    _tool_to_anthropic_payload,
)

class AnthropicMessagesChatAdapter:
    async def complete(
        self,
        *,
        provider_template: ProviderCatalogEntry,
        runtime_config: ProviderRuntimeConfig,
        api_key: str,
        request: ChatCompletionRequest,
        post_json: PostJson,
    ) -> ChatCompletionResult:
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
            _build_anthropic_body(request, stream=False),
        )
        text, thinking = _extract_anthropic_content(payload.get("content"))
        return ChatCompletionResult(
            provider_id=request.provider_id,
            model_id=request.model_id,
            message=ChatMessage(
                role=ChatMessageRole.ASSISTANT,
                content=text,
                tool_calls=_extract_anthropic_tool_calls(payload.get("content")),
            ),
            thinking_content=thinking,
            finish_reason=_optional_str(payload.get("stop_reason")),
            usage=_parse_anthropic_usage(payload.get("usage")),
            raw_response=payload,
        )

    async def stream(
        self,
        *,
        provider_template: ProviderCatalogEntry,
        runtime_config: ProviderRuntimeConfig,
        api_key: str,
        request: ChatCompletionRequest,
        stream_body: StreamBody,
    ) -> AsyncGenerator[ChatStreamEvent, None]:
        tool_blocks: dict[int, dict[str, str]] = {}
        async for payload in _iter_sse_payloads(
            stream_body(
                apply_auth_to_url(
                    runtime_config.api_base_url,
                    provider_template.auth_scheme,
                    api_key,
                ),
                build_anthropic_request_headers(
                    provider_template.auth_scheme,
                    api_key,
                    stream=True,
                ),
                _build_anthropic_body(request, stream=True),
            )
        ):
            if payload is None:
                yield _protocol_error_event()
                return
            event_type = str(payload.get("type") or "")
            if event_type == "content_block_start":
                _start_anthropic_tool_block(payload, tool_blocks)
            elif event_type == "content_block_delta":
                delta = payload.get("delta")
                if isinstance(delta, dict):
                    if delta.get("text"):
                        yield ChatStreamEvent(kind=ChatStreamEventKind.DELTA, content=str(delta["text"]))
                    thinking_delta = _extract_thinking_delta(delta)
                    if thinking_delta:
                        yield ChatStreamEvent(kind=ChatStreamEventKind.THINKING_DELTA, content=thinking_delta)
                    _append_anthropic_tool_delta(payload, delta, tool_blocks)
            elif event_type == "content_block_stop":
                tool_call = _finish_anthropic_tool_block(payload, tool_blocks)
                if tool_call is not None:
                    yield ChatStreamEvent(
                        kind=ChatStreamEventKind.TOOL_CALL,
                        tool_call=tool_call,
                    )
            elif event_type == "message_delta":
                usage = _parse_anthropic_usage(payload.get("usage"))
                if usage is not None:
                    yield ChatStreamEvent(kind=ChatStreamEventKind.USAGE, usage=usage)
                delta = payload.get("delta")
                finish_reason = _optional_str(delta.get("stop_reason")) if isinstance(delta, dict) else None
                if finish_reason:
                    yield ChatStreamEvent(kind=ChatStreamEventKind.DONE, finish_reason=finish_reason)
                    return
            elif event_type == "error":
                yield ChatStreamEvent(kind=ChatStreamEventKind.ERROR, error=_extract_error_message(payload))
                return
            elif event_type == "message_stop":
                yield ChatStreamEvent(kind=ChatStreamEventKind.DONE)
                return
        yield ChatStreamEvent(kind=ChatStreamEventKind.DONE)

def _build_anthropic_body(request: ChatCompletionRequest, *, stream: bool) -> dict[str, object]:
    body: dict[str, object] = {
        "model": request.model_id,
        "messages": [_message_to_anthropic_payload(message) for message in request.messages if message.role != ChatMessageRole.SYSTEM],
        "max_tokens": _max_output_tokens(request, default=1024),
        "stream": stream,
    }
    system_prompt = "\n\n".join(
        _message_content_to_text(message)
        for message in request.messages
        if message.role == ChatMessageRole.SYSTEM
    ).strip()
    if system_prompt:
        body["system"] = system_prompt
    temperature = request.generation.temperature if request.generation.temperature is not None else request.temperature
    if temperature is not None:
        body["temperature"] = temperature
    if request.generation.top_p is not None:
        body["top_p"] = request.generation.top_p
    if request.tools:
        body["tools"] = [_tool_to_anthropic_payload(tool) for tool in request.tools]
    return body

def _message_to_anthropic_payload(message: ChatMessage) -> dict[str, object]:
    if message.role == ChatMessageRole.TOOL:
        return {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": message.tool_call_id or "",
                    "content": _message_content_to_text(message),
                }
            ],
        }

    role = "assistant" if message.role == ChatMessageRole.ASSISTANT else "user"
    if message.tool_calls:
        content = _message_content_to_anthropic_blocks(message)
        content.extend(
            {
                "type": "tool_use",
                "id": tool_call.call_id,
                "name": tool_call.name,
                "input": _json_object_arguments(tool_call.arguments),
            }
            for tool_call in message.tool_calls
        )
        return {
            "role": role,
            "content": content,
        }
    return {
        "role": role,
        "content": _message_content_to_anthropic_payload(message),
    }

def _extract_anthropic_content(value: object) -> tuple[str, str]:
    if not isinstance(value, list):
        return "", ""
    text_chunks: list[str] = []
    thinking_chunks: list[str] = []
    for part in value:
        if not isinstance(part, dict):
            continue
        part_type = str(part.get("type") or "")
        text = part.get("text") or part.get("thinking")
        if not isinstance(text, str):
            continue
        if part_type in {"thinking", "redacted_thinking"}:
            thinking_chunks.append(text)
        else:
            text_chunks.append(text)
    return "".join(text_chunks), "".join(thinking_chunks)

def _extract_anthropic_tool_calls(value: object) -> tuple[ChatToolCall, ...]:
    if not isinstance(value, list):
        return ()
    tool_calls: list[ChatToolCall] = []
    for part in value:
        if not isinstance(part, dict) or part.get("type") != "tool_use":
            continue
        name = str(part.get("name") or "").strip()
        if not name:
            continue
        tool_calls.append(
            ChatToolCall(
                call_id=str(part.get("id") or ""),
                name=name,
                arguments=_json_arguments(part.get("input")),
            )
        )
    return tuple(tool_calls)

def _start_anthropic_tool_block(
    payload: dict[str, object],
    tool_blocks: dict[int, dict[str, str]],
) -> None:
    index = payload.get("index")
    content_block = payload.get("content_block")
    if not isinstance(index, int) or not isinstance(content_block, dict):
        return
    if content_block.get("type") != "tool_use":
        return
    tool_blocks[index] = {
        "id": str(content_block.get("id") or ""),
        "name": str(content_block.get("name") or ""),
        "arguments": "",
    }

def _append_anthropic_tool_delta(
    payload: dict[str, object],
    delta: dict[str, object],
    tool_blocks: dict[int, dict[str, str]],
) -> None:
    if delta.get("type") != "input_json_delta":
        return
    index = payload.get("index")
    if not isinstance(index, int) or index not in tool_blocks:
        return
    tool_blocks[index]["arguments"] += str(delta.get("partial_json") or "")

def _finish_anthropic_tool_block(
    payload: dict[str, object],
    tool_blocks: dict[int, dict[str, str]],
) -> ChatToolCall | None:
    index = payload.get("index")
    if not isinstance(index, int):
        return None
    item = tool_blocks.pop(index, None)
    if item is None:
        return None
    name = item.get("name", "").strip()
    if not name:
        return None
    return ChatToolCall(
        call_id=item.get("id", ""),
        name=name,
        arguments=item.get("arguments", "") or "{}",
    )

def _parse_anthropic_usage(value: object) -> ChatUsage | None:
    if not isinstance(value, dict):
        return None
    input_tokens = _optional_int(value.get("input_tokens"))
    output_tokens = _optional_int(value.get("output_tokens"))
    if input_tokens is None and output_tokens is None:
        return None
    total_tokens = (input_tokens or 0) + (output_tokens or 0)
    return ChatUsage(
        prompt_tokens=input_tokens,
        completion_tokens=output_tokens,
        total_tokens=total_tokens,
    )
