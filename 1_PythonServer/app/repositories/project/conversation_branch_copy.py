from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from json import dumps, loads
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.domain.project.project_conversation import ProjectConversationMessage
from app.repositories.project.conversation_storage import atomic_write_text

COMPRESSIONS_FILE = "compressions.jsonl"
PROJECT_MEMORY_MANAGEMENT_STATE_FILE = "project_memory_management_state.json"
GLOBAL_MEMORY_MANAGEMENT_STATE_FILE = "global_memory_management_state.json"
MEMORY_MANAGEMENT_STATE_FILES = (
    PROJECT_MEMORY_MANAGEMENT_STATE_FILE,
    GLOBAL_MEMORY_MANAGEMENT_STATE_FILE,
)
MEMORY_DELIVERY_FILE = "memory_delivery.json"
_MEMORY_SCOPES = ("global_memory", "project_memory")


def copy_message_prefix(
    messages: tuple[ProjectConversationMessage, ...],
    *,
    target_session_id: str,
) -> tuple[tuple[ProjectConversationMessage, ...], dict[str, str]]:
    id_map = {
        message.message_id: f"msg_{uuid4().hex[:16]}"
        for message in messages
    }
    copied = tuple(
        replace(
            message,
            message_id=id_map[message.message_id],
            session_id=target_session_id,
            origin_message_id=message.origin_message_id or message.message_id,
            variant_group_id=(
                message.variant_group_id or message.origin_message_id or message.message_id
                if message.role == "user"
                else None
            ),
        )
        for message in messages
    )
    return copied, id_map


def write_inherited_compressions(
    source_session_dir: Path,
    target_session_dir: Path,
    *,
    target_session_id: str,
    message_id_map: dict[str, str],
) -> None:
    records = _read_jsonl(source_session_dir / COMPRESSIONS_FILE)
    active_record = next(
        (
            record
            for record in reversed(records)
            if _is_eligible_completed_record(record, message_id_map)
        ),
        None,
    )
    if active_record is None:
        return
    inherited = _inherited_compression_record(
        active_record,
        target_session_id=target_session_id,
        message_id_map=message_id_map,
    )
    content = (
        f"{dumps(inherited, ensure_ascii=False, separators=(',', ':'))}\n"
    )
    atomic_write_text(target_session_dir / COMPRESSIONS_FILE, content)


def write_inherited_long_term_memory_state(
    source_session_dir: Path,
    target_session_dir: Path,
    *,
    target_session_id: str,
    message_id_map: dict[str, str],
) -> None:
    for state_file in MEMORY_MANAGEMENT_STATE_FILES:
        state = _read_json_object(source_session_dir / state_file)
        if state is None:
            continue
        boundary_message_id = state.get("last_completed_boundary_message_id")
        if (
            not isinstance(boundary_message_id, str)
            or boundary_message_id not in message_id_map
        ):
            continue
        inherited = deepcopy(state)
        inherited["session_id"] = target_session_id
        inherited["last_completed_boundary_message_id"] = message_id_map[
            boundary_message_id
        ]
        inherited["inherited_from"] = {
            "session_id": state.get("session_id"),
            "task_id": state.get("last_completed_task_id"),
        }
        atomic_write_text(
            target_session_dir / state_file,
            f"{dumps(inherited, ensure_ascii=False, indent=2)}\n",
        )


def write_inherited_memory_delivery_state(
    source_session_dir: Path,
    target_session_dir: Path,
    *,
    message_id_map: dict[str, str],
) -> None:
    state = _read_json_object(source_session_dir / MEMORY_DELIVERY_FILE)
    if state is None:
        return
    inherited = _inherited_memory_delivery_state(
        state,
        message_id_map=message_id_map,
    )
    atomic_write_text(
        target_session_dir / MEMORY_DELIVERY_FILE,
        f"{dumps(inherited, ensure_ascii=False, indent=2)}\n",
    )


