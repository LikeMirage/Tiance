from __future__ import annotations

from contextlib import contextmanager, nullcontext
from gzip import decompress as gzip_decompress
from hashlib import sha256
from json import dumps, loads
from pathlib import Path
import sqlite3
from threading import Lock, RLock, local
from weakref import WeakValueDictionary
from time import monotonic
import logging
from typing import Any, Iterator
from zlib import error as zlib_error

from app.infra.conversation_changes import conversation_changes

from app.repositories.project.conversation_audit_snapshots import (
    collect_unreferenced_audit_blocks,
    restore_audit_snapshot,
    store_audit_snapshot,
    store_prepared_audit_snapshot,
)
from app.repositories.project.conversation_audit_streaming import prepare_audit_snapshot
from app.repositories.project.conversation_schema import (
    SCHEMA_VERSION,
    ensure_current_schema as _ensure_schema,
    validate_current_schema,
)


DATABASE_FILE = "tiance.db"
_thread_state = local()
_database_lock_registry = Lock()
_database_locks: WeakValueDictionary = WeakValueDictionary()
_logger = logging.getLogger(__name__)


def _database_write_lock(path: Path):
    # Only writers to the same database serialize. Reads and other projects
    # remain independent; SQLite still protects against external writers.
    with _database_lock_registry:
        lock = _database_locks.get(path)
        if lock is None:
            lock = RLock()
            _database_locks[path] = lock
        return lock

_initialized_database_paths: set[Path] = set()
# Derived request snapshots are readable documents, not conversation changes.
_DERIVED_SESSION_DOCUMENTS = frozenset({"injection_preview"})


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
    # The common read path must never queue behind an active writer.
    if path in _initialized_database_paths and path.is_file():
        return path
    with _database_write_lock(path):
        if path in _initialized_database_paths and path.is_file():
            return path
        _initialized_database_paths.discard(path)
        connection = _open_connection(path)
        try:
            _ensure_schema(connection)
            connection.commit()
            current_mode = str(connection.execute("PRAGMA journal_mode").fetchone()[0]).lower()
            if current_mode != "wal":
                connection.execute("PRAGMA journal_mode=WAL")
        finally:
            connection.close()
        _initialized_database_paths.add(path)
    return path


@contextmanager
def transaction_for_conversations(conversations_dir: Path) -> Iterator[sqlite3.Connection]:
    with _write_connection(database_path_from_conversations(conversations_dir), track_all=True) as connection:
        yield connection


@contextmanager
def connection_for_path(path: Path) -> Iterator[sqlite3.Connection]:
    with _write_connection(path, track_all=False) as connection:
        yield connection


@contextmanager
def _write_connection(path: Path, *, track_all: bool) -> Iterator[sqlite3.Connection]:
    resolved = path.resolve()
    active = getattr(_thread_state, "transactions", None)
    if active is None:
        active = {}
        _thread_state.transactions = active
    existing = active.get(resolved)
    if existing is not None:
        existing[2] = existing[2] or track_all
        yield existing[0]
        return
    with _database_write_lock(resolved):
        ensure_database(resolved.parent)
        connection = _open_connection(resolved)
        started = monotonic()
        try:
            # BEGIN belongs to the cleanup scope too: a failed BEGIN must not
            # leave an open connection behind. Every nested writer reuses it.
            connection.execute("BEGIN IMMEDIATE")
            active[resolved] = [connection, 1, track_all]
            yield connection
            derived = getattr(_thread_state, "derived_changes", {}).get(id(connection), 0)
            changed = (connection.total_changes > derived if active[resolved][2]
                       else id(connection) in getattr(_thread_state, "visible_connections", set()))
            if changed:
                _increment_conversation_revision(connection)
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            active.pop(resolved, None)
            getattr(_thread_state, "visible_connections", set()).discard(id(connection))
            getattr(_thread_state, "derived_changes", {}).pop(id(connection), None)
            connection.close()
            duration = monotonic() - started
            if duration >= 1:
                _logger.warning("Slow project database write: %.3fs, %s", duration, resolved)
        if changed:
            conversation_changes.publish(resolved)


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
        validate_current_schema(connection)
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


