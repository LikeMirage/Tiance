from contextlib import aclosing
from app.domain.llm.output_limit_error import OutputLimitError
from collections.abc import AsyncGenerator
from uuid import uuid4

from app.core.errors import UpstreamProviderError
from app.domain.llm.chat import (
    ChatCompletionRequest,
    ChatCompletionResult,
    ChatMessage,
    ChatMessageRole,
    ChatProtocolContinuationKind,
    ChatStreamEvent,
    ChatStreamEventKind,
    ChatToolCall,
    ChatUsage,
)
from app.domain.llm.provider_catalog import ProviderCatalogEntry, ProviderProtocolFamily
from app.domain.llm.provider_runtime import ProviderRuntimeConfig
from app.infra.llm.chat_adapters.base import PostJson, StreamBody
from app.infra.llm.chat_adapters.common import (
    SSE_DONE,
    _iter_sse_payloads,
    _optional_int,
    _optional_str,
    _protocol_error_event,
)
from app.infra.llm.chat_adapters.continuation import (
    build_protocol_continuation,
    matching_continuation_items,
)
from app.infra.llm.chat_adapters.reasoning_replay import should_replay_reasoning
from app.infra.llm.chat_adapters.payloads import (
    _json_arguments,
    _json_object_arguments,
    _message_content_to_gemini_parts,
    _message_content_to_text,
    _tools_to_gemini_payload,
)
from app.infra.llm.url_utils import render_generation_url
from app.infra.llm.request_auth import apply_auth_to_url, build_auth_headers

