from __future__ import annotations

from collections import defaultdict
from json import loads
from pathlib import Path
import sqlite3
from typing import Any

from app.core.errors import ConflictError
from app.repositories.project.conversation_file_io import (
    read_json_object,
    read_jsonl,
    replace_jsonl,
    write_json_object,
)


LEGACY_SCHEMA_VERSION = 1
MIGRATION_DIRECTORY = "migrations/sqlite-v1"
MIGRATION_BACKUP_FILE = "tiance.db"


def migrate_sqlite_workspace(workspace_dir: Path, database_path: Path) -> None:
    backup_path = workspace_dir / MIGRATION_DIRECTORY / MIGRATION_BACKUP_FILE
    backup_path.parent.mkdir(parents=True, exist_ok=True)

    source = sqlite3.connect(database_path, timeout=10.0)
    try:
        source.execute("PRAGMA busy_timeout=10000")
        _require_legacy_schema(source)
        _backup_database(source, backup_path)
        exported = _export_database(source, workspace_dir)
    finally:
        source.close()

    _validate_export(workspace_dir, exported)

    from app.repositories.project.conversation_records import (
        write_migrated_storage_marker,
    )

    write_migrated_storage_marker(
        workspace_dir,
        legacy_backup=(
            Path(MIGRATION_DIRECTORY) / MIGRATION_BACKUP_FILE
        ).as_posix(),
    )
    database_path.unlink(missing_ok=True)
    database_path.with_name(f"{database_path.name}-wal").unlink(missing_ok=True)
    database_path.with_name(f"{database_path.name}-shm").unlink(missing_ok=True)


def _export_database(
    connection: sqlite3.Connection,
    workspace_dir: Path,
) -> dict[str, int]:
    conversations_dir = workspace_dir / "conversations"
    sessions_root = conversations_dir / "sessions"
    sessions_root.mkdir(parents=True, exist_ok=True)

    meta = {
        str(row[0]): _decode(row[1])
        for row in connection.execute(
            "SELECT key, value_json FROM conversation_meta ORDER BY key"
        ).fetchall()
    }

    session_rows = connection.execute(
        "SELECT session_id, payload_json FROM conversation_sessions ORDER BY session_id"
    ).fetchall()
    for session_id, payload_json in session_rows:
        session_dir = sessions_root / str(session_id)
        session_dir.mkdir(parents=True, exist_ok=True)
        write_json_object(session_dir / "session.json", _require_object(payload_json))

    message_count = 0
    for session_id, _payload_json in session_rows:
        rows = connection.execute(
            """
            SELECT payload_json FROM conversation_messages
            WHERE session_id = ? ORDER BY ordinal
            """,
            (session_id,),
        ).fetchall()
        payloads = [_require_object(row[0]) for row in rows]
        replace_jsonl(sessions_root / str(session_id) / "messages.jsonl", payloads)
        message_count += len(payloads)

    event_count = 0
    event_groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for session_id, kind, payload_json in connection.execute(
        """
        SELECT session_id, kind, payload_json FROM conversation_session_events
        ORDER BY session_id, kind, ordinal
        """
    ).fetchall():
        event_groups[(str(session_id), str(kind))].append(_require_object(payload_json))
        event_count += 1
    for (session_id, kind), payloads in event_groups.items():
        replace_jsonl(sessions_root / session_id / f"{kind}.jsonl", payloads)

    document_count = 0
    for session_id, kind, payload_json in connection.execute(
        """
        SELECT session_id, kind, payload_json FROM conversation_session_documents
        ORDER BY session_id, kind
        """
    ).fetchall():
        write_json_object(
            sessions_root / str(session_id) / f"{kind}.json",
            _require_object(payload_json),
        )
        document_count += 1

    project_event_count = 0
    project_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for kind, payload_json in connection.execute(
        """
        SELECT kind, payload_json FROM conversation_project_events
        ORDER BY kind, ordinal
        """
    ).fetchall():
        project_groups[str(kind)].append(_require_object(payload_json))
        project_event_count += 1
    for kind, payloads in project_groups.items():
        write_json_object(
            workspace_dir / "memory" / kind / "events" / "migration-sqlite-v1.json",
            {
                "batch_id": "migration-sqlite-v1",
                "records": payloads,
            },
        )

    _export_conversation_index(
        conversations_dir,
        sessions_root,
        meta.get("conversation_index"),
    )
    _export_branch_graph(
        conversations_dir,
        sessions_root,
        meta.get("branch_graph"),
    )
    workspace_state = meta.get("workspace_state")
    if isinstance(workspace_state, dict):
        write_json_object(workspace_dir / "state.json", workspace_state)

    return {
        "sessions": len(session_rows),
        "messages": message_count,
        "events": event_count,
        "documents": document_count,
        "project_events": project_event_count,
    }


