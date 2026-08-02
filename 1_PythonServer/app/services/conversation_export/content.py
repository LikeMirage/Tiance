from __future__ import annotations

from dataclasses import dataclass
from json import loads
from typing import Any

from app.domain.project.conversation_export import ConversationExportContentSelection
from app.domain.project.project_conversation import ProjectConversationMessage


@dataclass(frozen=True, slots=True)
class ConversationExportToolResult:
    arguments: str
    error: str
    name: str
    ok: bool | None
    result: str


def message_body(
    message: ProjectConversationMessage,
    selection: ConversationExportContentSelection,
) -> str:
    if message.role == "user" and selection.user_messages:
        return message.content
    if message.role == "assistant" and selection.assistant_content:
        return message.content
    if message.role == "error" and selection.error_messages:
        return message.content
    if message.role == "system" and selection.system_messages:
        return message.content
    return ""


def message_is_visible(
    message: ProjectConversationMessage,
    selection: ConversationExportContentSelection,
    *,
    has_images: bool,
) -> bool:
    return any(
        (
            bool(message_body(message, selection).strip()),
            bool(selection.thinking and message.thinking_content.strip()),
            bool(selection.tool_calls and message.tool_calls),
            bool(selection.tool_results and message.role == "tool"),
            bool(selection.timestamps),
            bool(
                selection.model_info
                and any(
                    (
                        message.provider_id,
                        message.model_id,
                        message.target_provider_id,
                        message.target_model_id,
                    )
                )
            ),
            bool(selection.token_usage and (message.usage or message.context_tokens is not None)),
            bool(selection.message_metadata),
            bool(selection.images and has_images),
        )
    )


def parse_tool_result(message: ProjectConversationMessage) -> ConversationExportToolResult:
    payload: dict[str, Any] = {}
    try:
        value = loads(message.content)
        if isinstance(value, dict):
            payload = value
    except (TypeError, ValueError):
        pass
    return ConversationExportToolResult(
        arguments=_stringify(payload.get("arguments")),
        error=str(payload.get("error") or ""),
        name=str(payload.get("tool") or message.name or "tool"),
        ok=payload.get("ok") if isinstance(payload.get("ok"), bool) else None,
        result=_stringify(payload.get("result")) or message.content,
    )


def message_label(message: ProjectConversationMessage) -> str:
    return {
        "user": "用户",
        "assistant": "助手",
        "tool": "工具结果",
        "system": "系统",
        "error": "错误",
    }.get(message.role, message.role)


def range_label(value: str) -> str:
    return {
        "conversation": "全部消息",
        "message": "仅本条消息",
        "through-message": "截止本条消息",
        "from-message": "本条消息及之后",
    }.get(value, value)


def usage_items(message: ProjectConversationMessage) -> tuple[tuple[str, int], ...]:
    usage = message.usage or {}
    labels = (
        ("输入", "prompt_tokens"),
        ("输出", "completion_tokens"),
        ("总计", "total_tokens"),
        ("缓存命中", "prompt_cache_hit_tokens"),
        ("缓存未命中", "prompt_cache_miss_tokens"),
        ("思考", "reasoning_tokens"),
    )
    items = tuple(
        (label, value)
        for label, key in labels
        if isinstance((value := usage.get(key)), int)
    )
    if message.context_tokens is not None:
        return (*items, ("上下文", message.context_tokens))
    return items


def _stringify(value: object) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    try:
        from json import dumps

        return dumps(value, ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        return str(value)
