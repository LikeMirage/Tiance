from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.domain.llm.chat import (
    ChatImageRef,
    ChatImageUrl,
    ChatMessageContentPart,
    ChatMessageContentPartType,
    ChatToolCall,
)
from app.domain.llm.generation_params import LlmReasoningMode
from app.domain.project.project_conversation import (
    ProjectConversationMessage,
    ProjectConversationNamingCallRecord,
    ProjectConversationSession,
    ProjectConversationSessionState,
)
from app.repositories.project.conversation_serialization_settings import (
    _merge_session_settings,
    _session_settings_from_payload,
    _session_settings_to_payload,
)

_RUNTIME_STATUSES = {"idle", "running", "error"}
_RUNNING_STATUS_STALE_AFTER = timedelta(seconds=150)
_DEFAULT_ASSISTANT_TITLE = "AI 助手"
_REASONING_MODES = {mode.value for mode in LlmReasoningMode}

def _session_from_payload(payload: dict) -> ProjectConversationSession:
    return ProjectConversationSession(
        session_id=str(payload.get("session_id") or ""),
        sequence_number=_payload_int(payload.get("sequence_number")),
        title=str(payload.get("title") or "新对话"),
        provider_id=_optional_str(payload.get("provider_id")),
        model_id=_optional_str(payload.get("model_id")),
        reasoning_mode=_optional_reasoning_mode(payload.get("reasoning_mode")),
        created_at=str(payload.get("created_at") or ""),
        updated_at=str(payload.get("updated_at") or ""),
        message_count=int(payload.get("message_count") or 0),
        manual_title=bool(payload.get("manual_title") or False),
        settings=_session_settings_from_payload(payload.get("settings")),
        role_project_id=_optional_str(payload.get("role_project_id")),
        role_configuration_hash=_optional_str(
            payload.get("role_configuration_hash")
        ),
    )

def _message_from_payload(payload: dict) -> ProjectConversationMessage:
    role = str(payload.get("role") or "assistant")
    target_provider_id = _optional_str(payload.get("target_provider_id"))
    target_model_id = _optional_str(payload.get("target_model_id"))
    provider_id = _optional_str(payload.get("provider_id"))
    model_id = _optional_str(payload.get("model_id"))
    if role == "user":
        provider_id = None
        model_id = None

    message_id = str(payload.get("message_id") or "")
    origin_message_id = _optional_str(payload.get("origin_message_id")) or message_id
    variant_group_id = (
        _optional_str(payload.get("variant_group_id"))
        or (origin_message_id if role == "user" else None)
    )
    return ProjectConversationMessage(
        message_id=message_id,
        session_id=str(payload.get("session_id") or ""),
        role=role,
        content=str(payload.get("content") or ""),
        thinking_content=str(payload.get("thinking_content") or "") if role in {"assistant", "error"} else "",
        usage=payload.get("usage") if role in {"assistant", "error"} and isinstance(payload.get("usage"), dict) else None,
        provider_id=provider_id,
        model_id=model_id,
        status=str(payload.get("status") or "done"),
        created_at=str(payload.get("created_at") or ""),
        updated_at=str(payload.get("updated_at") or ""),
        created_at_local=_optional_str(payload.get("created_at_local")),
        context_tokens=(
            _payload_int(payload.get("context_tokens"))
            if role in {"assistant", "error"} and payload.get("context_tokens") is not None
            else None
        ),
        context_tokens_estimated=(
            bool(payload.get("context_tokens_estimated"))
            if role in {"assistant", "error"}
            else False
        ),
        target_provider_id=target_provider_id,
        target_model_id=target_model_id,
        name=_optional_str(payload.get("name")),
        tool_call_id=_optional_str(payload.get("tool_call_id")),
        tool_calls=_tool_calls_from_payload(payload.get("tool_calls")),
        content_parts=_content_parts_from_payload(payload.get("content_parts")),
        origin_message_id=origin_message_id,
        variant_group_id=variant_group_id,
        variant_index=max(1, _payload_int(payload.get("variant_index")) or 1),
        references=(
            _message_references_from_payload(payload.get("references"))
            if role == "user"
            else _empty_session_references()
        ),
    )

def _session_to_payload(session: ProjectConversationSession) -> dict:
    return {
        "session_id": session.session_id,
        "sequence_number": session.sequence_number,
        "title": session.title,
        "provider_id": session.provider_id,
        "model_id": session.model_id,
        "reasoning_mode": session.reasoning_mode,
        "created_at": session.created_at,
        "updated_at": session.updated_at,
        "message_count": session.message_count,
        "manual_title": session.manual_title,
        "settings": _session_settings_to_payload(session.settings),
        "role_project_id": session.role_project_id,
        "role_configuration_hash": session.role_configuration_hash,
    }

def _session_index_payload(session: ProjectConversationSession) -> dict:
    return {
        "session_id": session.session_id,
        "sequence_number": session.sequence_number,
        "title": session.title,
        "updated_at": session.updated_at,
        "message_count": session.message_count,
    }

