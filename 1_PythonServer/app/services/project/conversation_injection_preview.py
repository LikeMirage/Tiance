from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from app.domain.llm.chat import (
    ChatCompletionRequest,
    ChatMessage,
    ChatMessageContentPart,
    ChatMessageRole,
    ChatToolDefinition,
)
from app.domain.llm.message_timestamp import model_visible_message_content

InjectionPreviewSource = Literal["real_request", "draft_request"]


def build_conversation_injection_preview(
    request: ChatCompletionRequest,
    *,
    preview_source: InjectionPreviewSource = "real_request",
) -> dict[str, Any]:
    """Build the complete request preview for a conversation session."""

    system_messages = tuple(
        message for message in request.messages
        if message.role == ChatMessageRole.SYSTEM
    )
    ends_with_tool_result = bool(request.messages and request.messages[-1].role == ChatMessageRole.TOOL)
    return {
        "schema_version": 3,
        "generated_at": datetime.now(UTC).isoformat(),
        "description": _description(preview_source),
        "request": {
            "project_id": request.project_id,
            "session_id": request.session_id,
            "provider_id": request.provider_id,
            "model_id": request.model_id,
            "preview_source": preview_source,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "return_thinking_content": request.return_thinking_content,
            "inject_message_timestamps": request.inject_message_timestamps,
            "max_tool_calls": request.max_tool_calls,
            "message_count": len(request.messages),
            "system_message_count": len(system_messages),
            "tool_count": len(request.tools),
            "ends_with_tool_result": ends_with_tool_result,
            "generation": _safe_dataclass_payload(request.generation),
            "output": _safe_dataclass_payload(request.output),
            "record_usage": request.record_usage,
            "usage_message_id": request.usage_message_id,
            "usage_feature_key": request.usage_feature_key,
        },
        "request_snapshot": {
            "tools": [
                _tool_definition_payload(tool)
                for tool in request.tools
            ],
            "messages": [
                _message_payload(index, message)
                for index, message in enumerate(request.messages, start=1)
            ],
        },
    }


def _description(preview_source: InjectionPreviewSource) -> str:
    if preview_source == "draft_request":
        return (
            "本文件记录当前输入框内容对应的下一次 AI 请求预览，"
            "用于检查系统提示词、工作区注入、动态工具目录、消息正文、工具结果和正式工具参数。"
        )
    return (
        "本文件记录最近一次真实发送给 AI 前的完整请求快照，"
        "用于检查系统提示词、工作区注入、动态工具目录、消息正文、工具结果和正式工具参数。"
    )


def _message_payload(index: int, message: ChatMessage) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "index": index,
        "role": str(message.role),
        "content": model_visible_message_content(message),
    }
    if message.role == ChatMessageRole.SYSTEM:
        payload["source"] = _system_message_source(message.content)
    if message.name:
        payload["name"] = message.name
    if message.tool_call_id:
        payload["tool_call_id"] = message.tool_call_id
    if message.thinking_content:
        payload["thinking_content"] = message.thinking_content
    if message.tool_calls:
        payload["tool_calls"] = [
            _tool_call_payload(tool_call)
            for tool_call in message.tool_calls
        ]
    if message.content_parts:
        payload["content_parts"] = [
            _content_part_payload(part)
            for part in message.content_parts
        ]
    if message.preview_metadata:
        payload["preview_metadata"] = _json_safe(message.preview_metadata)
    return payload


def _system_message_source(content: str) -> str:
    stripped = content.strip()
    if stripped.startswith("【动态加载工具目录】"):
        return "dynamic_tool_directory"
    if stripped.startswith("【全局长期记忆｜"):
        return "global_long_term_memory"
    if stripped.startswith("【项目长期记忆｜"):
        return "project_long_term_memory"
    if stripped.startswith("当前项目的工作区："):
        return "workspace_info"
    return "system_prompt"


def _tool_definition_payload(tool: ChatToolDefinition) -> dict[str, Any]:
    return {
        "name": tool.name,
        "description": tool.description,
        "parameters": tool.parameters,
    }


def _tool_call_payload(tool_call) -> dict[str, str]:
    return {
        "call_id": tool_call.call_id,
        "name": tool_call.name,
        "arguments": tool_call.arguments,
    }


def _content_part_payload(part: ChatMessageContentPart) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "type": str(part.type),
    }
    if part.text is not None:
        payload["text"] = part.text
    if part.image_url is not None:
        payload["image_url"] = _safe_dataclass_payload(part.image_url)
    if part.image_ref is not None:
        payload["image_ref"] = _safe_dataclass_payload(part.image_ref)
    return payload


def _safe_dataclass_payload(value: Any) -> dict[str, Any]:
    if not is_dataclass(value):
        return {}
    return _json_safe(asdict(value))


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "value"):
        return value.value
    return value
