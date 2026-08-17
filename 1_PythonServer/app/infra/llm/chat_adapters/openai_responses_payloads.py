from hashlib import sha256

from app.domain.llm.chat import (
    ChatCompletionRequest,
    ChatMessage,
    ChatMessageRole,
    ChatProtocolContinuationKind,
)
from app.domain.llm.provider_catalog import ProviderProtocolFamily
from app.infra.llm.chat_adapters.continuation import matching_continuation_items
from app.domain.llm.generation_params import LlmReasoningMode
from app.infra.llm.chat_adapters.openai_responses_parsing import (
    _responses_continuation_item,
)
from app.infra.llm.chat_adapters.payloads import (
    _message_content_to_openai_responses_payload,
    _message_content_to_text,
    _tool_to_openai_responses_payload,
)


def _build_responses_body(
    request: ChatCompletionRequest,
    *,
    stream: bool,
    include_message_phase: bool = False,
) -> dict[str, object]:
    body: dict[str, object] = {
        "model": request.model_id,
        "input": _messages_to_responses_payload(
            request,
            request.messages,
            include_message_phase=include_message_phase,
        ),
        "store": False,
        "stream": stream,
    }
    prompt_cache_key = _responses_prompt_cache_key(request)
    if prompt_cache_key is not None:
        body["prompt_cache_key"] = prompt_cache_key
    generation = request.generation
    max_output_tokens = generation.max_output_tokens
    if max_output_tokens is not None:
        body["max_output_tokens"] = max_output_tokens
    if generation.temperature is not None:
        body["temperature"] = generation.temperature
    if generation.top_p is not None:
        body["top_p"] = generation.top_p
    reasoning_payload = _responses_reasoning_payload(request)
    if reasoning_payload:
        body["reasoning"] = reasoning_payload
    tools = [
        *(_tool_to_openai_responses_payload(tool) for tool in request.tools),
    ]
    if tools:
        body["tools"] = tools
    if request.tools:
        body["include"] = ["reasoning.encrypted_content"]
    return body


def _responses_prompt_cache_key(request: ChatCompletionRequest) -> str | None:
    """Return a stable cache-affinity key for one conversation lineage and model."""
    affinity_id = (request.cache_affinity_id or request.session_id or "").strip()
    model_id = request.model_id.strip()
    if not affinity_id or not model_id:
        return None

    identity = f"{affinity_id}\0{model_id}".encode("utf-8")
    return sha256(identity).hexdigest()


def _messages_to_responses_payload(
    request: ChatCompletionRequest,
    messages: tuple[ChatMessage, ...],
    *,
    include_message_phase: bool = False,
) -> list[dict[str, object]]:
    payload: list[dict[str, object]] = []
    for message in messages:
        payload.extend(
            _message_to_responses_payload(
                message,
                request,
                include_message_phase=include_message_phase,
            )
        )
    return payload


def _message_to_responses_payload(
    message: ChatMessage,
    request: ChatCompletionRequest,
    *,
    include_message_phase: bool = False,
) -> list[dict[str, object]]:
    if message.role == ChatMessageRole.TOOL:
        return [
            {
                "type": "function_call_output",
                "call_id": message.tool_call_id or "",
                "output": _message_content_to_text(message),
            }
        ]

    items = [
        continuation_item
        for item in matching_continuation_items(
            message,
            request,
            ProviderProtocolFamily.OPENAI_RESPONSES,
            ChatProtocolContinuationKind.OPENAI_RESPONSES_OUTPUT,
        )
        if (continuation_item := _responses_continuation_item(item)) is not None
    ]
    content = _message_content_to_openai_responses_payload(message)
    if content or not message.tool_calls:
        message_item: dict[str, object] = {
            "role": message.role.value,
            "content": content,
        }
        if message.role == ChatMessageRole.ASSISTANT and include_message_phase:
            message_item["phase"] = "commentary" if message.tool_calls else "final_answer"
        items.append(message_item)
    for tool_call in message.tool_calls:
        items.append(
            {
                "type": "function_call",
                "call_id": tool_call.call_id,
                "name": tool_call.name,
                "arguments": tool_call.arguments,
            }
        )
    return items


def _responses_reasoning_payload(
    request: ChatCompletionRequest,
) -> dict[str, object]:
    payload: dict[str, object] = {}
    reasoning = request.generation.reasoning
    if reasoning is not None:
        effort = _responses_reasoning_effort(reasoning.mode)
        if effort is not None:
            payload["effort"] = effort
    if reasoning is not None and reasoning.mode != LlmReasoningMode.OFF:
        payload["summary"] = "auto"
    return payload


def _responses_reasoning_effort(mode: LlmReasoningMode) -> str | None:
    if mode in (LlmReasoningMode.DEFAULT, LlmReasoningMode.AUTO):
        return None
    if mode == LlmReasoningMode.ENABLED:
        return "medium"
    if mode == LlmReasoningMode.OFF:
        return "none"
    if mode == LlmReasoningMode.MAX:
        return "xhigh"
    return mode.value
