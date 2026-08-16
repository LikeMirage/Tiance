from __future__ import annotations

from pathlib import Path
from shutil import rmtree
from threading import Lock
from time import time_ns
from typing import Any
from uuid import uuid4

from app.core.errors import ConflictError
from app.repositories.project.conversation_file_io import (
    append_jsonl_recoverable,
    read_json_object,
    read_jsonl,
    replace_jsonl,
    require_safe_storage_name,
    write_json_object,
)
from app.repositories.project import conversation_message_index


STORAGE_FORMAT_FILE = "storage.json"
STORAGE_FORMAT_VERSION = 2
LEGACY_DATABASE_FILE = "tiance.db"
CONVERSATIONS_DIRECTORY = "conversations"
SESSIONS_DIRECTORY = "sessions"
SESSION_FILE = "session.json"
SESSION_STATE_FILE = "state.json"
SESSION_BRANCH_FILE = "branch.json"
MESSAGES_FILE = "messages.jsonl"
CONVERSATION_CONTROL_FILE = "control.json"
WORKSPACE_STATE_FILE = "state.json"
PROJECT_EVENTS_DIRECTORY = "memory"

_initialization_lock = Lock()
_initialized_workspaces: set[Path] = set()


def ensure_file_storage(workspace_dir: Path) -> Path:
    workspace = workspace_dir.resolve()
    with _initialization_lock:
        if workspace in _initialized_workspaces and _valid_storage_marker(workspace):
            return workspace
        workspace.mkdir(parents=True, exist_ok=True)
        marker = read_json_object(workspace / STORAGE_FORMAT_FILE)
        if marker is None:
            legacy_database = workspace / LEGACY_DATABASE_FILE
            if legacy_database.is_file():
                from app.repositories.project.conversation_sqlite_migration import (
                    migrate_sqlite_workspace,
                )

                migrate_sqlite_workspace(workspace, legacy_database)
            else:
                _write_storage_marker(workspace, migrated_from=None, legacy_backup=None)
        elif marker.get("version") != STORAGE_FORMAT_VERSION:
            raise ConflictError(
                f"不支持的会话文件结构版本：{marker.get('version')}"
            )
        (workspace / CONVERSATIONS_DIRECTORY / SESSIONS_DIRECTORY).mkdir(
            parents=True,
            exist_ok=True,
        )
        _initialized_workspaces.add(workspace)
    return workspace


def storage_marker(workspace_dir: Path) -> dict[str, Any] | None:
    return read_json_object(workspace_dir / STORAGE_FORMAT_FILE)


def write_migrated_storage_marker(
    workspace_dir: Path,
    *,
    legacy_backup: str,
) -> None:
    _write_storage_marker(
        workspace_dir,
        migrated_from="sqlite-v1",
        legacy_backup=legacy_backup,
    )


def list_session_payloads(conversations_dir: Path) -> list[dict[str, Any]]:
    sessions_root = conversations_dir / SESSIONS_DIRECTORY
    if not sessions_root.is_dir():
        return []
    payloads: list[dict[str, Any]] = []
    for directory in sessions_root.iterdir():
        if not directory.is_dir() or ".tmp-" in directory.name:
            continue
        payload = read_json_object(directory / SESSION_FILE)
        if payload is not None:
            payloads.append(payload)
    return payloads


def read_session(conversations_dir: Path, session_id: str) -> dict[str, Any] | None:
    return read_json_object(_session_dir(conversations_dir, session_id) / SESSION_FILE)


def write_session(
    conversations_dir: Path,
    session_id: str,
    payload: dict[str, Any],
) -> None:
    if str(payload.get("session_id") or "") != session_id:
        raise ValueError("session payload identity does not match its directory")
    write_json_object(_session_dir(conversations_dir, session_id) / SESSION_FILE, payload)


def write_session_file(
    session_dir: Path,
    session_id: str,
    payload: dict[str, Any],
) -> None:
    """Write a session payload to its actual directory, including staging dirs."""
    if str(payload.get("session_id") or "") != session_id:
        raise ValueError("session payload identity does not match its directory")
    physical_name = session_dir.name.split(".tmp-", 1)[0]
    if physical_name != session_id:
        raise ValueError("session directory identity does not match its payload")
    write_json_object(session_dir / SESSION_FILE, payload)


