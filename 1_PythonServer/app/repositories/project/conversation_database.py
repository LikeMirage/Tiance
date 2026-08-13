from __future__ import annotations

from contextlib import contextmanager
from json import dumps, loads
from pathlib import Path
import sqlite3
from threading import local
from typing import Any, Iterator


DATABASE_FILE = "tiance.db"
SCHEMA_VERSION = 1
_thread_state = local()


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
    path = database_path_from_workspace(workspace_dir)
    connection = _open_connection(path)
    try:
        _ensure_schema(connection)
        connection.commit()
    finally:
        connection.close()
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

    connection = _open_connection(path)
    _ensure_schema(connection)
    connection.execute("BEGIN IMMEDIATE")
    active[path] = [connection, 1]
    try:
        yield connection
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
    connection = _open_connection(resolved)
    try:
        _ensure_schema(connection)
        yield connection
        connection.commit()
    finally:
        connection.close()


def read_meta(conversations_dir: Path, key: str, default: Any = None) -> Any:
    with connection_for_path(database_path_from_conversations(conversations_dir)) as connection:
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
    with connection_for_path(database_path_from_conversations(conversations_dir)) as connection:
        row = connection.execute(
            "SELECT payload_json FROM conversation_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
    value = _decode(row[0]) if row is not None else None
    return value if isinstance(value, dict) else None


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
    with connection_for_path(database_path_from_conversations(conversations_dir)) as connection:
        row = connection.execute(
            "SELECT 1 FROM conversation_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
    return row is not None


def list_message_payloads(session_dir: Path) -> list[dict[str, Any]]:
    session_id = session_id_from_session_dir(session_dir)
    with connection_for_path(database_path_from_session(session_dir)) as connection:
        rows = connection.execute(
            """
            SELECT payload_json FROM conversation_messages
            WHERE session_id = ? ORDER BY ordinal
            """,
            (session_id,),
        ).fetchall()
    return [value for row in rows if isinstance((value := _decode(row[0])), dict)]


def count_message_payloads(session_dir: Path) -> int:
    with connection_for_path(database_path_from_session(session_dir)) as connection:
        row = connection.execute(
            "SELECT COUNT(*) FROM conversation_messages WHERE session_id = ?",
            (session_id_from_session_dir(session_dir),),
        ).fetchone()
    return int(row[0]) if row is not None else 0


def find_message_ordinal(session_dir: Path, message_id: str) -> int | None:
    with connection_for_path(database_path_from_session(session_dir)) as connection:
        row = connection.execute(
            """
            SELECT ordinal FROM conversation_messages
            WHERE session_id = ? AND message_id = ?
            """,
            (session_id_from_session_dir(session_dir), message_id),
        ).fetchone()
    return int(row[0]) if row is not None else None


def list_message_payloads_range(
    session_dir: Path,
    *,
    start_ordinal: int,
    end_ordinal: int,
) -> list[dict[str, Any]]:
    with connection_for_path(database_path_from_session(session_dir)) as connection:
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
    with connection_for_path(database_path_from_session(session_dir)) as connection:
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
    with connection_for_path(database_path_from_session(session_dir)) as connection:
        rows = connection.execute(
            """
            SELECT payload_json FROM conversation_session_events
            WHERE session_id = ? AND kind = ? ORDER BY ordinal
            """,
            (session_id_from_session_dir(session_dir), kind),
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
    with connection_for_path(database_path_from_session(session_dir)) as connection:
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
    with connection_for_path(database_path_from_workspace(workspace_dir)) as connection:
        rows = connection.execute(
            "SELECT payload_json FROM conversation_project_events WHERE kind = ? ORDER BY ordinal",
            (kind,),
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


def journal_mode(database_path: Path) -> str:
    with connection_for_path(database_path) as connection:
        return str(connection.execute("PRAGMA journal_mode").fetchone()[0]).lower()


def _open_connection(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10.0)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=NORMAL")
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=10000")
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
        connection.execute("INSERT INTO conversation_schema(version) VALUES (?)", (SCHEMA_VERSION,))
    elif int(row[0]) != SCHEMA_VERSION:
        raise RuntimeError(f"Unsupported project conversation database version: {row[0]}")


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