def read_next_session_sequence_number(conversations_dir: Path) -> int:
    """Calculate numbering without materializing session settings or objects."""
    with read_connection_for_path(database_path_from_conversations(conversations_dir)) as connection:
        if connection is None:
            return 1
        row = connection.execute(
            """
            SELECT MAX(CASE WHEN json_type(payload_json, '$.sequence_number') = 'integer'
                       AND typeof(json_extract(payload_json, '$.sequence_number')) = 'integer'
                       THEN json_extract(payload_json, '$.sequence_number') END),
                   COUNT(*),
                   COUNT(CASE WHEN json_type(payload_json, '$.sequence_number') = 'integer'
                         AND typeof(json_extract(payload_json, '$.sequence_number')) = 'integer'
                         THEN 1 END)
            FROM conversation_sessions
            WHERE json_type(payload_json) = 'object'
            """
        ).fetchone()
        if row[1] == row[2]:
            return (int(row[0]) if row[0] is not None else 0) + 1

        raise ValueError("会话序号必须是整数；项目数据未被修改。")


def read_conversation_list_snapshot(
    conversations_dir: Path,
    *,
    summaries_only: bool = False,
    session_id: str | None = None,
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
            f"""
            SELECT key, value_json FROM conversation_meta
            WHERE key IN ('conversation_revision', 'conversation_index'{", 'branch_graph'" if session_id is None else ""})
            """,
        ).fetchall()
        session_payload = "json_remove(payload_json, '$.settings', '$.role_configuration_hash')" if summaries_only else "payload_json"
        session_filter = " WHERE session_id = ?" if session_id is not None else ""
        parameters = (session_id,) if session_id is not None else ()
        session_rows = connection.execute(
            f"SELECT session_id, {session_payload} FROM conversation_sessions{session_filter}",
            parameters,
        ).fetchall()
        draft_value = "''" if summaries_only else "draft.draft"
        reference_value = "'[]'" if summaries_only else "reference.payload_json"
        state_rows = connection.execute(
            f"""
            SELECT session.session_id,
                   runtime.runtime_status, runtime.updated_at,
                   {draft_value}, draft.updated_at,
                   {reference_value}, reference.updated_at
            FROM conversation_sessions AS session
            LEFT JOIN conversation_session_runtime_states AS runtime
                ON runtime.session_id = session.session_id
            LEFT JOIN conversation_session_drafts AS draft
                ON draft.session_id = session.session_id
            LEFT JOIN conversation_session_references AS reference
                ON reference.session_id = session.session_id
            {"WHERE session.session_id = ?" if session_id is not None else ""}
            """,
            parameters,
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
        _mark_visible_connection(connection)
        connection.execute(
            """
            INSERT INTO conversation_sessions(session_id, payload_json) VALUES (?, ?)
            ON CONFLICT(session_id) DO UPDATE SET payload_json = excluded.payload_json
            """,
            (session_id, _encode(payload)),
        )


def delete_session(conversations_dir: Path, session_id: str) -> None:
    with connection_for_path(database_path_from_conversations(conversations_dir)) as connection:
        _mark_visible_connection(connection)
        connection.execute(
            "DELETE FROM conversation_sessions WHERE session_id = ?",
            (session_id,),
        )
        connection.execute(
            "DELETE FROM conversation_meta WHERE key IN (?, ?)",
            (f"messages:{session_id}", f"messages_reset:{session_id}"),
        )
        collect_unreferenced_audit_blocks(connection)


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
    if session_ids is not None and not session_ids:
        return {}
    with read_connection_for_path(database_path_from_conversations(conversations_dir)) as connection:
        if connection is None:
            return {}
        return _read_session_states(connection, session_ids)


def _read_session_states(
    connection: sqlite3.Connection,
    session_ids: set[str] | None,
) -> dict[str, dict[str, Any]]:
    if session_ids is not None and not session_ids:
        return {}
    query = """
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
    parameters: tuple[str, ...] = ()
    if session_ids is not None:
        # A single JSON parameter also handles selections above SQLite's bind limit.
        query += " WHERE session.session_id IN (SELECT value FROM json_each(?))"
        parameters = (dumps(tuple(session_ids), ensure_ascii=False),)
    rows = connection.execute(query, parameters).fetchall()
    return _session_state_payloads_from_rows(rows)


def read_session_index_page(
    conversations_dir: Path, *, page: int, page_size: int,
) -> tuple[int, dict[str, Any]]:
    """Page the diagnostic index in SQLite, loading states only for visible rows."""
    if page < 1 or page_size < 1:
        raise ValueError("Page and page size must be positive")
    path = database_path_from_conversations(conversations_dir).resolve()
    empty = {"active_session_id": None, "pinned_session_ids": [], "sessions": [], "session_states": {}}
    with read_connection_for_path(path) as connection:
        if connection is None:
            return 0, empty
        if path not in getattr(_thread_state, "transactions", {}):
            connection.execute("BEGIN")
        row = connection.execute(
            "SELECT value_json FROM conversation_meta WHERE key = 'conversation_index'",
        ).fetchone()
        raw_index = _decode(row[0]) if row else {}
        index = raw_index if isinstance(raw_index, dict) else {}
        pinned = {value for value in index.get("pinned_session_ids", []) if isinstance(value, str)}
        total = int(connection.execute(
            "SELECT COUNT(*) FROM conversation_sessions WHERE json_type(payload_json) = 'object'",
        ).fetchone()[0])
        last_page = max(1, (total + page_size - 1) // page_size)
        offset = (min(page, last_page) - 1) * page_size
        rows = connection.execute(
            """
            SELECT session_id, payload_json FROM conversation_sessions
            WHERE json_type(payload_json) = 'object'
            ORDER BY session_id IN (SELECT value FROM json_each(?)) DESC,
                     COALESCE(json_extract(payload_json, '$.created_at'), '') DESC,
                     CAST(COALESCE(json_extract(payload_json, '$.sequence_number'), 0) AS INTEGER) DESC,
                     rowid ASC
            LIMIT ? OFFSET ?
            """,
            (_encode(sorted(pinned)), page_size, offset),
        ).fetchall()
        visible_ids = {str(row[0]) for row in rows}
        return total, {
            "active_session_id": index.get("active_session_id"),
            "pinned_session_ids": sorted(pinned & visible_ids),
            "sessions": [_decode(row[1]) for row in rows],
            "session_states": _read_session_states(connection, visible_ids),
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
        _mark_visible_connection(connection)
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
        _mark_visible_connection(connection)
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
        _mark_visible_connection(connection)
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


def read_latest_message_payload(session_dir: Path) -> dict[str, Any] | None:
    with read_connection_for_path(database_path_from_session(session_dir)) as connection:
        if connection is None:
            return None
        row = connection.execute(
            """
            SELECT payload_json FROM conversation_messages
            WHERE session_id = ? ORDER BY ordinal DESC LIMIT 1
            """,
            (session_id_from_session_dir(session_dir),),
        ).fetchone()
    payload = _decode(row[0]) if row is not None else None
    return payload if isinstance(payload, dict) else None


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


def read_task_excerpt(session_dir: Path, message_id: str) -> str | None:
    """Read only the ranked task's display excerpt, never its reply or tool results."""
    with read_connection_for_path(database_path_from_session(session_dir)) as connection:
        if connection is None:
            return None
        row = connection.execute(
            """SELECT substr(json_extract(payload_json, '$.content'), 1, 161)
               FROM conversation_messages WHERE session_id = ? AND message_id = ?""",
            (session_id_from_session_dir(session_dir), message_id),
        ).fetchone()
    if row is None or not row[0]:
        return None
    value = str(row[0])
    return value[:160] + ("…" if len(value) > 160 else "")


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


@contextmanager
def read_conversation_snapshot(conversations_dir: Path):
    path = database_path_from_conversations(conversations_dir).resolve()
    active = getattr(_thread_state, "transactions", None)
    if active is None:
        active = {}
        _thread_state.transactions = active
    if path in active:
        yield
        return
    with read_connection_for_path(path) as connection:
        if connection is None:
            yield
            return
        connection.execute("BEGIN")
        active[path] = [connection, 1]
        try:
            yield
        finally:
            active.pop(path, None)
            connection.rollback()


def read_message_sync_state(session_dir: Path) -> dict[str, int]:
    with read_connection_for_path(database_path_from_session(session_dir)) as connection:
        if connection is None:
            return {"revision": 0, "reset_revision": 0, "project_revision": 0}
        session_id = session_id_from_session_dir(session_dir)
        keys = (f"messages:{session_id}", f"messages_reset:{session_id}", "conversation_revision")
        rows = connection.execute(
            "SELECT key, value_json FROM conversation_meta WHERE key IN (?, ?, ?)", keys,
        ).fetchall()
        values = {key: _decode(value) for key, value in rows}
        return dict(zip(("revision", "reset_revision", "project_revision"),
                        (values.get(key, 0) for key in keys)))


def _mark_visible_connection(connection: sqlite3.Connection) -> None:
    if not hasattr(_thread_state, "visible_connections"):
        _thread_state.visible_connections = set()
    _thread_state.visible_connections.add(id(connection))


def _touch_message_revision(connection: sqlite3.Connection, session_id: str, *, reset: bool = False) -> None:
    _mark_visible_connection(connection)
    key = f"messages:{session_id}"
    row = connection.execute(
        """INSERT INTO conversation_meta(key, value_json) VALUES (?, '1')
        ON CONFLICT(key) DO UPDATE SET value_json = CAST(CAST(value_json AS INTEGER) + 1 AS TEXT)
        RETURNING value_json""", (key,),
    ).fetchone()
    revision = int(row[0])
    if reset:
        _upsert_meta(connection, f"messages_reset:{session_id}", revision)


def append_message_payload(session_dir: Path, message_id: str, payload: dict[str, Any]) -> None:
    session_id = session_id_from_session_dir(session_dir)
    with connection_for_path(database_path_from_session(session_dir)) as connection:
        _touch_message_revision(connection, session_id)
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
        _touch_message_revision(connection, session_id, reset=True)
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
    # Encoding and compression do not require a write transaction. Prepare
    # first, then atomically insert blocks, manifest and its owning event.
    with (
        (prepare_audit_snapshot(payload) if kind == "model_exchanges" else nullcontext()) as prepared,
        connection_for_path(database_path_from_session(session_dir)) as connection,
    ):
        if not connection.in_transaction:
            connection.execute("BEGIN IMMEDIATE")
        stored_payload = (
            store_prepared_audit_snapshot(connection, session_id, kind, prepared)
            if kind == "model_exchanges" else payload
        )
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
            (session_id, kind, ordinal, _encode(stored_payload)),
        )


