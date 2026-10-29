"""Indexed access to compression records in the existing session event table.

Callers keep the conversation write transaction around multi-record operations.
History listing and branch copying still use the ordinary event stream.
"""
from pathlib import Path
from typing import Any

from app.core.errors import ConflictError
from app.repositories.project.conversation_database import (
    _decode, _encode, append_event, connection_for_path, database_path_from_session,
    read_connection_for_path, session_id_from_session_dir,
)


def append_compression_record(session_dir: Path, payload: dict[str, Any]) -> None:
    append_event(session_dir, "compressions", payload)


def read_compression_record(session_dir: Path, compression_id: str) -> dict[str, Any]:
    with read_connection_for_path(database_path_from_session(session_dir)) as connection:
        row = _find_record(connection, session_dir, compression_id)
        return _decode(row[1])


def update_compression_record(session_dir: Path, compression_id: str, fields: dict[str, Any]) -> None:
    with connection_for_path(database_path_from_session(session_dir)) as connection:
        if not connection.in_transaction:
            connection.execute("BEGIN IMMEDIATE")
        row = _find_record(connection, session_dir, compression_id)
        payload = _encode({**_decode(row[1]), **fields})
        connection.execute(
            """UPDATE conversation_session_events SET payload_json = ?
            WHERE session_id = ? AND kind = 'compressions' AND ordinal = ? AND payload_json <> ?""",
            (payload, session_id_from_session_dir(session_dir), row[0], payload),
        )


def _find_record(connection, session_dir: Path, compression_id: str):
    rows = [] if connection is None else connection.execute(
        """SELECT ordinal, payload_json FROM conversation_session_events
        WHERE session_id = ? AND kind = 'compressions'
          AND json_extract(payload_json, '$.compression_id') = ? LIMIT 2""",
        (session_id_from_session_dir(session_dir), compression_id),
    ).fetchall()
    if len(rows) != 1:
        raise ConflictError("记忆压缩记录不存在或 ID 重复，未写入结果。")
    return rows[0]


def active_compression_records(session_dir: Path) -> list[dict[str, Any]]:
    with read_connection_for_path(database_path_from_session(session_dir)) as connection:
        if connection is None:
            return []
        rows = connection.execute(
            """SELECT payload_json FROM conversation_session_events
            WHERE session_id = ? AND kind = 'compressions'
              AND json_extract(payload_json, '$.source_type') = 'conversation_context'
              AND json_extract(payload_json, '$.status') IN ('pending', 'running')
            ORDER BY ordinal""", (session_id_from_session_dir(session_dir),),
        ).fetchall()
        return [_decode(row[0]) for row in rows]


def latest_completed_compression_id(session_dir: Path) -> str | None:
    with read_connection_for_path(database_path_from_session(session_dir)) as connection:
        if connection is None:
            return None
        row = connection.execute(
            """SELECT json_extract(payload_json, '$.compression_id') FROM conversation_session_events
            WHERE session_id = ? AND kind = 'compressions'
              AND json_extract(payload_json, '$.source_type') = 'conversation_context'
              AND json_extract(payload_json, '$.status') = 'completed'
              AND json_type(payload_json, '$.compression_id') = 'text'
            ORDER BY ordinal DESC LIMIT 1""", (session_id_from_session_dir(session_dir),),
        ).fetchone()
        return str(row[0]) if row else None
