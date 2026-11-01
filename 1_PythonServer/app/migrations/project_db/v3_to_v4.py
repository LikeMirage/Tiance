"""Historical project conversion, within the caller transaction."""

import sqlite3
from json import dumps, loads
from app.migrations.sql import execute_script


def upgrade(connection: sqlite3.Connection) -> None:
    execute_script(connection,
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
        index = loads(row[0]) if row is not None else {}
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
            (normalized_session_id, dumps(references, ensure_ascii=False, separators=(",", ":")), updated_at),
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
    connection.execute("INSERT INTO conversation_meta(key,value_json) VALUES ('conversation_index',?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json", (dumps(index, ensure_ascii=False, separators=(",", ":")),))
    connection.execute("UPDATE conversation_schema SET version = 4")
