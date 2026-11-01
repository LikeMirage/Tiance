"""Losslessly convert v5 project audit records to the current v6 format."""

from gzip import compress, decompress
from hashlib import sha256
from json import dumps, loads
import sqlite3
from zlib import error as zlib_error

from app.repositories.project.conversation_audit_delta import json_bytes
from app.repositories.project.conversation_audit_snapshots import (
    MANIFEST_KEY,
    restore_audit_snapshot,
    store_audit_snapshot,
)

_SOURCE_TABLES = {
    "conversation_schema", "conversation_meta", "conversation_sessions", "conversation_messages",
    "conversation_session_documents", "conversation_session_events", "conversation_project_events",
    "conversation_artifacts", "conversation_journal", "conversation_artifact_payloads",
    "conversation_session_runtime_states", "conversation_session_drafts",
    "conversation_session_references", "conversation_runs",
}

# A migration describes its destination version, independent of future fresh-schema changes.
_AUDIT_SCHEMA_V6 = (
    """CREATE TABLE conversation_audit_blocks (
        digest TEXT PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('text', 'json')),
        size_bytes INTEGER NOT NULL, payload_blob BLOB NOT NULL)""",
    """CREATE TABLE conversation_audit_snapshots (
        snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,
        stream TEXT NOT NULL, base_snapshot_id INTEGER, depth INTEGER NOT NULL,
        payload_sha256 TEXT NOT NULL, payload_size_bytes INTEGER NOT NULL,
        tree_sha256 TEXT NOT NULL, payload_blob BLOB NOT NULL,
        FOREIGN KEY(session_id) REFERENCES conversation_sessions(session_id) ON DELETE CASCADE,
        FOREIGN KEY(base_snapshot_id) REFERENCES conversation_audit_snapshots(snapshot_id))""",
    """CREATE TABLE conversation_audit_snapshot_blocks (
        snapshot_id INTEGER NOT NULL, digest TEXT NOT NULL, PRIMARY KEY(snapshot_id, digest),
        FOREIGN KEY(snapshot_id) REFERENCES conversation_audit_snapshots(snapshot_id) ON DELETE CASCADE,
        FOREIGN KEY(digest) REFERENCES conversation_audit_blocks(digest))""",
    "CREATE INDEX idx_audit_snapshots_stream ON conversation_audit_snapshots(session_id, stream, snapshot_id)",
    "CREATE INDEX idx_audit_snapshots_base ON conversation_audit_snapshots(base_snapshot_id)",
    "CREATE INDEX idx_audit_snapshot_blocks_digest ON conversation_audit_snapshot_blocks(digest)",
)


def inspect_v5(connection: sqlite3.Connection) -> tuple[int, int]:
    tables = {
        row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    if any(name.startswith("conversation_audit_") for name in tables) or not _SOURCE_TABLES <= tables:
        raise RuntimeError("Unsupported project v5 structure; the original database was preserved.")
    event_count = 0
    for (raw,) in connection.execute(
        "SELECT payload_json FROM conversation_session_events "
        "WHERE kind='model_exchanges' ORDER BY session_id, ordinal"
    ):
        payload = loads(raw)
        if not isinstance(payload, dict) or MANIFEST_KEY in payload:
            raise RuntimeError("Project v5 contains an unsupported logical audit record.")
        event_count += 1
    artifact_count = 0
    for row in connection.execute(
        """SELECT a.artifact_id, a.encoding, a.size_bytes, a.sha256,
                  p.compression, p.stored_size_bytes, p.payload_blob
           FROM conversation_artifacts a JOIN conversation_artifact_payloads p
             ON p.artifact_id=a.artifact_id ORDER BY a.session_id, a.created_at, a.artifact_id"""
    ):
        _read_legacy_artifact(row)
        artifact_count += 1
    return event_count, artifact_count


def upgrade(connection: sqlite3.Connection) -> tuple[int, int]:
    expected = inspect_v5(connection)
    for statement in _AUDIT_SCHEMA_V6:
        connection.execute(statement)
    event_count = 0
    for session_id, ordinal, raw in connection.execute(
        "SELECT session_id, ordinal, payload_json FROM conversation_session_events "
        "WHERE kind='model_exchanges' ORDER BY session_id, ordinal"
    ):
        payload = loads(raw)
        manifest = store_audit_snapshot(connection, session_id, "model_exchanges", payload)
        restored = restore_audit_snapshot(connection, session_id, "model_exchanges", manifest)
        if json_bytes(restored) != json_bytes(payload):
            raise RuntimeError("Logical audit changed during v5 conversion.")
        connection.execute(
            "UPDATE conversation_session_events SET payload_json=? "
            "WHERE session_id=? AND kind='model_exchanges' AND ordinal=?",
            (dumps(manifest, ensure_ascii=False, separators=(",", ":")), session_id, ordinal),
        )
        event_count += 1
    artifact_count = 0
    for row in connection.execute(
        """SELECT a.artifact_id, a.session_id, a.kind, a.encoding, a.size_bytes,
                  a.sha256, p.compression, p.stored_size_bytes, p.payload_blob
           FROM conversation_artifacts a JOIN conversation_artifact_payloads p
             ON p.artifact_id=a.artifact_id ORDER BY a.session_id, a.created_at, a.artifact_id"""
    ):
        artifact_id, session_id, kind, encoding, size, digest, compression, stored_size, blob = row
        payload = _read_legacy_artifact((artifact_id, encoding, size, digest, compression, stored_size, blob))
        manifest = store_audit_snapshot(connection, session_id, kind, payload)
        restored = restore_audit_snapshot(connection, session_id, kind, manifest)
        content = dumps(restored, ensure_ascii=False, separators=(",", ":")).encode(encoding or "utf-8")
        if len(content) != size or sha256(content).hexdigest() != digest:
            raise RuntimeError(f"HTTP audit {artifact_id} changed during v5 conversion.")
        packed = compress(json_bytes(manifest), mtime=0)
        connection.execute(
            "UPDATE conversation_artifact_payloads "
            "SET compression='gzip+audit-manifest-v2', stored_size_bytes=?, payload_blob=? "
            "WHERE artifact_id=?",
            (len(packed), packed, artifact_id),
        )
        artifact_count += 1
    if (event_count, artifact_count) != expected:
        raise RuntimeError("Project audit row counts changed during v5 conversion.")
    connection.execute("UPDATE conversation_schema SET version=6 WHERE version=5")
    return expected


def _read_legacy_artifact(row: tuple) -> dict:
    artifact_id, encoding, size, digest, compression, stored_size, blob = row
    if compression != "gzip" or len(blob) != stored_size:
        raise RuntimeError(f"HTTP audit {artifact_id} has an unsupported legacy payload.")
    try:
        content = decompress(blob)
        payload = loads(content.decode(encoding or "utf-8"))
    except (OSError, EOFError, UnicodeError, ValueError, zlib_error) as exc:
        raise RuntimeError(f"HTTP audit {artifact_id} cannot be decoded.") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"HTTP audit {artifact_id} is not a JSON object.")
    canonical = dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(encoding or "utf-8")
    if content != canonical or len(content) != size or sha256(content).hexdigest() != digest:
        raise RuntimeError(f"HTTP audit {artifact_id} failed original integrity checks.")
    return payload
