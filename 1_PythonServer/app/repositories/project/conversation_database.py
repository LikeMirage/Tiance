from __future__ import annotations

from contextlib import contextmanager
from gzip import decompress as gzip_decompress
from hashlib import sha256
from json import dumps, loads
from pathlib import Path
import sqlite3
from threading import Lock, local
from typing import Any, Iterator
from zlib import error as zlib_error


DATABASE_FILE = "tiance.db"
SCHEMA_VERSION = 4
_thread_state = local()
_database_initialization_lock = Lock()
_initialized_database_paths: set[Path] = set()


def database_path_from_workspace(workspace_dir: Path) -> Path:
    return workspace_dir / DATABASE_FILE


def database_path_from_conversations(conversations_dir: Path) -> Path:
    return database_path_from_workspace(conversations_dir.parent)


def database_path_from_session(session_dir: Path) -> Path:
    return database_path_from_conversations(session_dir.parent.parent)


def session_id_from_session_dir(session_dir: Path) -> str:
    return session_dir.name.split(".tmp-", 1)[0]


def ensure_database(workspace_dir: Path) -> Path:
    workspace_dir.mkdir(parents=True, exist_ok=True)
    path = database_path_from_workspace(workspace_dir).resolve()
    with _database_initialization_lock:
        if path in _initialized_database_paths and path.is_file():
            return path
        _initialized_database_paths.discard(path)
        connection = _open_connection(path)
        try:
            current_mode = str(connection.execute("PRAGMA journal_mode").fetchone()[0]).lower()
            if current_mode != "wal":
                connection.execute("PRAGMA journal_mode=WAL")
            _ensure_schema(connection)
            connection.commit()
        finally:
            connection.close()
        _initialized_database_paths.add(path)
    return path


@contextmanager
def transaction_for_conversations(conversations_dir: Path) -> Iterator[sqlite3.Connection]:
    path = database_path_from_conversations(conversations_dir).resolve()
    active = getattr(_thread_state, "transactions", None)
    if active is None:
        active = {}
        _thread_state.transactions = active
    existing = active.get(path)
    if existing is not None:
        existing[1] += 1
        try:
            yield existing[0]
        finally:
            existing[1] -= 1
        return

    ensure_database(path.parent)
    connection = _open_connection(path)
    connection.execute("BEGIN IMMEDIATE")
    active[path] = [connection, 1]
    try:
        yield connection
        _increment_conversation_revision(connection)
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        active.pop(path, None)
        connection.close()


@contextmanager
def connection_for_path(path: Path) -> Iterator[sqlite3.Connection]:
    resolved = path.resolve()
    active = getattr(_thread_state, "transactions", {})
    existing = active.get(resolved)
    if existing is not None:
        yield existing[0]
        return
    ensure_database(resolved.parent)
    connection = _open_connection(resolved)
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


@contextmanager
def read_connection_for_path(path: Path) -> Iterator[sqlite3.Connection | None]:
    """Open an existing database without creating files or running migrations."""
    resolved = path.resolve()
    active = getattr(_thread_state, "transactions", {})
    existing = active.get(resolved)
    if existing is not None:
        yield existing[0]
        return
    if not resolved.is_file():
        yield None
        return
    connection = _open_read_connection(resolved)
    try:
        yield connection
    finally:
        connection.close()


def read_meta(conversations_dir: Path, key: str, default: Any = None) -> Any:
    with read_connection_for_path(database_path_from_conversations(conversations_dir)) as connection:
        if connection is None:
            return default
        row = connection.execute(
            "SELECT value_json FROM conversation_meta WHERE key = ?",
            (key,),
        ).fetchone()
    return _decode(row[0]) if row is not None else default


def write_meta(conversations_dir: Path, key: str, value: Any) -> None:
    with connection_for_path(database_path_from_conversations(conversations_dir)) as connection:
        connection.execute(
            """
            INSERT INTO conversation_meta(key, value_json) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json
            """,
            (key, _encode(value)),
        )


