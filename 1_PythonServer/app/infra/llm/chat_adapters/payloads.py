from app.domain.llm.chat import (
    ChatCompletionRequest,
    ChatImageUrl,
    ChatMessage,
    ChatMessageContentPart,
    ChatMessageContentPartType,
    ChatMessageRole,
    ChatToolCall,
    ChatToolDefinition,
)
from app.domain.llm.message_timestamp import model_visible_message_content
from json import dumps, loads
from re import fullmatch

_DATA_URL_PATTERN = r"data:([^;,]+);base64,(.+)"

def _apply_generation_params(body: dict[str, object], request: ChatCompletionRequest) -> None:
    generation = request.generation

    temperature = generation.temperature if generation.temperature is not None else request.temperature
    max_output_tokens = generation.max_output_tokens if generation.max_output_tokens is not None else request.max_tokens

    if temperature is not None:
        body["temperature"] = temperature
    if generation.top_p is not None:
        body["top_p"] = generation.top_p
    if generation.presence_penalty is not None:
        body["presence_penalty"] = generation.presence_penalty
    if generation.frequency_penalty is not None:
        body["frequency_penalty"] = generation.frequency_penalty
    if max_output_tokens is not None:
        body["max_tokens"] = max_output_tokens

def _message_to_openai_payload(
    message: ChatMessage,
    *,
    include_reasoning_content: bool = False,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "role": message.role.value,
        "content": (
            None
            if _uses_null_openai_tool_call_content(message)
            else _message_content_to_openai_payload(message)
        ),
    }
    if message.name:
        payload["name"] = message.name
    if message.tool_call_id:
        payload["tool_call_id"] = message.tool_call_id
    if message.tool_calls:
        payload["tool_calls"] = [_tool_call_to_openai_payload(tool_call) for tool_call in message.tool_calls]
    if (
        include_reasoning_content
        and message.role == ChatMessageRole.ASSISTANT
        and message.tool_calls
    ):
        payload["reasoning_content"] = message.thinking_content
    return payload

def _uses_null_openai_tool_call_content(message: ChatMessage) -> bool:
    return (
        message.role == ChatMessageRole.ASSISTANT
        and bool(message.tool_calls)
        and not model_visible_message_content(message)
        and not message.content_parts
    )

def _message_content_to_openai_payload(message: ChatMessage) -> object:
    visible_content = model_visible_message_content(message)
    if not message.content_parts:
        return visible_content

    parts: list[dict[str, object]] = []
    if visible_content:
        parts.append({"type": "text", "text": visible_content})
    parts.extend(
        _content_part_to_openai_payload(part)
        for part in message.content_parts
    )
    return parts

def _message_content_to_openai_responses_payload(message: ChatMessage) -> object:
    visible_content = model_visible_message_content(message)
    if not message.content_parts:
        return visible_content

    parts: list[dict[str, object]] = []
    if visible_content:
        parts.append({"type": "input_text", "text": visible_content})
    for part in message.content_parts:
        if part.type == ChatMessageContentPartType.TEXT:
            parts.append({"type": "input_text", "text": part.text or ""})
        elif part.type == ChatMessageContentPartType.IMAGE_URL and part.image_url is not None:
            image_payload: dict[str, object] = {
                "type": "input_image",
                "image_url": part.image_url.url,
            }
            if part.image_url.detail:
                image_payload["detail"] = part.image_url.detail
            parts.append(image_payload)
    return parts

def _message_content_to_anthropic_payload(message: ChatMessage) -> object:
    if not message.content_parts:
        return model_visible_message_content(message)
    return _message_content_to_anthropic_blocks(message)

def _message_content_to_anthropic_blocks(message: ChatMessage) -> list[dict[str, object]]:
    parts: list[dict[str, object]] = []
    visible_content = model_visible_message_content(message)
    if visible_content:
        parts.append({"type": "text", "text": visible_content})
    for part in message.content_parts:
        if part.type == ChatMessageContentPartType.TEXT:
            parts.append({"type": "text", "text": part.text or ""})
        elif part.type == ChatMessageContentPartType.IMAGE_URL and part.image_url is not None:
            parts.append(_image_url_to_anthropic_payload(part.image_url))
    return parts

def _message_content_to_gemini_parts(message: ChatMessage) -> list[dict[str, object]]:
    parts: list[dict[str, object]] = []
    visible_content = model_visible_message_content(message)
    if visible_content:
        parts.append({"text": visible_content})
    for part in message.content_parts:
        if part.type == ChatMessageContentPartType.TEXT:
            parts.append({"text": part.text or ""})
        elif part.type == ChatMessageContentPartType.IMAGE_URL and part.image_url is not None:
            parts.append(_image_url_to_gemini_payload(part.image_url))
    if not parts:
        parts.append({"text": ""})
    return parts