def _export_conversation_index(
    conversations_dir: Path,
    sessions_root: Path,
    raw_index: Any,
) -> None:
    index = raw_index if isinstance(raw_index, dict) else {}
    write_json_object(
        conversations_dir / "control.json",
        {"active_session_id": index.get("active_session_id")},
    )
    pinned = {
        str(item)
        for item in index.get("pinned_session_ids", [])
        if isinstance(item, str)
    }
    states = index.get("session_states")
    states = states if isinstance(states, dict) else {}
    for session_dir in sessions_root.iterdir():
        if not session_dir.is_dir():
            continue
        state = states.get(session_dir.name)
        write_json_object(
            session_dir / "state.json",
            {
                "pinned": session_dir.name in pinned,
                "runtime": state if isinstance(state, dict) else {},
            },
        )


def _export_branch_graph(
    conversations_dir: Path,
    sessions_root: Path,
    raw_graph: Any,
) -> None:
    graph = raw_graph if isinstance(raw_graph, dict) else {}
    nodes = [item for item in graph.get("nodes", []) if isinstance(item, dict)]
    variants = [item for item in graph.get("variants", []) if isinstance(item, dict)]
    nodes_by_session = {
        str(item.get("session_id") or ""): item
        for item in nodes
        if item.get("session_id")
    }
    variants_by_session: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in variants:
        session_id = str(item.get("session_id") or "")
        if session_id:
            variants_by_session[session_id].append(item)

    tombstones = conversations_dir / "tombstones"
    for session_id in sorted(set(nodes_by_session) | set(variants_by_session)):
        payload = {
            "version": 1,
            "node": nodes_by_session.get(session_id),
            "variants": variants_by_session.get(session_id, []),
        }
        session_dir = sessions_root / session_id
        target = (
            session_dir / "branch.json"
            if (session_dir / "session.json").is_file()
            else tombstones / f"{session_id}.json"
        )
        write_json_object(target, payload)


def _validate_export(workspace_dir: Path, expected: dict[str, int]) -> None:
    sessions_root = workspace_dir / "conversations" / "sessions"
    session_dirs = [
        item
        for item in sessions_root.iterdir()
        if item.is_dir() and (item / "session.json").is_file()
    ]
    if len(session_dirs) != expected["sessions"]:
        raise ConflictError("SQLite 会话迁移校验失败：会话数量不一致。")
    message_count = sum(
        len(read_jsonl(session_dir / "messages.jsonl"))
        for session_dir in session_dirs
    )
    if message_count != expected["messages"]:
        raise ConflictError("SQLite 会话迁移校验失败：消息数量不一致。")
    event_count = sum(
        len(read_jsonl(path))
        for session_dir in session_dirs
        for path in session_dir.glob("*.jsonl")
        if path.name != "messages.jsonl"
    )
    if event_count != expected["events"]:
        raise ConflictError("SQLite 会话迁移校验失败：会话事件数量不一致。")
    document_count = sum(
        1
        for session_dir in session_dirs
        for path in session_dir.glob("*.json")
        if path.name not in {"session.json", "state.json", "branch.json"}
        and read_json_object(path) is not None
    )
    if document_count != expected["documents"]:
        raise ConflictError("SQLite 会话迁移校验失败：会话文档数量不一致。")
    project_event_count = 0
    memory_root = workspace_dir / "memory"
    if memory_root.is_dir():
        for path in memory_root.glob("*/events/*.json"):
            batch = read_json_object(path)
            records = batch.get("records") if batch else None
            if not isinstance(records, list) or not all(
                isinstance(item, dict) for item in records
            ):
                raise ConflictError("SQLite 会话迁移校验失败：项目事件格式无效。")
            project_event_count += len(records)
    if project_event_count != expected["project_events"]:
        raise ConflictError("SQLite 会话迁移校验失败：项目事件数量不一致。")


def _backup_database(source: sqlite3.Connection, backup_path: Path) -> None:
    backup = sqlite3.connect(backup_path)
    try:
        source.backup(backup)
        backup.commit()
    finally:
        backup.close()


def _require_legacy_schema(connection: sqlite3.Connection) -> None:
    row = connection.execute("SELECT version FROM conversation_schema LIMIT 1").fetchone()
    if row is None or int(row[0]) != LEGACY_SCHEMA_VERSION:
        raise ConflictError(
            f"不支持的旧会话数据库版本：{row[0] if row is not None else 'missing'}"
        )


def _require_object(value_json: str) -> dict[str, Any]:
    value = _decode(value_json)
    if not isinstance(value, dict):
        raise ConflictError("SQLite 会话数据包含非对象记录，已停止迁移。")
    return value


def _decode(value_json: str) -> Any:
    try:
        return loads(value_json)
    except ValueError as exc:
        raise ConflictError("SQLite 会话数据包含无效 JSON，已停止迁移。") from exc