def _message_to_payload(message: ProjectConversationMessage) -> dict:
    payload = {
        "message_id": message.message_id,
        "session_id": message.session_id,
        "role": message.role,
        "content": message.content,
        "status": message.status,
        "created_at": message.created_at,
        "updated_at": message.updated_at,
        "origin_message_id": message.origin_message_id or message.message_id,
    }
    if message.created_at_local:
        payload["created_at_local"] = message.created_at_local
    if message.variant_group_id:
        payload["variant_group_id"] = message.variant_group_id
        payload["variant_index"] = max(1, message.variant_index)
    if message.role == "user":
        if message.target_provider_id:
            payload["target_provider_id"] = message.target_provider_id
        if message.target_model_id:
            payload["target_model_id"] = message.target_model_id
        if _has_message_references(message.references):
            payload["references"] = _message_references_from_payload(message.references)
    else:
        if message.provider_id:
            payload["provider_id"] = message.provider_id
        if message.model_id:
            payload["model_id"] = message.model_id
        if message.thinking_content:
            payload["thinking_content"] = message.thinking_content
        if message.usage is not None:
            payload["usage"] = message.usage
        if message.context_tokens is not None:
            payload["context_tokens"] = message.context_tokens
            if message.context_tokens_estimated:
                payload["context_tokens_estimated"] = True
        if message.name:
            payload["name"] = message.name
        if message.tool_call_id:
            payload["tool_call_id"] = message.tool_call_id
        if message.tool_calls:
            payload["tool_calls"] = [
                {
                    "call_id": tool_call.call_id,
                    "name": tool_call.name,
                    "arguments": tool_call.arguments,
                }
                for tool_call in message.tool_calls
            ]
    if message.content_parts:
        payload["content_parts"] = [
            _content_part_to_payload(part)
            for part in message.content_parts
        ]
    return payload

def _naming_call_record_to_payload(record: ProjectConversationNamingCallRecord) -> dict:
    return {
        "naming_call_id": record.naming_call_id,
        "session_id": record.session_id,
        "provider_id": record.provider_id,
        "model_id": record.model_id,
        "request": record.request,
        "response": record.response,
        "status": record.status,
        "error": record.error,
        "created_at": record.created_at,
        "completed_at": record.completed_at,
    }

def _empty_index() -> dict:
    return {
        "active_session_id": None,
        "pinned_session_ids": [],
        "sessions": [],
        "session_states": {},
    }


def _index_pinned_session_ids(index: dict) -> set[str]:
    values = index.get("pinned_session_ids")
    if not isinstance(values, list):
        return set()
    return {
        value.strip()
        for value in values
        if isinstance(value, str) and value.strip()
    }


def _index_session_items(index: dict) -> list:
    sessions = index.get("sessions")
    return sessions if isinstance(sessions, list) else []

def _default_session_state(session_id: str) -> ProjectConversationSessionState:
    return ProjectConversationSessionState(
        session_id=session_id,
        runtime_status="idle",
        draft="",
        references=_empty_session_references(),
        updated_at=_utc_now(),
    )

def _session_state_from_payload(
    session_id: str,
    payload: object,
) -> ProjectConversationSessionState:
    if not isinstance(payload, dict):
        return _default_session_state(session_id)
    runtime_status = str(payload.get("runtime_status") or "idle")
    if runtime_status not in _RUNTIME_STATUSES:
        runtime_status = "idle"
    return ProjectConversationSessionState(
        session_id=session_id,
        runtime_status=runtime_status,
        draft=str(payload.get("draft") or ""),
        references=_session_references_from_payload(payload.get("references")),
        updated_at=str(payload.get("updated_at") or _utc_now()),
    )

def _merge_session_state(
    session_id: str,
    payload: dict,
    existing: ProjectConversationSessionState | None,
) -> ProjectConversationSessionState:
    current = existing or _default_session_state(session_id)
    runtime_status = payload.get("runtime_status", current.runtime_status)
    if runtime_status not in _RUNTIME_STATUSES:
        runtime_status = current.runtime_status
    draft = payload.get("draft", current.draft)
    references = payload.get("references", current.references)
    return ProjectConversationSessionState(
        session_id=session_id,
        runtime_status=str(runtime_status),
        draft=str(draft or ""),
        references=_session_references_from_payload(references),
        updated_at=_utc_now(),
    )

def _session_state_to_payload(state: ProjectConversationSessionState) -> dict:
    return {
        "runtime_status": state.runtime_status,
        "draft": state.draft,
        "references": state.references,
        "updated_at": state.updated_at,
    }

def _empty_session_references() -> list[dict]:
    return []

def _session_references_from_payload(value: object) -> list[dict]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _message_references_from_payload(value: object) -> list[dict]:
    return _session_references_from_payload(value)


def _has_message_references(value: object) -> bool:
    references = _message_references_from_payload(value)
    return bool(references)