def _message_content_to_text(message: ChatMessage) -> str:
    visible_content = model_visible_message_content(message)
    chunks = [visible_content] if visible_content else []
    for part in message.content_parts:
        if part.type == ChatMessageContentPartType.TEXT and part.text:
            chunks.append(part.text)
    return "\n".join(chunks)

def _content_part_to_openai_payload(part: ChatMessageContentPart) -> dict[str, object]:
    if part.type == ChatMessageContentPartType.TEXT:
        return {
            "type": "text",
            "text": part.text or "",
        }

    if part.type == ChatMessageContentPartType.IMAGE_URL and part.image_url is not None:
        return {
            "type": "image_url",
            "image_url": _image_url_to_openai_payload(part.image_url),
        }

    return {
        "type": part.type.value,
    }

def _image_url_to_openai_payload(image_url: ChatImageUrl) -> dict[str, object]:
    payload: dict[str, object] = {"url": image_url.url}
    if image_url.detail:
        payload["detail"] = image_url.detail
    return payload

def _image_url_to_anthropic_payload(image_url: ChatImageUrl) -> dict[str, object]:
    data_url = _parse_base64_data_url(image_url.url)
    if data_url is not None:
        mime_type, data = data_url
        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": mime_type,
                "data": data,
            },
        }
    return {
        "type": "image",
        "source": {
            "type": "url",
            "url": image_url.url,
        },
    }

def _image_url_to_gemini_payload(image_url: ChatImageUrl) -> dict[str, object]:
    data_url = _parse_base64_data_url(image_url.url)
    if data_url is not None:
        mime_type, data = data_url
        return {
            "inlineData": {
                "mimeType": mime_type,
                "data": data,
            },
        }
    return {
        "fileData": {
            "fileUri": image_url.url,
        },
    }

def _parse_base64_data_url(url: str) -> tuple[str, str] | None:
    match = fullmatch(_DATA_URL_PATTERN, url, flags=0)
    if match is None:
        return None
    return match.group(1), match.group(2)

def _tool_to_openai_payload(tool: ChatToolDefinition) -> dict[str, object]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        },
    }

def _tool_to_openai_responses_payload(tool: ChatToolDefinition) -> dict[str, object]:
    return {
        "type": "function",
        "name": tool.name,
        "description": tool.description,
        "parameters": tool.parameters,
    }

def _tool_to_anthropic_payload(tool: ChatToolDefinition) -> dict[str, object]:
    return {
        "name": tool.name,
        "description": tool.description,
        "input_schema": tool.parameters,
    }

def _tools_to_gemini_payload(tools: tuple[ChatToolDefinition, ...]) -> list[dict[str, object]]:
    if not tools:
        return []
    return [
        {
            "functionDeclarations": [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                }
                for tool in tools
            ],
        }
    ]

def _tool_call_to_openai_payload(tool_call: ChatToolCall) -> dict[str, object]:
    return {
        "id": tool_call.call_id,
        "type": "function",
        "function": {
            "name": tool_call.name,
            "arguments": tool_call.arguments,
        },
    }

def _max_output_tokens(request: ChatCompletionRequest, *, default: int) -> int:
    configured = request.generation.max_output_tokens if request.generation.max_output_tokens is not None else request.max_tokens
    return configured if configured is not None else default

def _parse_role(value: object) -> ChatMessageRole:
    try:
        return ChatMessageRole(str(value))
    except ValueError:
        return ChatMessageRole.ASSISTANT

def _extract_thinking_delta(delta: object) -> str | None:
    if not isinstance(delta, dict):
        return None
    for key in ("reasoning_content", "reasoning", "thinking", "thinking_content"):
        value = delta.get(key)
        if isinstance(value, str) and value:
            return value
    return None

def _extract_thinking_content(message: object) -> str:
    if not isinstance(message, dict):
        return ""
    return _extract_thinking_delta(message) or ""

def _parse_tool_calls(value: object) -> tuple[ChatToolCall, ...]:
    if not isinstance(value, list):
        return ()

    tool_calls: list[ChatToolCall] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        function = item.get("function")
        if not isinstance(function, dict):
            continue
        tool_calls.append(
            ChatToolCall(
                call_id=str(item.get("id") or ""),
                name=str(function.get("name") or ""),
                arguments=str(function.get("arguments") or ""),
            )
        )
    return tuple(tool_calls)

def _json_arguments(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return dumps(value, ensure_ascii=False, separators=(",", ":"))
    return "{}"

def _json_object_arguments(arguments: str) -> dict[str, object]:
    try:
        payload = loads(arguments or "{}")
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}