def delete_session(conversations_dir: Path, session_id: str) -> None:
    directory = _session_dir(conversations_dir, session_id)
    conversation_message_index.remove_session(directory)
    if directory.exists():
        rmtree(directory)


def session_exists(conversations_dir: Path, session_id: str) -> bool:
    return (_session_dir(conversations_dir, session_id) / SESSION_FILE).is_file()


def read_session_state(session_dir: Path) -> dict[str, Any]:
    return read_json_object(session_dir / SESSION_STATE_FILE) or {}


def write_session_state(session_dir: Path, payload: dict[str, Any]) -> None:
    write_json_object(session_dir / SESSION_STATE_FILE, payload)


def read_conversation_control(conversations_dir: Path) -> dict[str, Any]:
    return read_json_object(conversations_dir / CONVERSATION_CONTROL_FILE) or {
        "active_session_id": None,
    }


def write_conversation_control(
    conversations_dir: Path,
    payload: dict[str, Any],
) -> None:
    write_json_object(conversations_dir / CONVERSATION_CONTROL_FILE, payload)


def read_session_branch(session_dir: Path) -> dict[str, Any] | None:
    return read_json_object(session_dir / SESSION_BRANCH_FILE)


def write_session_branch(session_dir: Path, payload: dict[str, Any]) -> None:
    write_json_object(session_dir / SESSION_BRANCH_FILE, payload)


def delete_session_branch(session_dir: Path) -> None:
    (session_dir / SESSION_BRANCH_FILE).unlink(missing_ok=True)


def list_message_payloads(session_dir: Path) -> list[dict[str, Any]]:
    # Full-history consumers always read the authoritative file. The SQLite
    # index is intentionally limited to paging/lookup acceleration so cache
    # damage can never alter or truncate model context.
    return _read_canonical_messages(session_dir)


def count_message_payloads(session_dir: Path) -> int:
    return conversation_message_index.count_payloads(
        session_dir,
        lambda: _read_canonical_messages(session_dir),
    )


def find_message_ordinal(session_dir: Path, message_id: str) -> int | None:
    return conversation_message_index.find_ordinal(
        session_dir,
        message_id,
        lambda: _read_canonical_messages(session_dir),
    )


def list_message_payloads_range(
    session_dir: Path,
    *,
    start_ordinal: int,
    end_ordinal: int,
) -> list[dict[str, Any]]:
    return conversation_message_index.list_payload_range(
        session_dir,
        start_ordinal=start_ordinal,
        end_ordinal=end_ordinal,
        loader=lambda: _read_canonical_messages(session_dir),
    )


def read_message_turn_payloads(
    session_dir: Path,
    message_id: str,
) -> tuple[str | None, list[dict[str, Any]]]:
    return conversation_message_index.read_turn(
        session_dir,
        message_id,
        lambda: _read_canonical_messages(session_dir),
    )


def append_message_payload(
    session_dir: Path,
    message_id: str,
    payload: dict[str, Any],
) -> None:
    if str(payload.get("message_id") or "") != message_id:
        raise ValueError("message payload identity does not match the append request")
    path = session_dir / MESSAGES_FILE
    previous = conversation_message_index.source_fingerprint(path)
    append_jsonl_recoverable(path, payload)
    current = conversation_message_index.source_fingerprint(path)
    conversation_message_index.update_after_append(
        session_dir,
        payload=payload,
        previous_fingerprint=previous,
        current_fingerprint=current,
    )


def replace_message_payloads(
    session_dir: Path,
    payloads: list[dict[str, Any]],
) -> None:
    seen: set[str] = set()
    for payload in payloads:
        message_id = str(payload.get("message_id") or "")
        if not message_id or message_id in seen:
            raise ValueError("message records require unique non-empty message_id values")
        seen.add(message_id)
    replace_jsonl(session_dir / MESSAGES_FILE, payloads)
    conversation_message_index.rebuild(session_dir, payloads)


def append_event(session_dir: Path, kind: str, payload: dict[str, Any]) -> None:
    append_jsonl_recoverable(_event_path(session_dir, kind), payload)


def read_events(session_dir: Path, kind: str) -> list[dict[str, Any]]:
    return read_jsonl(_event_path(session_dir, kind))


