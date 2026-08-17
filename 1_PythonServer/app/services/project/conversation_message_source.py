from __future__ import annotations

from app.domain.llm.chat import ChatMessage


_SOURCE_CONTEXT_KEY = "source_context"
_FIELDS = ("project_id", "session_id", "session_title", "tool_request_id")


def source_context_from_chat_message(message: ChatMessage | None) -> dict[str, str]:
    if message is None:
        return {}
    return normalize_source_context(message.internal_metadata.get(_SOURCE_CONTEXT_KEY))


def normalize_source_context(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    normalized: dict[str, str] = {}
    for field in _FIELDS:
        raw = value.get(field)
        if not isinstance(raw, str) or not raw.strip():
            return {}
        normalized[field] = raw.strip()
    return normalized


def add_source_context_to_model_content(content: str, source_context: object) -> str:
    source = normalize_source_context(source_context)
    if not source:
        return content
    header = (
        "<conversation_source "
        f'project_id="{_escape(source["project_id"])}" '
        f'session_id="{_escape(source["session_id"])}" '
        f'session_title="{_escape(source["session_title"])}" '
        f'tool_request_id="{_escape(source["tool_request_id"])}" />'
    )
    return f"{header}\n\n{content}" if content else header


def _escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace('"', "&quot;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
