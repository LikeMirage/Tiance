from __future__ import annotations

import json

from app.domain.project.project_conversation import ProjectConversationMessage


def leading_completed_conversation_messages(
    messages: tuple[ProjectConversationMessage, ...],
    *,
    depth_turns: int,
) -> tuple[ProjectConversationMessage, ...]:
    selected: list[ProjectConversationMessage] = []
    pending_user_messages = 0
    completed_turns = 0
    for message in messages:
        selected.append(message)
        if message.role == "user":
            pending_user_messages += 1
        elif message.role == "assistant" and pending_user_messages > 0:
            pending_user_messages -= 1
            completed_turns += 1
            if completed_turns >= depth_turns:
                return tuple(selected)
    return ()


def eligible_conversation_messages(
    messages: tuple[ProjectConversationMessage, ...],
) -> tuple[ProjectConversationMessage, ...]:
    return tuple(
        message for message in messages
        if message.status == "done" and message.role in {"user", "assistant"} and message.content.strip()
    )


def completed_turn_count(messages: tuple[ProjectConversationMessage, ...]) -> int:
    pending_user_messages = 0
    completed_turns = 0
    for message in messages:
        if message.role == "user":
            pending_user_messages += 1
        elif message.role == "assistant" and pending_user_messages > 0:
            pending_user_messages -= 1
            completed_turns += 1
    return completed_turns


def has_user_and_assistant(messages: tuple[ProjectConversationMessage, ...]) -> bool:
    roles = {message.role for message in messages}
    return "user" in roles and "assistant" in roles


def build_naming_input(messages: tuple[ProjectConversationMessage, ...]) -> str:
    payload = {
        "messages": [
            {
                "role": message.role,
                "content": message.content,
            }
            for message in messages
        ],
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def naming_usage_message_id(project_id: str, session_id: str) -> str:
    return f"system:naming:{project_id}:{session_id}"


def extract_title(content: str) -> str | None:
    text = content.strip()
    if not text:
        return None
    try:
        payload = json.loads(text)
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    title = payload.get("title")
    return _normalize_title(title) if isinstance(title, str) else None


def _normalize_title(value: str) -> str | None:
    title = " ".join(value.strip().strip("\"'“”‘’`").split())
    if not title:
        return None
    return title