def replace_events(
    session_dir: Path,
    kind: str,
    payloads: list[dict[str, Any]],
) -> None:
    replace_jsonl(_event_path(session_dir, kind), payloads)


def read_document(session_dir: Path, kind: str) -> dict[str, Any] | None:
    return read_json_object(_document_path(session_dir, kind))


def write_document(session_dir: Path, kind: str, payload: dict[str, Any]) -> None:
    write_json_object(_document_path(session_dir, kind), payload)


def delete_document(session_dir: Path, kind: str) -> None:
    _document_path(session_dir, kind).unlink(missing_ok=True)


def read_project_events(workspace_dir: Path, kind: str) -> list[dict[str, Any]]:
    root = _project_events_root(workspace_dir, kind)
    if not root.is_dir():
        return []
    records: list[dict[str, Any]] = []
    for batch_path in sorted(root.glob("*.json")):
        batch = read_json_object(batch_path)
        if batch is None:
            continue
        values = batch.get("records")
        if not isinstance(values, list) or not all(isinstance(item, dict) for item in values):
            raise ConflictError(f"项目事件批次格式无效：{batch_path}")
        records.extend(values)
    return records


def append_project_events(
    workspace_dir: Path,
    kind: str,
    payloads: list[dict[str, Any]],
) -> None:
    if not payloads:
        return
    root = _project_events_root(workspace_dir, kind)
    root.mkdir(parents=True, exist_ok=True)
    batch_id = f"{time_ns():020d}-{uuid4().hex}"
    write_json_object(
        root / f"{batch_id}.json",
        {
            "batch_id": batch_id,
            "records": payloads,
        },
    )


def read_workspace_state(workspace_dir: Path) -> dict[str, Any] | None:
    return read_json_object(workspace_dir / WORKSPACE_STATE_FILE)


def write_workspace_state(workspace_dir: Path, payload: dict[str, Any]) -> None:
    write_json_object(workspace_dir / WORKSPACE_STATE_FILE, payload)


def storage_revision_ms(*paths: Path) -> int:
    latest = 0
    for path in paths:
        try:
            if path.is_dir():
                for child in path.rglob("*"):
                    if child.is_file() and CACHE_DIRECTORY not in child.parts:
                        latest = max(latest, int(child.stat().st_mtime_ns // 1_000_000))
            elif path.is_file():
                latest = max(latest, int(path.stat().st_mtime_ns // 1_000_000))
        except OSError:
            continue
    return latest


def _valid_storage_marker(workspace_dir: Path) -> bool:
    try:
        marker = read_json_object(workspace_dir / STORAGE_FORMAT_FILE)
    except ConflictError:
        return False
    return bool(marker and marker.get("version") == STORAGE_FORMAT_VERSION)


def _write_storage_marker(
    workspace_dir: Path,
    *,
    migrated_from: str | None,
    legacy_backup: str | None,
) -> None:
    payload: dict[str, Any] = {
        "version": STORAGE_FORMAT_VERSION,
        "authoritative_storage": "files",
        "sqlite_role": "disposable_message_index",
    }
    if migrated_from is not None:
        payload["migrated_from"] = migrated_from
    if legacy_backup is not None:
        payload["legacy_backup"] = legacy_backup
    write_json_object(workspace_dir / STORAGE_FORMAT_FILE, payload)


def _session_dir(conversations_dir: Path, session_id: str) -> Path:
    safe = require_safe_storage_name(session_id, label="session_id")
    return conversations_dir / SESSIONS_DIRECTORY / safe


def _event_path(session_dir: Path, kind: str) -> Path:
    safe = require_safe_storage_name(kind, label="event kind")
    return session_dir / f"{safe}.jsonl"


def _document_path(session_dir: Path, kind: str) -> Path:
    safe = require_safe_storage_name(kind, label="document kind")
    return session_dir / f"{safe}.json"


def _project_events_root(workspace_dir: Path, kind: str) -> Path:
    safe = require_safe_storage_name(kind, label="project event kind")
    return workspace_dir / PROJECT_EVENTS_DIRECTORY / safe / "events"


def _read_canonical_messages(session_dir: Path) -> list[dict[str, Any]]:
    return read_jsonl(session_dir / MESSAGES_FILE)
