"""Normalize remaining legacy payloads and persist verified role-hash repairs."""

from gzip import compress
from hashlib import sha256
from json import dumps, loads
import sqlite3

from app.migrations.project_db.role_hash import migrated_role_hash
from app.migrations.project_db.legacy_audit import read_legacy_artifact, restore_legacy_payload
from app.repositories.project.conversation_audit_delta import json_bytes
from app.repositories.project.conversation_audit_snapshots import MANIFEST_KEY, restore_audit_snapshot, store_audit_snapshot


def upgrade(connection: sqlite3.Connection) -> None:
    for session_id, ordinal, raw in connection.execute(
        "SELECT session_id,ordinal,payload_json FROM conversation_session_events WHERE kind='model_exchanges' ORDER BY session_id,ordinal"
    ):
        payload = loads(raw)
        if not isinstance(payload, dict):
            raise RuntimeError("Legacy logical audit must be a JSON object.")
        if payload.get(MANIFEST_KEY) == 2:
            # Already at the destination format, including records converted by
            # v5 -> v6 in this same transaction. Leave their snapshots untouched;
            # normal readers validate their content when it is requested.
            continue
        payload = restore_legacy_payload(connection, payload)
        manifest = store_audit_snapshot(connection, session_id, "model_exchanges", payload)
        if json_bytes(restore_audit_snapshot(connection, session_id, "model_exchanges", manifest)) != json_bytes(payload):
            raise RuntimeError("Logical audit changed during conversion.")
        connection.execute("UPDATE conversation_session_events SET payload_json=? WHERE session_id=? AND kind='model_exchanges' AND ordinal=?",
                           (dumps(manifest, separators=(",", ":")), session_id, ordinal))
    for row in connection.execute(
        "SELECT a.artifact_id,a.session_id,a.kind,a.encoding,a.size_bytes,a.sha256,p.compression,p.stored_size_bytes,p.payload_blob "
        "FROM conversation_artifacts a JOIN conversation_artifact_payloads p USING(artifact_id) "
        "WHERE p.compression != 'gzip+audit-manifest-v2' ORDER BY a.session_id,a.created_at,a.artifact_id"
    ):
        identifier, session_id, kind, encoding, size, digest, compression, stored_size, blob = row
        payload = read_legacy_artifact(connection, (identifier, encoding, size, digest, compression, stored_size, blob))
        manifest = store_audit_snapshot(connection, session_id, kind, payload)
        payload = restore_audit_snapshot(connection, session_id, kind, manifest)
        content = dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(encoding or "utf-8")
        if len(content) != size or sha256(content).hexdigest() != digest:
            raise RuntimeError(f"Artifact {identifier} failed original content verification.")
        packed = compress(json_bytes(manifest), mtime=0)
        connection.execute("UPDATE conversation_artifact_payloads SET compression='gzip+audit-manifest-v2',stored_size_bytes=?,payload_blob=? WHERE artifact_id=?",
                           (len(packed), packed, identifier))
    for session_id, raw in connection.execute("SELECT session_id,payload_json FROM conversation_sessions"):
        payload = loads(raw)
        if not isinstance(payload, dict):
            raise RuntimeError("Legacy session must be a JSON object.")
        if not payload.get("role_project_id") or not payload.get("role_configuration_hash"):
            continue
        migrated = migrated_role_hash(payload)
        if migrated != payload["role_configuration_hash"]:
            payload["role_configuration_hash"] = migrated
            connection.execute("UPDATE conversation_sessions SET payload_json=? WHERE session_id=?",
                               (dumps(payload, ensure_ascii=False, separators=(",", ":")), session_id))
    connection.execute("UPDATE conversation_schema SET version=8 WHERE version=7")