def _runtime_status_for_appended_message(role: str) -> str | None:
    if role == "user":
        return "running"
    if role == "assistant":
        return "idle"
    if role == "error":
        return "error"
    return None

def _expire_running_state_if_stale(
    state: ProjectConversationSessionState,
) -> ProjectConversationSessionState:
    if state.runtime_status != "running":
        return state
    updated_at = _parse_utc_datetime(state.updated_at)
    if updated_at is None:
        return replace(state, runtime_status="idle", updated_at=_utc_now())
    if datetime.now(UTC) - updated_at <= _RUNNING_STATUS_STALE_AFTER:
        return state
    return replace(state, runtime_status="idle", updated_at=_utc_now())

def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) else None

def _tool_calls_from_payload(value: object) -> tuple[ChatToolCall, ...]:
    if not isinstance(value, list):
        return ()
    tool_calls: list[ChatToolCall] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        call_id = item.get("call_id")
        arguments = item.get("arguments")
        tool_calls.append(
            ChatToolCall(
                call_id=str(call_id or ""),
                name=name.strip(),
                arguments=str(arguments or ""),
            )
        )
    return tuple(tool_calls)


def _content_parts_from_payload(value: object) -> tuple[ChatMessageContentPart, ...]:
    if not isinstance(value, list):
        return ()
    parts: list[ChatMessageContentPart] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        try:
            part_type = ChatMessageContentPartType(str(item.get("type") or ""))
        except ValueError:
            continue
        if part_type == ChatMessageContentPartType.TEXT:
            text = item.get("text")
            if isinstance(text, str):
                parts.append(ChatMessageContentPart(type=part_type, text=text))
            continue
        if part_type == ChatMessageContentPartType.IMAGE_URL:
            image_url = item.get("image_url")
            if isinstance(image_url, dict):
                url = image_url.get("url")
                if isinstance(url, str) and url:
                    parts.append(
                        ChatMessageContentPart(
                            type=part_type,
                            image_url=ChatImageUrl(
                                url=url,
                                detail=_optional_str(image_url.get("detail")),
                            ),
                        )
                    )
            continue
        if part_type == ChatMessageContentPartType.IMAGE_REF:
            image_ref = item.get("image_ref")
            if isinstance(image_ref, dict):
                path = image_ref.get("path")
                if isinstance(path, str) and path:
                    parts.append(
                        ChatMessageContentPart(
                            type=part_type,
                            image_ref=ChatImageRef(
                                path=path,
                                mime_type=_optional_str(image_ref.get("mime_type")),
                                detail=_optional_str(image_ref.get("detail")),
                                name=_optional_str(image_ref.get("name")),
                                size_bytes=_optional_int_or_none(image_ref.get("size_bytes")),
                                attachment_id=_optional_str(image_ref.get("attachment_id")),
                                source_path=_optional_str(image_ref.get("source_path")),
                                source_kind=_optional_str(image_ref.get("source_kind")),
                            ),
                        )
                    )
    return tuple(parts)


def _content_part_to_payload(part: ChatMessageContentPart) -> dict:
    payload = {"type": part.type.value}
    if part.text is not None:
        payload["text"] = part.text
    if part.image_url is not None:
        payload["image_url"] = {
            "url": part.image_url.url,
            "detail": part.image_url.detail,
        }
    if part.image_ref is not None:
        payload["image_ref"] = {
            "path": part.image_ref.path,
            "mime_type": part.image_ref.mime_type,
            "detail": part.image_ref.detail,
            "name": part.image_ref.name,
            "size_bytes": part.image_ref.size_bytes,
            "attachment_id": part.image_ref.attachment_id,
            "source_path": part.image_ref.source_path,
            "source_kind": part.image_ref.source_kind,
        }
    return payload

def _optional_reasoning_mode(value: object) -> str | None:
    mode = _optional_str(value)
    if mode in _REASONING_MODES:
        return mode
    return None

def _payload_int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return 0


def _optional_int_or_none(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None

def _next_session_sequence_number(index: dict) -> int:
    max_sequence_number = 0
    sessions = index.get("sessions")
    if not isinstance(sessions, list):
        return 1
    for item in sessions:
        if isinstance(item, dict):
            max_sequence_number = max(max_sequence_number, _payload_int(item.get("sequence_number")))
    return max_sequence_number + 1

def _normalize_session_title(value: object) -> str:
    if not isinstance(value, str):
        return "新对话"
    title = " ".join(value.strip().split())
    return title or "新对话"

def _normalize_assistant_title(value: object) -> str:
    if not isinstance(value, str):
        return _DEFAULT_ASSISTANT_TITLE
    title = value.strip()
    return title or _DEFAULT_ASSISTANT_TITLE

def _new_session_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%d%H%M%S") + f"-{uuid4().hex[:8]}"

def _utc_now() -> str:
    return datetime.now(UTC).isoformat()

def _parse_utc_datetime(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
