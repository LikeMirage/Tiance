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
from app.infra.llm.chat_adapters.base import PostJson, StreamBody
from app.infra.llm.chat_adapters.common import (
    _iter_sse_payloads,
    _optional_int,
    _optional_str,
    _protocol_error_event,
)
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
        text, thinking = _extract_gemini_content(payload)
        return ChatCompletionResult(
            provider_id=request.provider_id,
            model_id=request.model_id,
            message=ChatMessage(
                role=ChatMessageRole.ASSISTANT,
                content=text,
                tool_calls=_extract_gemini_tool_calls(payload),
            ),
            thinking_content=thinking,
            finish_reason=_extract_gemini_finish_reason(payload),
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
        emitted_tool_call_keys: set[tuple[str, str]] = set()
        async for payload in _iter_sse_payloads(
            stream_body(
                _build_gemini_generate_content_url(
                    provider_template, runtime_config, request, api_key, stream=True
                ),
                _build_gemini_headers(provider_template, api_key, stream=True),
                _build_gemini_body(request),
            )
        ):
            if payload is None:
                yield _protocol_error_event()
                return
            text, thinking = _extract_gemini_content(payload)
            if text:
                yield ChatStreamEvent(kind=ChatStreamEventKind.DELTA, content=text)
            if thinking:
                yield ChatStreamEvent(kind=ChatStreamEventKind.THINKING_DELTA, content=thinking)
            for tool_call in _extract_gemini_tool_calls(payload):
                tool_call_key = (tool_call.name, tool_call.arguments)
                if tool_call_key in emitted_tool_call_keys:
                    continue
                emitted_tool_call_keys.add(tool_call_key)
                yield ChatStreamEvent(
                    kind=ChatStreamEventKind.TOOL_CALL,
                    tool_call=tool_call,
                )
            usage = _parse_gemini_usage(payload.get("usageMetadata"))
            if usage is not None:
                yield ChatStreamEvent(kind=ChatStreamEventKind.USAGE, usage=usage)
            last_finish_reason = _extract_gemini_finish_reason(payload) or last_finish_reason
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
            _message_to_gemini_payload(message)
            for message in request.messages
            if message.role != ChatMessageRole.SYSTEM
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

def _message_to_gemini_payload(message: ChatMessage) -> dict[str, object]:
    if message.role == ChatMessageRole.TOOL:
        return {
            "role": "user",
            "parts": [
                {
                    "functionResponse": {
                        "name": message.name or "",
                        "response": {
                            "result": _message_content_to_text(message),
                        },
                    },
                }
            ],
        }

    role = "model" if message.role == ChatMessageRole.ASSISTANT else "user"
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
    temperature = request.generation.temperature if request.generation.temperature is not None else request.temperature
    if temperature is not None:
        config["temperature"] = temperature
    if request.generation.top_p is not None:
        config["topP"] = request.generation.top_p
    max_output_tokens = request.generation.max_output_tokens if request.generation.max_output_tokens is not None else request.max_tokens
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
        function_call = part.get("functionCall")
        if not isinstance(function_call, dict):
            continue
        name = str(function_call.get("name") or "").strip()
        if not name:
            continue
        tool_calls.append(
            ChatToolCall(
                call_id=f"gemini_tool_call_{index}",
                name=name,
                arguments=_json_arguments(function_call.get("args")),
            )
        )
    return tuple(tool_calls)

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

def _parse_gemini_usage(value: object) -> ChatUsage | None:
    if not isinstance(value, dict):
        return None
    prompt_tokens = _optional_int(value.get("promptTokenCount"))
    completion_tokens = _optional_int(value.get("candidatesTokenCount"))
    total_tokens = _optional_int(value.get("totalTokenCount"))
    reasoning_tokens = _optional_int(value.get("thoughtsTokenCount"))
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
