from __future__ import annotations

from json import loads

from app.domain.llm.chat import ChatMessage, ChatMessageContentPart, ChatMessageRole
from app.domain.project.project_conversation import (
    ProjectConversationMessage,
    ProjectConversationSessionSettings,
)
from app.services.tools.tool_result_content import (
    restore_tool_resource_messages,
)
from app.services.project.conversation_request_provenance import tag_conversation_message
from app.services.project.conversation_references import build_referenced_user_message_content


def build_conversation_request_messages(
    messages: tuple[ProjectConversationMessage, ...],
    next_user_content: str | None,
    settings: ProjectConversationSessionSettings,
    *,
    next_user_content_parts: tuple[ChatMessageContentPart, ...] = (),
    next_user_references: list[dict] | None = None,
    next_user_message_id: str | None = None,
    next_user_created_at: str | None = None,
) -> tuple[ChatMessage, ...]:
    skipped_user_ids = (
        set()
        if settings.return_user_before_cancelled
        else _user_messages_before_cancelled_assistant(messages)
    )
    request_messages: list[ChatMessage] = []
    system_prompt = settings.system_prompt.strip()
    if system_prompt:
        request_messages.append(ChatMessage(role=ChatMessageRole.SYSTEM, content=system_prompt))

    for message in messages:
        if message.role == "user" and message.message_id in skipped_user_ids:
            continue
        request_message = _to_request_message(message, settings=settings)
        if request_message is not None:
            request_messages.append(request_message)

    normalized_messages = restore_tool_resource_messages(
        _normalize_tool_message_pairs(tuple(request_messages))
    )
    if next_user_content is None:
        return normalized_messages
    content, content_parts = build_referenced_user_message_content(
        next_user_content,
        next_user_references,
        next_user_content_parts,
    )
    return (
        *normalized_messages,
        tag_conversation_message(
            ChatMessage(
                role=ChatMessageRole.USER,
                content=content,
                content_parts=content_parts,
                created_at=(
                    next_user_created_at
                    if settings.inject_message_timestamps
                    else None
                ),
            ),
            next_user_message_id,
        ),
    )


def _to_request_message(
    message: ProjectConversationMessage,
    *,
    settings: ProjectConversationSessionSettings,
) -> ChatMessage | None:
    if message.role in {"system", "error"} or message.status == "running":
        return None
    if message.status == "cancelled" and not settings.return_cancelled_messages:
        return None

    role = _request_role(message.role)
    if role is None:
        return None

    content_parts: tuple[ChatMessageContentPart, ...] = ()
    if message.role == "tool":
        content = _tool_result_content(message.content)
        content_parts = message.content_parts
    elif message.role == "user":
        content, content_parts = build_referenced_user_message_content(
            message.content.strip(),
            message.references,
            message.content_parts,
        )
    else:
        content = message.content.strip()
    has_tool_calls = bool(message.tool_calls)
    thinking_content = (
        message.thinking_content.strip()
        if (
            settings.return_thinking_content
            and message.role == "assistant"
            and has_tool_calls
        )
        else ""
    )
    if not content.strip() and not content_parts and not has_tool_calls and not thinking_content:
        return None

    return tag_conversation_message(
        ChatMessage(
            role=role,
            content=content,
            content_parts=content_parts,
            name=message.name if role == ChatMessageRole.TOOL else None,
            tool_call_id=message.tool_call_id if role == ChatMessageRole.TOOL else None,
            tool_calls=message.tool_calls if role == ChatMessageRole.ASSISTANT else (),
            protocol_continuation=(
                message.protocol_continuation
                if role == ChatMessageRole.ASSISTANT
                else None
            ),
            thinking_content=thinking_content,
            created_at=(
                message.created_at_local or message.created_at
                if settings.inject_message_timestamps
                and role == ChatMessageRole.USER
                else None
            ),
        ),
        message.message_id,
    )


def _normalize_tool_message_pairs(
    messages: tuple[ChatMessage, ...],
) -> tuple[ChatMessage, ...]:
    normalized: list[ChatMessage] = []
    index = 0

    while index < len(messages):
        message = messages[index]
        if message.role == ChatMessageRole.TOOL:
            index += 1
            continue

        if message.role == ChatMessageRole.ASSISTANT and message.tool_calls:
            tool_call_ids = [tool_call.call_id for tool_call in message.tool_calls if tool_call.call_id]
            expected_call_ids = set(tool_call_ids)
            tool_messages: list[ChatMessage] = []
            cursor = index + 1
            while cursor < len(messages) and messages[cursor].role == ChatMessageRole.TOOL:
                tool_message = messages[cursor]
                if tool_message.tool_call_id and tool_message.tool_call_id in expected_call_ids:
                    tool_messages.append(tool_message)
                    expected_call_ids.remove(tool_message.tool_call_id)
                cursor += 1

            if len(tool_call_ids) == len(message.tool_calls) and not expected_call_ids:
                normalized.append(message)
                normalized.extend(tool_messages)
            index = cursor
            continue

        normalized.append(message)
        index += 1

    return tuple(normalized)


def _user_messages_before_cancelled_assistant(
    messages: tuple[ProjectConversationMessage, ...],
) -> set[str]:
    user_ids: set[str] = set()
    last_user_id: str | None = None
    for message in messages:
        if message.role == "user":
            last_user_id = message.message_id
            continue
        if message.role == "assistant" and message.status == "cancelled" and last_user_id:
            user_ids.add(last_user_id)
            last_user_id = None
            continue
        if message.role == "assistant" and message.status != "cancelled":
            last_user_id = None
    return user_ids


def _request_role(role: str) -> ChatMessageRole | None:
    if role == "user":
        return ChatMessageRole.USER
    if role == "assistant":
        return ChatMessageRole.ASSISTANT
    if role == "tool":
        return ChatMessageRole.TOOL
    return None


def _tool_result_content(content: str) -> str:
    try:
        payload = loads(content)
    except Exception:
        return ""
    if not isinstance(payload, dict):
        return ""
    result = payload.get("result")
    return result if isinstance(result, str) else ""