def read_session(conversations_dir: Path, session_id: str) -> dict[str, Any] | None:
    with read_connection_for_path(database_path_from_conversations(conversations_dir)) as connection:
        if connection is None:
            return None
        row = connection.execute(
            "SELECT payload_json FROM conversation_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
    value = _decode(row[0]) if row is not None else None
    return value if isinstance(value, dict) else None


def read_sessions(conversations_dir: Path) -> dict[str, dict[str, Any]]:
    """Read all session records with one database connection."""
    with read_connection_for_path(database_path_from_conversations(conversations_dir)) as connection:
        if connection is None:
            return {}
        rows = connection.execute(
            "SELECT session_id, payload_json FROM conversation_sessions",
        ).fetchall()
    result: dict[str, dict[str, Any]] = {}
    for session_id, raw_payload in rows:
        payload = _decode(raw_payload)
        if isinstance(payload, dict):
            result[str(session_id)] = payload
    return result


def read_conversation_list_snapshot(
    conversations_dir: Path,
) -> tuple[int, Any, dict[str, dict[str, Any]], dict[str, dict[str, Any]], Any]:
    """Read one consistent projection for conversation-list consumers."""
    path = database_path_from_conversations(conversations_dir).resolve()
    active_transactions = getattr(_thread_state, "transactions", {})
    owns_snapshot = path not in active_transactions
    with read_connection_for_path(path) as connection:
        if connection is None:
            return 0, None, {}, {}, None
        if owns_snapshot:
            connection.execute("BEGIN")
        meta_rows = connection.execute(
            """
            SELECT key, value_json FROM conversation_meta
            WHERE key IN ('conversation_revision', 'conversation_index', 'branch_graph')
            """,
        ).fetchall()
        session_rows = connection.execute(
            "SELECT session_id, payload_json FROM conversation_sessions",
        ).fetchall()
        state_rows = connection.execute(
            """
            SELECT session.session_id,
                   runtime.runtime_status, runtime.updated_at,
                   draft.draft, draft.updated_at,
                   reference.payload_json, reference.updated_at
            FROM conversation_sessions AS session
            LEFT JOIN conversation_session_runtime_states AS runtime
                ON runtime.session_id = session.session_id
            LEFT JOIN conversation_session_drafts AS draft
                ON draft.session_id = session.session_id
            LEFT JOIN conversation_session_references AS reference
                ON reference.session_id = session.session_id
            """
        ).fetchall()

    meta = {str(key): _decode(raw_value) for key, raw_value in meta_rows}
    sessions: dict[str, dict[str, Any]] = {}
    for session_id, raw_payload in session_rows:
        payload = _decode(raw_payload)
        if isinstance(payload, dict):
            sessions[str(session_id)] = payload
    raw_revision = meta.get("conversation_revision", 0)
    revision = raw_revision if isinstance(raw_revision, int) and raw_revision >= 0 else 0
    return (
        revision,
        meta.get("conversation_index"),
        sessions,
        _session_state_payloads_from_rows(state_rows),
        meta.get("branch_graph"),
    )


def write_session(conversations_dir: Path, session_id: str, payload: dict[str, Any]) -> None:
    with connection_for_path(database_path_from_conversations(conversations_dir)) as connection:
        connection.execute(
            """
            INSERT INTO conversation_sessions(session_id, payload_json) VALUES (?, ?)
            ON CONFLICT(session_id) DO UPDATE SET payload_json = excluded.payload_json
            """,
            (session_id, _encode(payload)),
        )


def delete_session(conversations_dir: Path, session_id: str) -> None:
    with connection_for_path(database_path_from_conversations(conversations_dir)) as connection:
        connection.execute(
            "DELETE FROM conversation_sessions WHERE session_id = ?",
            (session_id,),
        )


def session_exists(conversations_dir: Path, session_id: str) -> bool:
    with read_connection_for_path(database_path_from_conversations(conversations_dir)) as connection:
        if connection is None:
            return False
        row = connection.execute(
            "SELECT 1 FROM conversation_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
    return row is not None


def read_session_state_payloads(
    conversations_dir: Path,
    session_ids: set[str] | None = None,
) -> dict[str, dict[str, Any]]:
    with read_connection_for_path(database_path_from_conversations(conversations_dir)) as connection:
        if connection is None:
            return {}
        rows = connection.execute(
            """
            SELECT session.session_id,
                   runtime.runtime_status, runtime.updated_at,
                   draft.draft, draft.updated_at,
                   reference.payload_json, reference.updated_at
            FROM conversation_sessions AS session
            LEFT JOIN conversation_session_runtime_states AS runtime
                ON runtime.session_id = session.session_id
            LEFT JOIN conversation_session_drafts AS draft
                ON draft.session_id = session.session_id
            LEFT JOIN conversation_session_references AS reference
                ON reference.session_id = session.session_id
            """
        ).fetchall()
    result = _session_state_payloads_from_rows(rows)
    if session_ids is None:
        return result
    return {
        session_id: payload
        for session_id, payload in result.items()
        if session_id in session_ids
    }


def _session_state_payloads_from_rows(
    rows: list[sqlite3.Row] | list[tuple[Any, ...]],
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        session_id = str(row[0])
        references = _decode(row[5]) if row[5] is not None else []
        result[session_id] = {
            "runtime_status": str(row[1] or "idle"),
            "runtime_updated_at": str(row[2] or ""),
            "draft": str(row[3] or ""),
            "draft_updated_at": str(row[4] or ""),
            "references": references if isinstance(references, list) else [],
            "references_updated_at": str(row[6] or ""),
        }
    return result


def write_session_runtime_state(
    conversations_dir: Path,
    session_id: str,
    runtime_status: str,
    updated_at: str,
) -> None:
    with connection_for_path(database_path_from_conversations(conversations_dir)) as connection:
        connection.execute(
            """
            INSERT INTO conversation_session_runtime_states(
                session_id, runtime_status, updated_at
            ) VALUES (?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                runtime_status = excluded.runtime_status,
                updated_at = excluded.updated_at
            """,
            (session_id, runtime_status, updated_at),
        )


def write_session_draft(
    conversations_dir: Path,
    session_id: str,
    draft: str,
    updated_at: str,
) -> None:
    with connection_for_path(database_path_from_conversations(conversations_dir)) as connection:
        connection.execute(
            """
            INSERT INTO conversation_session_drafts(session_id, draft, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                draft = excluded.draft,
                updated_at = excluded.updated_at
            """,
            (session_id, draft, updated_at),
        )


def write_session_references(
    conversations_dir: Path,
    session_id: str,
    references: list[dict[str, Any]],
    updated_at: str,
) -> None:
    with connection_for_path(database_path_from_conversations(conversations_dir)) as connection:
        connection.execute(
            """
            INSERT INTO conversation_session_references(
                session_id, payload_json, updated_at
            ) VALUES (?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                payload_json = excluded.payload_json,
                updated_at = excluded.updated_at
            """,
            (session_id, _encode(references), updated_at),
        )


def list_message_payloads(session_dir: Path) -> list[dict[str, Any]]:
    session_id = session_id_from_session_dir(session_dir)
    with read_connection_for_path(database_path_from_session(session_dir)) as connection:
        if connection is None:
            return []
        rows = connection.execute(
            """
            SELECT payload_json FROM conversation_messages
            WHERE session_id = ? ORDER BY ordinal
            """,
            (session_id,),
        ).fetchall()
    return [value for row in rows if isinstance((value := _decode(row[0])), dict)]


def count_message_payloads(session_dir: Path) -> int:
    with read_connection_for_path(database_path_from_session(session_dir)) as connection:
        if connection is None:
            return 0
        row = connection.execute(
            "SELECT COUNT(*) FROM conversation_messages WHERE session_id = ?",
            (session_id_from_session_dir(session_dir),),
        ).fetchone()
    return int(row[0]) if row is not None else 0


def find_message_ordinal(session_dir: Path, message_id: str) -> int | None:
    with read_connection_for_path(database_path_from_session(session_dir)) as connection:
        if connection is None:
            return None
        row = connection.execute(
            """
            SELECT ordinal FROM conversation_messages
            WHERE session_id = ? AND message_id = ?
            """,
            (session_id_from_session_dir(session_dir), message_id),
        ).fetchone()
    return int(row[0]) if row is not None else None


def latest_user_message_id(session_dir: Path) -> str | None:
    with read_connection_for_path(database_path_from_session(session_dir)) as connection:
        if connection is None:
            return None
        row = connection.execute(
            """
            SELECT message_id FROM conversation_messages
            WHERE session_id = ? AND json_extract(payload_json, '$.role') = 'user'
            ORDER BY ordinal DESC LIMIT 1
            """,
            (session_id_from_session_dir(session_dir),),
        ).fetchone()
    return str(row[0]) if row is not None else None


def list_message_payloads_range(
    session_dir: Path,
    *,
    start_ordinal: int,
    end_ordinal: int,
) -> list[dict[str, Any]]:
    with read_connection_for_path(database_path_from_session(session_dir)) as connection:
        if connection is None:
            return []
        rows = connection.execute(
            """
            SELECT payload_json FROM conversation_messages
            WHERE session_id = ? AND ordinal >= ? AND ordinal < ?
            ORDER BY ordinal
            """,
            (
                session_id_from_session_dir(session_dir),
                start_ordinal,
                end_ordinal,
            ),
        ).fetchall()
    return [value for row in rows if isinstance((value := _decode(row[0])), dict)]


def read_message_turn_payloads(
    session_dir: Path,
    message_id: str,
) -> tuple[str | None, list[dict[str, Any]]]:
    session_id = session_id_from_session_dir(session_dir)
    with read_connection_for_path(database_path_from_session(session_dir)) as connection:
        if connection is None:
            return None, []
        target = connection.execute(
            """
            SELECT ordinal, json_extract(payload_json, '$.role')
            FROM conversation_messages
            WHERE session_id = ? AND message_id = ?
            """,
            (session_id, message_id),
        ).fetchone()
        if target is None:
            return None, []
        target_ordinal = int(target[0])
        target_role = str(target[1]) if target[1] is not None else ""
        if target_role != "user":
            return target_role, []
        boundary = connection.execute(
            """
            SELECT MIN(ordinal)
            FROM conversation_messages
            WHERE session_id = ? AND ordinal > ?
              AND json_extract(payload_json, '$.role') = 'user'
            """,
            (session_id, target_ordinal),
        ).fetchone()[0]
        if boundary is None:
            rows = connection.execute(
                """
                SELECT payload_json FROM conversation_messages
                WHERE session_id = ? AND ordinal >= ?
                ORDER BY ordinal
                """,
                (session_id, target_ordinal),
            ).fetchall()
        else:
            rows = connection.execute(
                """
                SELECT payload_json FROM conversation_messages
                WHERE session_id = ? AND ordinal >= ? AND ordinal < ?
                ORDER BY ordinal
                """,
                (session_id, target_ordinal, int(boundary)),
            ).fetchall()
    return target_role, [
        value for row in rows if isinstance((value := _decode(row[0])), dict)
    ]


def append_message_payload(session_dir: Path, message_id: str, payload: dict[str, Any]) -> None:
    session_id = session_id_from_session_dir(session_dir)
    with connection_for_path(database_path_from_session(session_dir)) as connection:
        ordinal = connection.execute(
            "SELECT COALESCE(MAX(ordinal), -1) + 1 FROM conversation_messages WHERE session_id = ?",
            (session_id,),
        ).fetchone()[0]
        connection.execute(
            """
            INSERT INTO conversation_messages(session_id, ordinal, message_id, payload_json)
            VALUES (?, ?, ?, ?)
            """,
            (session_id, ordinal, message_id, _encode(payload)),
        )


def replace_message_payloads(session_dir: Path, payloads: list[dict[str, Any]]) -> None:
    session_id = session_id_from_session_dir(session_dir)
    with connection_for_path(database_path_from_session(session_dir)) as connection:
        connection.execute(
            "DELETE FROM conversation_messages WHERE session_id = ?",
            (session_id,),
        )
        connection.executemany(
            """
            INSERT INTO conversation_messages(session_id, ordinal, message_id, payload_json)
            VALUES (?, ?, ?, ?)
            """,
            [
                (session_id, ordinal, str(payload.get("message_id") or ""), _encode(payload))
                for ordinal, payload in enumerate(payloads)
            ],
        )


def append_event(session_dir: Path, kind: str, payload: dict[str, Any]) -> None:
    session_id = session_id_from_session_dir(session_dir)
    with connection_for_path(database_path_from_session(session_dir)) as connection:
        ordinal = connection.execute(
            """
            SELECT COALESCE(MAX(ordinal), -1) + 1 FROM conversation_session_events
            WHERE session_id = ? AND kind = ?
            """,
            (session_id, kind),
        ).fetchone()[0]
        connection.execute(
            """
            INSERT INTO conversation_session_events(session_id, kind, ordinal, payload_json)
            VALUES (?, ?, ?, ?)
            """,
            (session_id, kind, ordinal, _encode(payload)),
        )


def read_events(session_dir: Path, kind: str) -> list[dict[str, Any]]:
    with read_connection_for_path(database_path_from_session(session_dir)) as connection:
        if connection is None:
            return []
        rows = connection.execute(
            """
            SELECT payload_json FROM conversation_session_events
            WHERE session_id = ? AND kind = ? ORDER BY ordinal
            """,
            (session_id_from_session_dir(session_dir), kind),
        ).fetchall()
    return [value for row in rows if isinstance((value := _decode(row[0])), dict)]


def count_events(session_dir: Path, kind: str) -> int:
    with read_connection_for_path(database_path_from_session(session_dir)) as connection:
        if connection is None:
            return 0
        row = connection.execute(
            """
            SELECT COUNT(*) FROM conversation_session_events
            WHERE session_id = ? AND kind = ?
            """,
            (session_id_from_session_dir(session_dir), kind),
        ).fetchone()
    return int(row[0]) if row is not None else 0


def list_events_range(
    session_dir: Path,
    kind: str,
    *,
    start_ordinal: int,
    end_ordinal: int,
) -> list[dict[str, Any]]:
    with read_connection_for_path(database_path_from_session(session_dir)) as connection:
        if connection is None:
            return []
        rows = connection.execute(
            """
            SELECT payload_json FROM conversation_session_events
            WHERE session_id = ? AND kind = ? AND ordinal >= ? AND ordinal < ?
            ORDER BY ordinal
            """,
            (
                session_id_from_session_dir(session_dir),
                kind,
                start_ordinal,
                end_ordinal,
            ),
        ).fetchall()
    return [value for row in rows if isinstance((value := _decode(row[0])), dict)]


def replace_events(session_dir: Path, kind: str, payloads: list[dict[str, Any]]) -> None:
    with connection_for_path(database_path_from_session(session_dir)) as connection:
        connection.execute(
            "DELETE FROM conversation_session_events WHERE session_id = ? AND kind = ?",
            (session_id_from_session_dir(session_dir), kind),
        )
        connection.executemany(
            """
            INSERT INTO conversation_session_events(session_id, kind, ordinal, payload_json)
            VALUES (?, ?, ?, ?)
            """,
            [
                (session_id_from_session_dir(session_dir), kind, ordinal, _encode(payload))
                for ordinal, payload in enumerate(payloads)
            ],
        )


def read_document(session_dir: Path, kind: str) -> dict[str, Any] | None:
    with read_connection_for_path(database_path_from_session(session_dir)) as connection:
        if connection is None:
            return None
        row = connection.execute(
            """
            SELECT payload_json FROM conversation_session_documents
            WHERE session_id = ? AND kind = ?
            """,
            (session_id_from_session_dir(session_dir), kind),
        ).fetchone()
    value = _decode(row[0]) if row is not None else None
    return value if isinstance(value, dict) else None


def write_document(session_dir: Path, kind: str, payload: dict[str, Any]) -> None:
    with connection_for_path(database_path_from_session(session_dir)) as connection:
        connection.execute(
            """
            INSERT INTO conversation_session_documents(session_id, kind, payload_json)
            VALUES (?, ?, ?)
            ON CONFLICT(session_id, kind) DO UPDATE SET payload_json = excluded.payload_json
            """,
            (session_id_from_session_dir(session_dir), kind, _encode(payload)),
        )


def delete_document(session_dir: Path, kind: str) -> None:
    with connection_for_path(database_path_from_session(session_dir)) as connection:
        connection.execute(
            "DELETE FROM conversation_session_documents WHERE session_id = ? AND kind = ?",
            (session_id_from_session_dir(session_dir), kind),
        )


def read_project_events(workspace_dir: Path, kind: str) -> list[dict[str, Any]]:
    with read_connection_for_path(database_path_from_workspace(workspace_dir)) as connection:
        if connection is None:
            return []
        rows = connection.execute(
            "SELECT payload_json FROM conversation_project_events WHERE kind = ? ORDER BY ordinal",
            (kind,),
        ).fetchall()
    return [value for row in rows if isinstance((value := _decode(row[0])), dict)]


def count_project_events(workspace_dir: Path, kind: str) -> int:
    with read_connection_for_path(database_path_from_workspace(workspace_dir)) as connection:
        if connection is None:
            return 0
        row = connection.execute(
            "SELECT COUNT(*) FROM conversation_project_events WHERE kind = ?",
            (kind,),
        ).fetchone()
    return int(row[0]) if row is not None else 0


def list_project_events_range(
    workspace_dir: Path,
    kind: str,
    *,
    start_ordinal: int,
    end_ordinal: int,
) -> list[dict[str, Any]]:
    with read_connection_for_path(database_path_from_workspace(workspace_dir)) as connection:
        if connection is None:
            return []
        rows = connection.execute(
            """
            SELECT payload_json FROM conversation_project_events
            WHERE kind = ? AND ordinal >= ? AND ordinal < ?
            ORDER BY ordinal
            """,
            (kind, start_ordinal, end_ordinal),
        ).fetchall()
    return [value for row in rows if isinstance((value := _decode(row[0])), dict)]


def append_project_events(workspace_dir: Path, kind: str, payloads: list[dict[str, Any]]) -> None:
    if not payloads:
        return
    with connection_for_path(database_path_from_workspace(workspace_dir)) as connection:
        start = connection.execute(
            "SELECT COALESCE(MAX(ordinal), -1) + 1 FROM conversation_project_events WHERE kind = ?",
            (kind,),
        ).fetchone()[0]
        connection.executemany(
            """
            INSERT INTO conversation_project_events(kind, ordinal, payload_json)
            VALUES (?, ?, ?)
            """,
            [(kind, start + index, _encode(payload)) for index, payload in enumerate(payloads)],
        )


def append_journal_event(
    workspace_dir: Path,
    *,
    session_id: str | None,
    run_id: str | None,
    turn_id: str | None,
    tool_call_id: str | None,
    event_type: str,
    occurred_at: str,
    payload: dict[str, Any],
    artifact_id: str | None = None,
) -> int:
    with connection_for_path(database_path_from_workspace(workspace_dir)) as connection:
        cursor = connection.execute(
            """
            INSERT INTO conversation_journal(
                session_id, run_id, turn_id, tool_call_id, event_type,
                occurred_at, payload_json, artifact_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                run_id,
                turn_id,
                tool_call_id,
                event_type,
                occurred_at,
                _encode(payload),
                artifact_id,
            ),
        )
        return int(cursor.lastrowid)


def count_journal_events(workspace_dir: Path, *, session_id: str | None = None) -> int:
    with read_connection_for_path(database_path_from_workspace(workspace_dir)) as connection:
        if connection is None:
            return 0
        if session_id is None:
            row = connection.execute("SELECT COUNT(*) FROM conversation_journal").fetchone()
        else:
            row = connection.execute(
                "SELECT COUNT(*) FROM conversation_journal WHERE session_id = ?",
                (session_id,),
            ).fetchone()
    return int(row[0]) if row is not None else 0


def list_journal_events_range(
    workspace_dir: Path,
    *,
    session_id: str | None,
    offset: int,
    limit: int,
) -> list[dict[str, Any]]:
    with read_connection_for_path(database_path_from_workspace(workspace_dir)) as connection:
        if connection is None:
            return []
        if session_id is None:
            rows = connection.execute(
                """
                SELECT event_id, session_id, run_id, turn_id, tool_call_id,
                       event_type, occurred_at, payload_json, artifact_id
                FROM conversation_journal
                ORDER BY event_id LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
        else:
            rows = connection.execute(
                """
                SELECT event_id, session_id, run_id, turn_id, tool_call_id,
                       event_type, occurred_at, payload_json, artifact_id
                FROM conversation_journal
                WHERE session_id = ?
                ORDER BY event_id LIMIT ? OFFSET ?
                """,
                (session_id, limit, offset),
            ).fetchall()
    return [
        {
            "event_id": int(row[0]),
            "session_id": row[1],
            "run_id": row[2],
            "turn_id": row[3],
            "tool_call_id": row[4],
            "event_type": row[5],
            "occurred_at": row[6],
            "payload": _decode(row[7]),
            "artifact_id": row[8],
        }
        for row in rows
    ]


def write_artifact_record(
    workspace_dir: Path,
    *,
    artifact_id: str,
    session_id: str,
    kind: str,
    relative_path: str,
    media_type: str,
    encoding: str | None,
    size_bytes: int,
    sha256: str,
    status: str,
    created_at: str,
    metadata: dict[str, Any],
    payload_blob: bytes | None = None,
    compression: str | None = None,
    stored_size_bytes: int | None = None,
) -> None:
    with connection_for_path(database_path_from_workspace(workspace_dir)) as connection:
        connection.execute(
            """
            INSERT INTO conversation_artifacts(
                artifact_id, session_id, kind, relative_path, media_type,
                encoding, size_bytes, sha256, status, created_at, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                artifact_id,
                session_id,
                kind,
                relative_path,
                media_type,
                encoding,
                size_bytes,
                sha256,
                status,
                created_at,
                _encode(metadata),
            ),
        )
        if payload_blob is not None:
            if compression is None or stored_size_bytes is None:
                raise ValueError("Embedded artifact payload requires compression metadata.")
            if stored_size_bytes != len(payload_blob):
                raise ValueError("Embedded artifact stored size does not match its payload.")
            connection.execute(
                """
                INSERT INTO conversation_artifact_payloads(
                    artifact_id, compression, stored_size_bytes, payload_blob
                ) VALUES (?, ?, ?, ?)
                """,
                (artifact_id, compression, stored_size_bytes, payload_blob),
            )


def count_embedded_artifacts(
    workspace_dir: Path,
    *,
    session_id: str,
    kind: str,
) -> int:
    with read_connection_for_path(database_path_from_workspace(workspace_dir)) as connection:
        if connection is None:
            return 0
        row = connection.execute(
            """
            SELECT COUNT(*)
            FROM conversation_artifacts AS artifact
            INNER JOIN conversation_artifact_payloads AS payload
                ON payload.artifact_id = artifact.artifact_id
            WHERE artifact.session_id = ? AND artifact.kind = ?
            """,
            (session_id, kind),
        ).fetchone()
    return int(row[0]) if row is not None else 0


def list_embedded_artifacts_range(
    workspace_dir: Path,
    *,
    session_id: str,
    kind: str,
    offset: int,
    limit: int,
) -> list[dict[str, Any]]:
    with read_connection_for_path(database_path_from_workspace(workspace_dir)) as connection:
        if connection is None:
            return []
        rows = connection.execute(
            """
            SELECT artifact.artifact_id, artifact.created_at, artifact.media_type,
                   artifact.encoding, artifact.size_bytes, artifact.sha256,
                   artifact.status, artifact.metadata_json, payload.compression,
                   payload.stored_size_bytes, payload.payload_blob
            FROM conversation_artifacts AS artifact
            INNER JOIN conversation_artifact_payloads AS payload
                ON payload.artifact_id = artifact.artifact_id
            WHERE artifact.session_id = ? AND artifact.kind = ?
            ORDER BY artifact.created_at, artifact.artifact_id
            LIMIT ? OFFSET ?
            """,
            (session_id, kind, limit, offset),
        ).fetchall()
    return [_restore_embedded_artifact(row) for row in rows]


def journal_mode(database_path: Path) -> str:
    with read_connection_for_path(database_path) as connection:
        if connection is None:
            raise FileNotFoundError(database_path)
        return str(connection.execute("PRAGMA journal_mode").fetchone()[0]).lower()


def _open_connection(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10.0)
    connection.execute("PRAGMA busy_timeout=10000")
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA synchronous=NORMAL")
    return connection


def _open_read_connection(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, timeout=10.0)
    connection.execute("PRAGMA busy_timeout=10000")
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def _ensure_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS conversation_schema (
            version INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS conversation_meta (
            key TEXT PRIMARY KEY,
            value_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS conversation_sessions (
            session_id TEXT PRIMARY KEY,
            payload_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS conversation_messages (
            session_id TEXT NOT NULL,
            ordinal INTEGER NOT NULL,
            message_id TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            PRIMARY KEY(session_id, ordinal),
            UNIQUE(session_id, message_id),
            FOREIGN KEY(session_id) REFERENCES conversation_sessions(session_id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_conversation_messages_id
            ON conversation_messages(message_id);
        CREATE TABLE IF NOT EXISTS conversation_session_documents (
            session_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            PRIMARY KEY(session_id, kind),
            FOREIGN KEY(session_id) REFERENCES conversation_sessions(session_id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS conversation_session_events (
            session_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            ordinal INTEGER NOT NULL,
            payload_json TEXT NOT NULL,
            PRIMARY KEY(session_id, kind, ordinal),
            FOREIGN KEY(session_id) REFERENCES conversation_sessions(session_id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS conversation_project_events (
            kind TEXT NOT NULL,
            ordinal INTEGER NOT NULL,
            payload_json TEXT NOT NULL,
            PRIMARY KEY(kind, ordinal)
        );
        """
    )
    row = connection.execute("SELECT version FROM conversation_schema LIMIT 1").fetchone()
    if row is None:
        current_version = 1
        connection.execute("INSERT INTO conversation_schema(version) VALUES (?)", (current_version,))
    else:
        current_version = int(row[0])
    if current_version > SCHEMA_VERSION:
        raise RuntimeError(f"Unsupported project conversation database version: {current_version}")
    if current_version < 2:
        _migrate_schema_v1_to_v2(connection)
        current_version = 2
    if current_version < 3:
        _migrate_schema_v2_to_v3(connection)
        current_version = 3
    if current_version < 4:
        _migrate_schema_v3_to_v4(connection)
        current_version = 4
    if current_version != SCHEMA_VERSION:
        raise RuntimeError(f"Unsupported project conversation database version: {current_version}")


def _migrate_schema_v1_to_v2(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE conversation_artifacts (
            artifact_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            relative_path TEXT NOT NULL,
            media_type TEXT NOT NULL,
            encoding TEXT,
            size_bytes INTEGER NOT NULL,
            sha256 TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            metadata_json TEXT NOT NULL,
            FOREIGN KEY(session_id) REFERENCES conversation_sessions(session_id) ON DELETE CASCADE
        );
        CREATE INDEX idx_conversation_artifacts_session
            ON conversation_artifacts(session_id, created_at);
        CREATE TABLE conversation_journal (
            event_id INTEGER PRIMARY KEY,
            session_id TEXT,
            run_id TEXT,
            turn_id TEXT,
            tool_call_id TEXT,
            event_type TEXT NOT NULL,
            occurred_at TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            artifact_id TEXT,
            FOREIGN KEY(session_id) REFERENCES conversation_sessions(session_id) ON DELETE CASCADE,
            FOREIGN KEY(artifact_id) REFERENCES conversation_artifacts(artifact_id) ON DELETE SET NULL
        );
        CREATE INDEX idx_conversation_journal_session
            ON conversation_journal(session_id, event_id);
        CREATE INDEX idx_conversation_journal_run
            ON conversation_journal(run_id, event_id);
        CREATE INDEX idx_conversation_journal_tool_call
            ON conversation_journal(tool_call_id, event_id);
        CREATE INDEX idx_conversation_journal_type
            ON conversation_journal(event_type, event_id);
        UPDATE conversation_schema SET version = 2;
        """
    )


def _migrate_schema_v2_to_v3(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE conversation_artifact_payloads (
            artifact_id TEXT PRIMARY KEY,
            compression TEXT NOT NULL,
            stored_size_bytes INTEGER NOT NULL,
            payload_blob BLOB NOT NULL,
            FOREIGN KEY(artifact_id) REFERENCES conversation_artifacts(artifact_id) ON DELETE CASCADE
        );
        UPDATE conversation_schema SET version = 3;
        """
    )


def _migrate_schema_v3_to_v4(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE conversation_session_runtime_states (
            session_id TEXT PRIMARY KEY,
            runtime_status TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(session_id) REFERENCES conversation_sessions(session_id) ON DELETE CASCADE
        );
        CREATE TABLE conversation_session_drafts (
            session_id TEXT PRIMARY KEY,
            draft TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(session_id) REFERENCES conversation_sessions(session_id) ON DELETE CASCADE
        );
        CREATE TABLE conversation_session_references (
            session_id TEXT PRIMARY KEY,
            payload_json TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(session_id) REFERENCES conversation_sessions(session_id) ON DELETE CASCADE
        );
        """
    )
    row = connection.execute(
        "SELECT value_json FROM conversation_meta WHERE key = 'conversation_index'",
    ).fetchone()
    try:
        index = _decode(row[0]) if row is not None else {}
    except (TypeError, ValueError) as error:
        raise RuntimeError("Conversation index cannot be decoded during schema migration.") from error
    if not isinstance(index, dict):
        raise RuntimeError("Conversation index must be an object during schema migration.")
    raw_states = index.get("session_states")
    if raw_states is not None and not isinstance(raw_states, dict):
        raise RuntimeError("Conversation session states must be an object during schema migration.")
    states = raw_states or {}
    live_session_ids = {
        str(session_row[0])
        for session_row in connection.execute(
            "SELECT session_id FROM conversation_sessions"
        ).fetchall()
    }
    for session_id, raw_state in states.items():
        normalized_session_id = str(session_id)
        if normalized_session_id not in live_session_ids:
            continue
        if not isinstance(raw_state, dict):
            raise RuntimeError(
                f"Conversation session state '{normalized_session_id}' must be an object."
            )
        updated_at = str(raw_state.get("updated_at") or "")
        if not updated_at:
            raise RuntimeError(
                f"Conversation session state '{normalized_session_id}' has no update time."
            )
        runtime_updated_at = str(raw_state.get("runtime_updated_at") or updated_at)
        runtime_status = str(raw_state.get("runtime_status") or "idle")
        if runtime_status not in {"idle", "running", "error"}:
            raise RuntimeError(
                f"Conversation session state '{normalized_session_id}' has invalid runtime status."
            )
        draft = str(raw_state.get("draft") or "")
        references = raw_state.get("references")
        if not isinstance(references, list):
            raise RuntimeError(
                f"Conversation session state '{normalized_session_id}' has invalid references."
            )
        connection.execute(
            """
            INSERT INTO conversation_session_runtime_states(
                session_id, runtime_status, updated_at
            ) VALUES (?, ?, ?)
            """,
            (normalized_session_id, runtime_status, runtime_updated_at),
        )
        connection.execute(
            """
            INSERT INTO conversation_session_drafts(session_id, draft, updated_at)
            VALUES (?, ?, ?)
            """,
            (normalized_session_id, draft, updated_at),
        )
        connection.execute(
            """
            INSERT INTO conversation_session_references(
                session_id, payload_json, updated_at
            ) VALUES (?, ?, ?)
            """,
            (normalized_session_id, _encode(references), updated_at),
        )
    active_session_id = index.get("active_session_id")
    pinned = index.get("pinned_session_ids")
    index = {
        "active_session_id": (
            active_session_id
            if isinstance(active_session_id, str) and active_session_id in live_session_ids
            else None
        ),
    }
    index["pinned_session_ids"] = (
        [str(value) for value in pinned if str(value) in live_session_ids]
        if isinstance(pinned, list)
        else []
    )
    _upsert_meta(connection, "conversation_index", index)
    connection.execute("UPDATE conversation_schema SET version = 4")


def _restore_embedded_artifact(row: sqlite3.Row | tuple[Any, ...]) -> dict[str, Any]:
    artifact_id = str(row[0])
    compression = str(row[8])
    stored_payload = bytes(row[10])
    stored_size_bytes = int(row[9])
    if len(stored_payload) != stored_size_bytes:
        raise RuntimeError(f"Artifact {artifact_id} stored size validation failed.")
    if compression != "gzip":
        raise RuntimeError(f"Artifact {artifact_id} uses unsupported compression: {compression}.")
    try:
        content = gzip_decompress(stored_payload)
    except (OSError, EOFError, zlib_error) as error:
        raise RuntimeError(f"Artifact {artifact_id} cannot be decompressed.") from error
    if len(content) != int(row[4]):
        raise RuntimeError(f"Artifact {artifact_id} original size validation failed.")
    if sha256(content).hexdigest() != str(row[5]):
        raise RuntimeError(f"Artifact {artifact_id} SHA-256 validation failed.")
    encoding = str(row[3] or "utf-8")
    try:
        payload = loads(content.decode(encoding))
    except (UnicodeDecodeError, ValueError) as error:
        raise RuntimeError(f"Artifact {artifact_id} does not contain valid JSON.") from error
    return {
        "artifact_id": artifact_id,
        "created_at": row[1],
        "media_type": row[2],
        "encoding": row[3],
        "size_bytes": int(row[4]),
        "stored_size_bytes": stored_size_bytes,
        "sha256": row[5],
        "status": row[6],
        "metadata": _decode(row[7]),
        "compression": compression,
        "content": payload,
    }


def _encode(value: Any) -> str:
    return dumps(value, ensure_ascii=False, separators=(",", ":"))


def _decode(value: str) -> Any:
    return loads(value)


def _upsert_meta(connection: sqlite3.Connection, key: str, value: Any) -> None:
    connection.execute(
        """
        INSERT INTO conversation_meta(key, value_json) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json
        """,
        (key, _encode(value)),
    )


def _increment_conversation_revision(connection: sqlite3.Connection) -> None:
    row = connection.execute(
        "SELECT value_json FROM conversation_meta WHERE key = 'conversation_revision'",
    ).fetchone()
    try:
        current = _decode(row[0]) if row is not None else 0
    except (TypeError, ValueError):
        current = 0
    revision = current + 1 if isinstance(current, int) and current >= 0 else 1
    _upsert_meta(connection, "conversation_revision", revision)