class GeminiGenerateContentChatAdapter:
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
            _build_gemini_generate_content_url(
                provider_template, runtime_config, request, api_key, stream=False
            ),
            _build_gemini_headers(provider_template, api_key, stream=False),
            _build_gemini_body(request),
        )
        parts = _extract_gemini_parts(payload)
        finish_reason = _extract_gemini_finish_reason(payload)
        if finish_reason == "MAX_TOKENS":
            text, thinking = _extract_gemini_content(payload)
            raise OutputLimitError(ChatCompletionResult(
                provider_id=request.provider_id, model_id=request.model_id,
                message=ChatMessage(role=ChatMessageRole.ASSISTANT, content=text, thinking_content=thinking),
                thinking_content=thinking, finish_reason=finish_reason,
                usage=_parse_gemini_usage(payload.get("usageMetadata")), raw_response=payload,
            ))
        if not parts or finish_reason is None:
            raise UpstreamProviderError(
                "上游 Gemini 返回缺少完整候选结果结构。",
                code="upstream_response_malformed",
            )
        _raise_for_gemini_finish_reason(finish_reason)
        text, thinking = _extract_gemini_content(payload)
        try:
            tool_calls = _extract_gemini_tool_calls(payload)
        except ValueError as exc:
            raise UpstreamProviderError(
                "上游 Gemini 返回了无效的工具参数。",
                code="upstream_response_malformed",
            ) from exc
        continuation = build_protocol_continuation(
            request,
            provider_template.protocol_family,
            ChatProtocolContinuationKind.GEMINI_PARTS,
            tuple(dict(item) for item in parts if isinstance(item, dict)),
        )
        return ChatCompletionResult(
            provider_id=request.provider_id,
            model_id=request.model_id,
            message=ChatMessage(
                role=ChatMessageRole.ASSISTANT,
                content=text,
                tool_calls=tool_calls,
                thinking_content=thinking,
                protocol_continuation=continuation,
            ),
            thinking_content=thinking,
            finish_reason=finish_reason,
            usage=_parse_gemini_usage(payload.get("usageMetadata")),
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
        last_finish_reason: str | None = None
        malformed_tool_arguments = False
        emitted_tool_calls: dict[str, ChatToolCall] = {}
        tool_part_indices: dict[str, int] = {}
        fallback_call_prefix = f"gemini_tool_call_{uuid4().hex}"
        part_sequence = 0
        continuation_parts: list[dict[str, object]] = []
        async with aclosing(_iter_sse_payloads(
            stream_body(
                _build_gemini_generate_content_url(
                    provider_template, runtime_config, request, api_key, stream=True
                ),
                _build_gemini_headers(provider_template, api_key, stream=True),
                _build_gemini_body(request),
            )
        )) as owned_stream:
            async for payload in owned_stream:
                if payload is SSE_DONE:
                    break
                if payload is None:
                    yield _protocol_error_event()
                    return
                text, thinking = _extract_gemini_content(payload)
                if text:
                    yield ChatStreamEvent(kind=ChatStreamEventKind.DELTA, content=text)
                if thinking:
                    yield ChatStreamEvent(kind=ChatStreamEventKind.THINKING_DELTA, content=thinking)
                for part in _extract_gemini_parts(payload):
                    if not isinstance(part, dict):
                        continue
                    part_sequence += 1
                    try:
                        tool_call = _extract_gemini_tool_call(
                            part, fallback_id=f"{fallback_call_prefix}_{part_sequence}"
                        )
                    except ValueError:
                        malformed_tool_arguments = True
                        continue
                    if tool_call is not None:
                        previous = emitted_tool_calls.get(tool_call.call_id)
                        if previous is not None:
                            if previous != tool_call:
                                # Reusing an ID for a different call is ambiguous; never execute it.
                                malformed_tool_arguments = True
                            else:
                                # Preserve metadata delivered with a repeated complete call.
                                continuation_parts[tool_part_indices[tool_call.call_id]].update(part)
                            continue
                        emitted_tool_calls[tool_call.call_id] = tool_call
                        tool_part_indices[tool_call.call_id] = len(continuation_parts)
                        yield ChatStreamEvent(kind=ChatStreamEventKind.TOOL_CALL, tool_call=tool_call)
                    continuation_parts.append(dict(part))
                usage = _parse_gemini_usage(payload.get("usageMetadata"))
                if usage is not None:
                    yield ChatStreamEvent(kind=ChatStreamEventKind.USAGE, usage=usage)
                last_finish_reason = _extract_gemini_finish_reason(payload) or last_finish_reason
        if last_finish_reason is None:
            yield ChatStreamEvent(
                kind=ChatStreamEventKind.ERROR,
                error="上游 Gemini 流在完成标记前意外结束，当前回答可能不完整。",
                error_code="upstream_stream_incomplete",
            )
            return
        finish_error = _gemini_finish_error(last_finish_reason)
        if finish_error is not None:
            message, code = finish_error
            yield ChatStreamEvent(
                kind=ChatStreamEventKind.ERROR,
                error=message,
                error_code=code,
                finish_reason=last_finish_reason,
            )
            return
        if malformed_tool_arguments:
            yield _protocol_error_event("上游 Gemini 返回了无效的工具参数。")
            return
        continuation = build_protocol_continuation(
            request,
            provider_template.protocol_family,
            ChatProtocolContinuationKind.GEMINI_PARTS,
            tuple(continuation_parts),
        )
        if continuation is not None:
            yield ChatStreamEvent(
                kind=ChatStreamEventKind.PROTOCOL_CONTINUATION,
                protocol_continuation=continuation,
            )
        yield ChatStreamEvent(kind=ChatStreamEventKind.DONE, finish_reason=last_finish_reason)

def _build_gemini_generate_content_url(
    provider_template: ProviderCatalogEntry,
    runtime_config: ProviderRuntimeConfig,
    request: ChatCompletionRequest,
    api_key: str,
    *,
    stream: bool,
) -> str:
    action = "streamGenerateContent?alt=sse" if stream else "generateContent"
    return apply_auth_to_url(render_generation_url(
        runtime_config.api_base_url,
        model_id=request.model_id,
        action=action,
    ), provider_template.auth_scheme, api_key)

def _build_gemini_headers(
    provider_template: ProviderCatalogEntry,
    api_key: str,
    *,
    stream: bool,
) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if stream:
        headers["Accept"] = "text/event-stream"
    headers.update(build_auth_headers(provider_template.auth_scheme, api_key))
    return headers

def _build_gemini_body(request: ChatCompletionRequest) -> dict[str, object]:
    body: dict[str, object] = {
        "contents": [
            payload
            for message in request.messages
            if message.role != ChatMessageRole.SYSTEM
            if (payload := _message_to_gemini_payload(message, request)) is not None
        ],
        "generationConfig": _gemini_generation_config(request),
    }
    system_prompt = "\n\n".join(
        _message_content_to_text(message)
        for message in request.messages
        if message.role == ChatMessageRole.SYSTEM
    ).strip()
    if system_prompt:
        body["systemInstruction"] = {"parts": [{"text": system_prompt}]}
    tools = _tools_to_gemini_payload(request.tools)
    if tools:
        body["tools"] = tools
    return body

def _message_to_gemini_payload(
    message: ChatMessage,
    request: ChatCompletionRequest,
) -> dict[str, object] | None:
    if message.role == ChatMessageRole.TOOL:
        return {
            "role": "user",
            "parts": [
                {
                    "functionResponse": {
                        **({"id": message.tool_call_id} if message.tool_call_id else {}),
                        "name": message.name or "",
                        "response": {
                            "result": _message_content_to_text(message),
                        },
                    },
                }
            ],
        }

    role = "model" if message.role == ChatMessageRole.ASSISTANT else "user"
    if message.role == ChatMessageRole.ASSISTANT:
        items = matching_continuation_items(
            message,
            request,
            ProviderProtocolFamily.GEMINI_GENERATE_CONTENT,
            ChatProtocolContinuationKind.GEMINI_PARTS,
        )
        if items:
            if not should_replay_reasoning(message, request.reasoning_replay_mode):
                # Signatures carry opaque thought state even on text/functionCall parts.
                items = tuple(
                    filtered
                    for item in items
                    if item.get("thought") is not True
                    if (filtered := {key: value for key, value in item.items() if key != "thoughtSignature"})
                )
            if not items:
                return None
            return {"role": role, "parts": list(items)}
    if message.tool_calls:
        parts = (
            _message_content_to_gemini_parts(message)
            if message.content or message.content_parts or message.created_at
            else []
        )
        parts.extend(
            {
                "functionCall": {
                    "name": tool_call.name,
                    "args": _json_object_arguments(tool_call.arguments),
                },
            }
            for tool_call in message.tool_calls
        )
        return {
            "role": role,
            "parts": parts,
        }
    return {
        "role": role,
        "parts": _message_content_to_gemini_parts(message),
    }

def _gemini_generation_config(request: ChatCompletionRequest) -> dict[str, object]:
    config: dict[str, object] = {}
    temperature = request.generation.temperature
    if temperature is not None:
        config["temperature"] = temperature
    if request.generation.top_p is not None:
        config["topP"] = request.generation.top_p
    if request.generation.presence_penalty is not None:
        config["presencePenalty"] = request.generation.presence_penalty
    if request.generation.frequency_penalty is not None:
        config["frequencyPenalty"] = request.generation.frequency_penalty
    max_output_tokens = request.generation.max_output_tokens
    if max_output_tokens is not None:
        config["maxOutputTokens"] = max_output_tokens
    return config

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

def _extract_gemini_tool_calls(payload: dict[str, object]) -> tuple[ChatToolCall, ...]:
    parts = _extract_gemini_parts(payload)
    tool_calls: list[ChatToolCall] = []
    for index, part in enumerate(parts):
        if not isinstance(part, dict):
            continue
        tool_call = _extract_gemini_tool_call(part, fallback_id=f"gemini_tool_call_{index}")
        if tool_call is not None:
            tool_calls.append(tool_call)
    return tuple(tool_calls)


def _extract_gemini_tool_call(part: dict, *, fallback_id: str) -> ChatToolCall | None:
    function_call = part.get("functionCall")
    if not isinstance(function_call, dict):
        return None
    name = str(function_call.get("name") or "").strip()
    if not name:
        return None
    arguments = function_call.get("args")
    if arguments is not None and not isinstance(arguments, (dict, str)):
        raise ValueError("invalid Gemini functionCall args")
    return ChatToolCall(
        call_id=str(function_call.get("id") or fallback_id),
        name=name,
        arguments=_json_arguments(arguments),
    )

def _extract_gemini_parts(payload: dict[str, object]) -> list[object]:
    candidates = payload.get("candidates")
    first_candidate = candidates[0] if isinstance(candidates, list) and candidates else {}
    if not isinstance(first_candidate, dict):
        return []
    content = first_candidate.get("content")
    if not isinstance(content, dict):
        return []
    parts = content.get("parts")
    return parts if isinstance(parts, list) else []

def _extract_gemini_finish_reason(payload: dict[str, object]) -> str | None:
    candidates = payload.get("candidates")
    first_candidate = candidates[0] if isinstance(candidates, list) and candidates else {}
    if not isinstance(first_candidate, dict):
        return None
    return _optional_str(first_candidate.get("finishReason"))


def _raise_for_gemini_finish_reason(finish_reason: str) -> None:
    finish_error = _gemini_finish_error(finish_reason)
    if finish_error is None:
        return
    message, code = finish_error
    raise UpstreamProviderError(message, code=code)


def _gemini_finish_error(finish_reason: str) -> tuple[str, str] | None:
    if finish_reason == "STOP":
        return None
    if finish_reason == "MAX_TOKENS":
        return (
            "上游 Gemini 达到最大输出 Token，回复不完整。",
            "upstream_response_incomplete",
        )
    return (
        f"上游 Gemini 未正常完成生成：{finish_reason}。",
        "upstream_response_failed",
    )

def _parse_gemini_usage(value: object) -> ChatUsage | None:
    if not isinstance(value, dict):
        return None
    prompt_tokens = _optional_int(value.get("promptTokenCount"))
    completion_tokens = _optional_int(value.get("candidatesTokenCount"))
    total_tokens = _optional_int(value.get("totalTokenCount"))
    reasoning_tokens = _optional_int(value.get("thoughtsTokenCount"))
    if completion_tokens is not None or reasoning_tokens is not None:
        completion_tokens = (completion_tokens or 0) + (reasoning_tokens or 0)
    if (
        prompt_tokens is None
        and completion_tokens is None
        and total_tokens is None
        and reasoning_tokens is None
    ):
        return None
    return ChatUsage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        reasoning_tokens=reasoning_tokens,
    )
