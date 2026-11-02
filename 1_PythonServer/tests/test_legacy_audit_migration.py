"""Real historical manifest shapes, including external blobs and mixed v1/v2 data."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from gzip import compress, decompress
from hashlib import sha256
from json import dumps, loads
from pathlib import Path
import sqlite3

import pytest

from app.migrations import attempts
from app.migrations.project_db import v7_to_v8
from app.repositories.project.conversation_audit_delta import json_bytes
from app.repositories.project.conversation_audit_snapshots import restore_audit_snapshot, store_audit_snapshot
from app.repositories.project.conversation_database import ensure_database, read_connection_for_path
from app.repositories.project.conversation_schema import SCHEMA_VERSION

FIXTURES = Path(__file__).parent / "fixtures" / "database"


def _legacy_project(workspace, version=6):
    workspace.mkdir(parents=True, exist_ok=True)
    path = workspace / "tiance.db"
    content = ("保留完整的请求及响应\\n" * 6000).encode("utf-8")
    digest = sha256(content).hexdigest()
    blob = workspace / "conversations" / "audit_blobs" / digest[:2] / f"{digest}.blob"
    blob.parent.mkdir(parents=True)
    blob.write_bytes(content)
    payload = {"request": {"messages": [{"role": "user", "content": content.decode()}]}, "response": "回答"}
    manifest = {"__tiance_audit_manifest__": 1,
                "payload": {"request": {"messages": [{"role": "user", "content": None}]}, "response": "回答"},
                "external_values": [{"path": ["request", "messages", 0, "content"], "sha256": digest,
                                     "size_bytes": len(content), "encoding": "utf-8"}]}
    with closing(sqlite3.connect(path)) as db:
        db.executescript((FIXTURES / f"project_v{min(version, 6)}.sql").read_text(encoding="utf-8"))
        db.execute("UPDATE conversation_schema SET version=?", (version,))
        db.execute("INSERT INTO conversation_sessions VALUES ('session','{}')")
        db.execute("INSERT INTO conversation_meta VALUES ('unrelated','123')")
        db.execute("INSERT INTO conversation_session_events VALUES ('session','model_exchanges',0,?)", (dumps(manifest),))
        db.execute("INSERT INTO conversation_session_events VALUES ('session','model_exchanges',1,?)",
                   (dumps({"__tiance_audit_manifest__": 1, "payload": {"inline": "旧版没有外部块"}, "external_values": []}),))
        db.execute("INSERT INTO conversation_session_events VALUES ('session','model_exchanges',2,?)", (dumps({"plain": "keep"}),))
        if version >= 6:
            current = store_audit_snapshot(db, "session", "model_exchanges", {"current": "keep"})
            db.execute("INSERT INTO conversation_session_events VALUES ('session','model_exchanges',3,?)", (dumps(current),))
        canonical = json_bytes(payload)
        packed = compress(json_bytes(manifest))
        db.execute("INSERT INTO conversation_artifacts VALUES ('artifact','session','model_http_exchange','','application/json','utf-8',?,?,'completed','2026-01-01','{}')",
                   (len(canonical), sha256(canonical).hexdigest()))
        db.execute("INSERT INTO conversation_artifact_payloads VALUES ('artifact','gzip+audit-manifest-v1',?,?)", (len(packed), packed))
        db.commit()
    return path, blob, payload


@pytest.mark.parametrize("version", [5, 6, 7])
def test_real_v1_and_mixed_payloads_convert_losslessly(tmp_path, version):
    path, blob, payload = _legacy_project(tmp_path, version)
    original_blob = blob.read_bytes()
    with read_connection_for_path(path) as db:
        assert db.execute("SELECT version FROM conversation_schema").fetchone()[0] == SCHEMA_VERSION
        assert db.execute("SELECT value_json FROM conversation_meta WHERE key='unrelated'").fetchone()[0] == '123'
        records = [restore_audit_snapshot(db, "session", "model_exchanges", loads(raw))
                   for (raw,) in db.execute("SELECT payload_json FROM conversation_session_events ORDER BY ordinal")]
        expected = [payload, {"inline": "旧版没有外部块"}, {"plain": "keep"}]
        if version >= 6:
            expected.append({"current": "keep"})
        assert records == expected
        mode, packed = db.execute("SELECT compression,payload_blob FROM conversation_artifact_payloads").fetchone()
        assert mode == 'gzip+audit-manifest-v2'
        assert restore_audit_snapshot(db, "session", "model_http_exchange", loads(decompress(packed))) == payload
    assert blob.read_bytes() == original_blob
    backup = next(tmp_path.glob('*.bak'))
    with closing(sqlite3.connect(backup)) as db:
        assert db.execute("SELECT version FROM conversation_schema").fetchone()[0] == version
        assert loads(db.execute("SELECT payload_json FROM conversation_session_events WHERE ordinal=0").fetchone()[0])["__tiance_audit_manifest__"] == 1


@pytest.mark.parametrize("damage", ["missing", "hash", "path", "artifact_hash", "version"])
def test_invalid_v1_rolls_back_and_unchanged_ui_requests_do_not_retry(tmp_path, damage):
    path, blob, _ = _legacy_project(tmp_path)
    original = blob.read_bytes()
    with closing(sqlite3.connect(path)) as db:
        stored = db.execute("SELECT payload_json FROM conversation_session_events WHERE ordinal=0").fetchone()[0]
        if damage == 'missing':
            blob.unlink()
        elif damage == 'hash':
            blob.write_bytes(b'x' * len(original))
        elif damage == 'artifact_hash':
            db.execute("UPDATE conversation_artifacts SET sha256='wrong'")
        else:
            manifest = loads(stored)
            if damage == 'path':
                manifest['external_values'][0]['path'] = ['response']
            else:
                manifest['__tiance_audit_manifest__'] = 99
            db.execute("UPDATE conversation_session_events SET payload_json=? WHERE ordinal=0", (dumps(manifest),))
        db.commit()

    def read(_):
        with pytest.raises(RuntimeError):
            with read_connection_for_path(path):
                pass

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(read, range(16)))
    assert len(list(tmp_path.glob('*.bak'))) == 1
    with closing(sqlite3.connect(path)) as db:
        assert db.execute("SELECT version FROM conversation_schema").fetchone()[0] == 6
        assert db.execute("SELECT COUNT(*) FROM conversation_audit_snapshots").fetchone()[0] == 1
    ensure_database(tmp_path / 'other-project')  # A failed project cannot block other databases.
    if damage in {'missing', 'hash'}:
        blob.write_bytes(original)
    else:
        with closing(sqlite3.connect(path)) as db:
            if damage == 'artifact_hash':
                # The original metadata is available in the pre-migration backup.
                with closing(sqlite3.connect(next(tmp_path.glob('*.bak')))) as old:
                    packed = old.execute("SELECT payload_blob FROM conversation_artifact_payloads").fetchone()[0]
                from app.migrations.project_db.legacy_audit import restore_legacy_payload
                digest = sha256(json_bytes(restore_legacy_payload(db, loads(decompress(packed))))).hexdigest()
                db.execute("UPDATE conversation_artifacts SET sha256=?", (digest,))
            else:
                db.execute("UPDATE conversation_session_events SET payload_json=? WHERE ordinal=0", (stored,))
            db.commit()
    ensure_database(tmp_path)
    assert path.resolve() not in attempts._failures
    with closing(sqlite3.connect(path)) as db:
        assert db.execute("SELECT version FROM conversation_schema").fetchone()[0] == SCHEMA_VERSION


def test_transient_database_or_io_failure_is_not_cached(tmp_path, monkeypatch):
    from app.repositories.project import conversation_database as repository
    _legacy_project(tmp_path)
    original = repository._ensure_schema
    for error in (sqlite3.OperationalError('database is locked'), OSError('backup unavailable')):
        def fail(_connection):
            raise error
        monkeypatch.setattr(repository, '_ensure_schema', fail)
        with pytest.raises(type(error)):
            ensure_database(tmp_path)
        assert (tmp_path / 'tiance.db').resolve() not in attempts._failures
    monkeypatch.setattr(repository, '_ensure_schema', original)
    ensure_database(tmp_path)


def _add_current_audits(db):
    payload = {"request": {"body": "keep current audit " * 8000}, "response": "complete"}
    logical = store_audit_snapshot(db, "session", "model_exchanges", payload)
    db.execute("INSERT INTO conversation_session_events VALUES ('session','model_exchanges',10,?)",
               (dumps(logical),))
    manifest = store_audit_snapshot(db, "session", "model_http_exchange", payload)
    content = json_bytes(payload)
    packed = compress(json_bytes(manifest))
    db.execute("INSERT INTO conversation_artifacts VALUES ('current','session','model_http_exchange','','application/json','utf-8',?,?,'completed','2026-01-02','{}')",
               (len(content), sha256(content).hexdigest()))
    db.execute("INSERT INTO conversation_artifact_payloads VALUES ('current','gzip+audit-manifest-v2',?,?)",
               (len(packed), packed))
    return payload, logical


def _audit_rows(db):
    return {table: db.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall() for table in (
        "conversation_session_events", "conversation_artifacts", "conversation_artifact_payloads",
        "conversation_audit_snapshots", "conversation_audit_blocks", "conversation_audit_snapshot_blocks",
    )}


def _no_audit_conversion(*args, **kwargs):
    raise AssertionError("Current audit records must not be restored or converted during upgrade")


def test_current_audits_are_unchanged_without_full_body_processing(tmp_path, monkeypatch):
    path = tmp_path / "tiance.db"
    with closing(sqlite3.connect(path)) as db:
        db.executescript((FIXTURES / "project_v6.sql").read_text(encoding="utf-8"))
        db.execute("INSERT INTO conversation_sessions VALUES ('session','{}')")
        _add_current_audits(db)
        before = _audit_rows(db)
        db.commit()
    for name in ("restore_audit_snapshot", "store_audit_snapshot", "read_legacy_artifact", "restore_legacy_payload"):
        monkeypatch.setattr(v7_to_v8, name, _no_audit_conversion)
    ensure_database(tmp_path)
    with closing(sqlite3.connect(path)) as db:
        assert db.execute("SELECT version FROM conversation_schema").fetchone()[0] == SCHEMA_VERSION
        assert _audit_rows(db) == before


def test_v5_conversion_is_not_repeated_by_later_migration_steps(tmp_path, monkeypatch):
    path, _blob, _payload = _legacy_project(tmp_path, version=5)
    for name in ("restore_audit_snapshot", "store_audit_snapshot", "read_legacy_artifact", "restore_legacy_payload"):
        monkeypatch.setattr(v7_to_v8, name, _no_audit_conversion)
    ensure_database(tmp_path)
    with closing(sqlite3.connect(path)) as db:
        assert db.execute("SELECT version FROM conversation_schema").fetchone()[0] == SCHEMA_VERSION
        assert db.execute("SELECT COUNT(*) FROM conversation_audit_snapshots").fetchone()[0] == 4


def test_mixed_upgrade_only_restores_records_it_converts(tmp_path, monkeypatch):
    path, _blob, _payload = _legacy_project(tmp_path)
    with closing(sqlite3.connect(path)) as db:
        db.execute("BEGIN")
        _add_current_audits(db)
        before = _audit_rows(db)
        db.commit()
    restored = []
    original_restore = v7_to_v8.restore_audit_snapshot
    def record_restore(connection, session_id, stream, manifest):
        restored.append(manifest["snapshot_id"])
        return original_restore(connection, session_id, stream, manifest)
    monkeypatch.setattr(v7_to_v8, "restore_audit_snapshot", record_restore)
    ensure_database(tmp_path)
    # Three legacy logical records and one legacy HTTP record, each verified once.
    assert len(restored) == 4
    existing_ids = {row[0] for row in before["conversation_audit_snapshots"]}
    assert not existing_ids.intersection(restored)
    with closing(sqlite3.connect(path)) as db:
        after = _audit_rows(db)
        for table in ("conversation_audit_snapshots", "conversation_audit_blocks", "conversation_audit_snapshot_blocks"):
            assert all(row in after[table] for row in before[table])
        assert db.execute("SELECT * FROM conversation_artifact_payloads WHERE artifact_id='current'").fetchone() == before["conversation_artifact_payloads"][-1]


def test_unchanged_current_audit_still_validates_content_when_read(tmp_path):
    path = tmp_path / "tiance.db"
    with closing(sqlite3.connect(path)) as db:
        db.executescript((FIXTURES / "project_v6.sql").read_text(encoding="utf-8"))
        db.execute("INSERT INTO conversation_sessions VALUES ('session','{}')")
        _payload, logical = _add_current_audits(db)
        db.execute("UPDATE conversation_audit_blocks SET payload_blob=?", (compress(b"damaged"),))
        before = _audit_rows(db)
        db.commit()
    ensure_database(tmp_path)
    with read_connection_for_path(path) as db:
        assert _audit_rows(db) == before
        with pytest.raises(RuntimeError, match="integrity"):
            restore_audit_snapshot(db, "session", "model_exchanges", logical)