def _inherited_memory_delivery_state(
    state: dict[str, Any],
    *,
    message_id_map: dict[str, str],
) -> dict[str, Any]:
    baseline = state.get("baseline")
    source_cursors = state.get("cursors")
    deliveries = state.get("deliveries")
    if (
        not isinstance(baseline, dict)
        or not isinstance(source_cursors, dict)
        or not isinstance(deliveries, list)
    ):
        raise ValueError("Conversation memory delivery state is invalid.")

    inherited_cursors = {
        scope: _memory_event_count(baseline, scope)
        for scope in _MEMORY_SCOPES
    }
    inherited_deliveries: list[dict[str, Any]] = []
    for delivery in deliveries:
        if not isinstance(delivery, dict):
            raise ValueError("Conversation memory delivery entry is invalid.")
        source_message_id = delivery.get("user_message_id")
        if not isinstance(source_message_id, str) or not source_message_id:
            raise ValueError("Conversation memory delivery message ID is invalid.")
        target_message_id = message_id_map.get(source_message_id)
        if target_message_id is None:
            continue
        inherited_delivery = deepcopy(delivery)
        inherited_delivery["user_message_id"] = target_message_id
        inherited_deliveries.append(inherited_delivery)
        inherited_cursors = _delivery_cursors(inherited_delivery)

    last_prepared_message_id = state.get("last_prepared_user_message_id")
    mapped_last_prepared_message_id = (
        message_id_map.get(last_prepared_message_id, "")
        if isinstance(last_prepared_message_id, str)
        else ""
    )
    if mapped_last_prepared_message_id:
        inherited_cursors = {
            scope: _non_negative_int(source_cursors.get(scope))
            for scope in _MEMORY_SCOPES
        }
    elif inherited_deliveries:
        mapped_last_prepared_message_id = inherited_deliveries[-1][
            "user_message_id"
        ]

    return {
        **deepcopy(state),
        "last_prepared_user_message_id": mapped_last_prepared_message_id,
        "cursors": inherited_cursors,
        "deliveries": inherited_deliveries,
    }


def _memory_event_count(baseline: dict[str, Any], scope: str) -> int:
    scope_baseline = baseline.get(scope)
    if not isinstance(scope_baseline, dict):
        raise ValueError("Conversation memory delivery baseline is invalid.")
    return _non_negative_int(scope_baseline.get("event_count"))


def _delivery_cursors(delivery: dict[str, Any]) -> dict[str, int]:
    cursor_after = delivery.get("cursor_after")
    if not isinstance(cursor_after, dict):
        raise ValueError("Conversation memory delivery cursor snapshot is invalid.")
    return {
        scope: _non_negative_int(cursor_after.get(scope))
        for scope in _MEMORY_SCOPES
    }


def _non_negative_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("Conversation memory delivery cursor is invalid.")
    return value


def _is_eligible_completed_record(record: dict[str, Any], message_id_map: dict[str, str]) -> bool:
    if (
        record.get("status") != "completed"
        or record.get("source_type") != "conversation_context"
    ):
        return False
    compression_id = record.get("compression_id")
    source_message_ids = record.get("source_message_ids")
    if not isinstance(compression_id, str) or not compression_id:
        return False
    if not isinstance(source_message_ids, list) or not source_message_ids:
        return False
    normalized_ids = [item for item in source_message_ids if isinstance(item, str) and item]
    return len(normalized_ids) == len(source_message_ids) and all(
        message_id in message_id_map
        for message_id in normalized_ids
    )


def _inherited_compression_record(
    source: dict[str, Any],
    *,
    target_session_id: str,
    message_id_map: dict[str, str],
) -> dict[str, Any]:
    record = deepcopy(source)
    source_compression_id = str(source["compression_id"])
    record["compression_id"] = f"cmp_{uuid4().hex[:16]}"
    record["session_id"] = target_session_id
    record["source_message_ids"] = [
        message_id_map[message_id]
        for message_id in source["source_message_ids"]
    ]
    record["newly_covered_message_ids"] = [
        message_id_map[message_id]
        for message_id in source.get("newly_covered_message_ids", [])
        if isinstance(message_id, str) and message_id in message_id_map
    ]
    record["supersedes_compression_id"] = None
    record["inherited_from"] = {
        "session_id": source.get("session_id"),
        "compression_id": source_compression_id,
    }
    return record


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = loads(line)
        except ValueError:
            continue
        if isinstance(payload, dict):
            records.append(payload)
    return records


def _read_json_object(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None