def read_events(session_dir: Path, kind: str) -> list[dict[str, Any]]:
    with read_connection_for_path(database_path_from_session(session_dir)) as connection:
        if connection is None:
            return []
        if not connection.in_transaction:
            connection.execute("BEGIN")
        rows = connection.execute(
            """
            SELECT payload_json FROM conversation_session_events
            WHERE session_id = ? AND kind = ? ORDER BY ordinal
            """,
            (session_id_from_session_dir(session_dir), kind),
        ).fetchall()
        return [
            _restore_session_event(connection, session_dir, kind, value)
            for row in rows
            if isinstance((value := _decode(row[0])), dict)
        ]


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
        if not connection.in_transaction:
            connection.execute("BEGIN")
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
        return [
            _restore_session_event(connection, session_dir, kind, value)
            for row in rows
            if isinstance((value := _decode(row[0])), dict)
        ]


def replace_events(session_dir: Path, kind: str, payloads: list[dict[str, Any]]) -> None:
    session_id = session_id_from_session_dir(session_dir)
    with connection_for_path(database_path_from_session(session_dir)) as connection:
        if not connection.in_transaction:
            connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "DELETE FROM conversation_session_events WHERE session_id = ? AND kind = ?",
            (session_id_from_session_dir(session_dir), kind),
        )
        if kind == "model_exchanges":
            connection.execute(
                "DELETE FROM conversation_audit_snapshots WHERE session_id = ? AND stream = ?",
                (session_id, kind),
            )
            stored_payloads = [store_audit_snapshot(connection, session_id, kind, payload) for payload in payloads]
            collect_unreferenced_audit_blocks(connection)
        else:
            stored_payloads = payloads
        connection.executemany(
            """
            INSERT INTO conversation_session_events(session_id, kind, ordinal, payload_json)
            VALUES (?, ?, ?, ?)
            """,
            [
                (session_id_from_session_dir(session_dir), kind, ordinal, _encode(payload))
                for ordinal, payload in enumerate(stored_payloads)
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
        before = connection.total_changes
        connection.execute(
            """
            INSERT INTO conversation_session_documents(session_id, kind, payload_json)
            VALUES (?, ?, ?)
            ON CONFLICT(session_id, kind) DO UPDATE SET payload_json = excluded.payload_json
            WHERE conversation_session_documents.payload_json <> excluded.payload_json
            """,
            (session_id_from_session_dir(session_dir), kind, _encode(payload)),
        )
        _mark_document_changes(connection, kind, before)


def delete_document(session_dir: Path, kind: str) -> None:
    with connection_for_path(database_path_from_session(session_dir)) as connection:
        before = connection.total_changes
        connection.execute(
            "DELETE FROM conversation_session_documents WHERE session_id = ? AND kind = ?",
            (session_id_from_session_dir(session_dir), kind),
        )
        _mark_document_changes(connection, kind, before)


def _mark_document_changes(connection: sqlite3.Connection, kind: str, before: int) -> None:
    changes = connection.total_changes - before
    if not changes:
        return
    if kind not in _DERIVED_SESSION_DOCUMENTS:
        _mark_visible_connection(connection)
        return
    # An outer transaction also counts SQL writes. Exclude only this derived
    # write, never real messages/settings/memory written in the same transaction.
    if not hasattr(_thread_state, "derived_changes"):
        _thread_state.derived_changes = {}
    counts = _thread_state.derived_changes
    counts[id(connection)] = counts.get(id(connection), 0) + changes


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


def find_model_exchange_artifact_id(
    workspace_dir: Path,
    *,
    session_id: str,
    run_id: str,
    attempt_index: int,
) -> str | None:
    with read_connection_for_path(database_path_from_workspace(workspace_dir)) as connection:
        if connection is None:
            return None
        rows = connection.execute(
            """
            SELECT payload_json, artifact_id
            FROM conversation_journal
            WHERE session_id = ?
              AND run_id = ?
              AND event_type IN (
                  'model.http_exchange.pending',
                  'model.http_exchange.completed',
                  'model.http_exchange.failed'
              )
              AND artifact_id IS NOT NULL
            ORDER BY event_id DESC
            """,
            (session_id, run_id),
        ).fetchall()
    for row in rows:
        payload = _decode(row[0])
        if int(payload.get("attempt_index") or 1) == max(1, int(attempt_index)):
            return str(row[1])
    return None


def begin_conversation_run(
    workspace_dir: Path,
    *,
    run_id: str,
    session_id: str,
    user_message_id: str,
    started_at: str,
) -> None:
    with connection_for_path(database_path_from_workspace(workspace_dir)) as connection:
        _mark_visible_connection(connection)
        connection.execute(
            """
            INSERT INTO conversation_runs(
                run_id, session_id, user_message_id, status, error_code,
                error_message, attempt_count, started_at, settled_at
            ) VALUES (?, ?, ?, 'running', NULL, NULL, 0, ?, NULL)
            ON CONFLICT(run_id) DO NOTHING
            """,
            (run_id, session_id, user_message_id, started_at),
        )


def settle_conversation_run(
    workspace_dir: Path,
    *,
    run_id: str,
    session_id: str,
    status: str,
    error_code: str | None,
    error_message: str | None,
    attempt_count: int,
    settled_at: str,
) -> bool:
    if status not in {"done", "error", "cancelled"}:
        raise ValueError(f"Unsupported conversation run status: {status}")
    with connection_for_path(database_path_from_workspace(workspace_dir)) as connection:
        has_attempt_failure = (
            status == "error"
            and connection.execute(
                """
                SELECT 1
                FROM conversation_journal
                WHERE session_id = ?
                  AND run_id = ?
                  AND event_type = 'model.request_attempt.failed'
                LIMIT 1
                """,
                (session_id, run_id),
            ).fetchone()
            is not None
        )
        cursor = connection.execute(
            """
            UPDATE conversation_runs
            SET status = ?, error_code = ?, error_message = ?,
                attempt_count = ?, settled_at = ?
            WHERE run_id = ? AND session_id = ? AND status = 'running'
            """,
            (
                status,
                None if has_attempt_failure else error_code,
                None if has_attempt_failure else error_message,
                max(1, int(attempt_count)),
                settled_at,
                run_id,
                session_id,
            ),
        )
        if cursor.rowcount > 0:
            _touch_message_revision(connection, session_id)
        return cursor.rowcount > 0


def read_conversation_run(
    workspace_dir: Path,
    run_id: str,
    *,
    session_id: str,
) -> dict[str, Any] | None:
    with read_connection_for_path(database_path_from_workspace(workspace_dir)) as connection:
        if connection is None:
            return None
        row = connection.execute(
            """
            SELECT run_id, session_id, user_message_id, status, error_code,
                   error_message, attempt_count, started_at, settled_at
            FROM conversation_runs WHERE run_id = ? AND session_id = ?
            """,
            (run_id, session_id),
        ).fetchone()
    return _conversation_run_from_row(row) if row is not None else None


def list_conversation_run_outcomes(
    workspace_dir: Path,
    *,
    session_id: str,
    user_message_ids: tuple[str, ...],
) -> list[dict[str, Any]]:
    if not user_message_ids:
        return []
    placeholders = ",".join("?" for _ in user_message_ids)
    with read_connection_for_path(database_path_from_workspace(workspace_dir)) as connection:
        if connection is None:
            return []
        rows = connection.execute(
            f"""
            SELECT run_id, session_id, user_message_id, status, error_code,
                   error_message, attempt_count, started_at, settled_at
            FROM conversation_runs
            WHERE session_id = ?
              AND user_message_id IN ({placeholders})
              AND status = 'error'
            ORDER BY started_at, run_id
            """,
            (session_id, *user_message_ids),
        ).fetchall()
    return [_conversation_run_from_row(row) for row in rows]


def list_conversation_run_attempt_failures(
    workspace_dir: Path,
    *,
    session_id: str,
    user_message_ids: tuple[str, ...],
) -> list[dict[str, Any]]:
    if not user_message_ids:
        return []
    placeholders = ",".join("?" for _ in user_message_ids)
    with read_connection_for_path(database_path_from_workspace(workspace_dir)) as connection:
        if connection is None:
            return []
        rows = connection.execute(
            f"""
            SELECT journal.event_id,
                   journal.run_id,
                   runs.user_message_id,
                   journal.occurred_at,
                   journal.payload_json
            FROM conversation_journal AS journal
            JOIN conversation_runs AS runs
              ON runs.run_id = journal.run_id
             AND runs.session_id = journal.session_id
            WHERE journal.session_id = ?
              AND runs.user_message_id IN ({placeholders})
              AND journal.event_type = 'model.request_attempt.failed'
            ORDER BY journal.event_id
            """,
            (session_id, *user_message_ids),
        ).fetchall()
    failures: list[dict[str, Any]] = []
    for row in rows:
        payload = _decode(row[4])
        run_id = str(row[1] or "").strip()
        user_message_id = str(row[2] or "").strip()
        if not run_id or not user_message_id:
            continue
        attempt_index = max(1, int(payload.get("attempt_index") or 1))
        attempt_count = max(attempt_index, int(payload.get("attempt_count") or attempt_index))
        failures.append(
            {
                "event_id": int(row[0]),
                "run_id": run_id,
                "session_id": session_id,
                "user_message_id": user_message_id,
                "error_code": payload.get("error_code"),
                "error_message": str(payload.get("error_message") or ""),
                "attempt_index": attempt_index,
                "attempt_count": attempt_count,
                "occurred_at": row[3],
            }
        )
    return failures


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


def complete_artifact_record(
    workspace_dir: Path,
    *,
    artifact_id: str,
    size_bytes: int,
    sha256: str,
    metadata: dict[str, Any],
    payload_blob: bytes,
    compression: str,
) -> None:
    with connection_for_path(database_path_from_workspace(workspace_dir)) as connection:
        cursor = connection.execute(
            """
            UPDATE conversation_artifacts
            SET size_bytes = ?, sha256 = ?, status = 'complete', metadata_json = ?
            WHERE artifact_id = ? AND status = 'pending'
            """,
            (size_bytes, sha256, _encode(metadata), artifact_id),
        )
        if cursor.rowcount != 1:
            raise RuntimeError(f"Pending artifact {artifact_id} no longer exists.")
        connection.execute(
            """
            INSERT INTO conversation_artifact_payloads(
                artifact_id, compression, stored_size_bytes, payload_blob
            ) VALUES (?, ?, ?, ?)
            """,
            (artifact_id, compression, len(payload_blob), payload_blob),
        )


def fail_artifact_record(
    workspace_dir: Path,
    *,
    artifact_id: str,
    metadata: dict[str, Any],
) -> None:
    with connection_for_path(database_path_from_workspace(workspace_dir)) as connection:
        connection.execute(
            """
            UPDATE conversation_artifacts
            SET status = 'failed', metadata_json = ?
            WHERE artifact_id = ? AND status = 'pending'
            """,
            (_encode(metadata), artifact_id),
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
        # Roots, delta chains and shared blocks must belong to one read snapshot.
        if not connection.in_transaction:
            connection.execute("BEGIN")
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
        return [_restore_embedded_artifact(connection, session_id, kind, row) for row in rows]


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


def _conversation_run_from_row(row: sqlite3.Row | tuple[Any, ...]) -> dict[str, Any]:
    return {
        "run_id": str(row[0]),
        "session_id": str(row[1]),
        "user_message_id": str(row[2]),
        "status": str(row[3]),
        "error_code": row[4],
        "error_message": row[5],
        "attempt_count": int(row[6]),
        "started_at": str(row[7]),
        "settled_at": row[8],
    }


def _restore_embedded_artifact(
    connection: sqlite3.Connection,
    session_id: str,
    kind: str,
    row: sqlite3.Row | tuple[Any, ...],
) -> dict[str, Any]:
    artifact_id = str(row[0])
    compression = str(row[8])
    stored_payload = bytes(row[10])
    stored_size_bytes = int(row[9])
    if len(stored_payload) != stored_size_bytes:
        raise RuntimeError(f"Artifact {artifact_id} stored size validation failed.")
    if compression != "gzip+audit-manifest-v2":
        raise RuntimeError(f"Artifact {artifact_id} uses unsupported compression: {compression}.")
    try:
        content = gzip_decompress(stored_payload)
    except (OSError, EOFError, zlib_error) as error:
        raise RuntimeError(f"Artifact {artifact_id} cannot be decompressed.") from error
    encoding = str(row[3] or "utf-8")
    try:
        payload = loads(content.decode(encoding))
    except (UnicodeDecodeError, ValueError) as error:
        raise RuntimeError(f"Artifact {artifact_id} does not contain valid JSON.") from error
    payload = restore_audit_snapshot(connection, session_id, kind, payload)
    content = dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(encoding)
    if len(content) != int(row[4]):
        raise RuntimeError(f"Artifact {artifact_id} original size validation failed.")
    if sha256(content).hexdigest() != str(row[5]):
        raise RuntimeError(f"Artifact {artifact_id} SHA-256 validation failed.")
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


def _restore_session_event(
    connection: sqlite3.Connection,
    session_dir: Path,
    kind: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    if kind == "model_exchanges":
        return restore_audit_snapshot(connection, session_id_from_session_dir(session_dir), kind, payload)
    return payload


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
