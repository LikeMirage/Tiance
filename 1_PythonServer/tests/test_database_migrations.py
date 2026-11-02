"""Normal database entry points automatically upgrade without losing stored facts."""

from contextlib import closing
from gzip import compress, decompress
from hashlib import sha256
from json import dumps, loads
from pathlib import Path
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.infra.database.schema import ensure_database_schema
from app.migrations.project_db import v5_to_v6, v6_to_v7
from app.migrations import runner
from app.repositories.project.conversation_audit_snapshots import restore_audit_snapshot
from app.repositories.project.conversation_database import (
    ensure_database, list_embedded_artifacts_range, read_connection_for_path, read_events,
)
from app.repositories.project.conversation_schema import SCHEMA_VERSION

FIXTURES = Path(__file__).parent / "fixtures" / "database"


def _project_v5(path: Path) -> tuple[dict, dict]:
    logical = {"request": {"messages": [{"role": "user", "content": "keep"}]}, "response": "reply"}
    http = {"request": {"body": "keep"}, "response": {"body": "reply"}}
    content = dumps(http, ensure_ascii=False, separators=(",", ":")).encode()
    with closing(sqlite3.connect(path)) as db:
        db.execute("PRAGMA foreign_keys=ON")
        db.executescript((FIXTURES / "project_v5.sql").read_text(encoding="utf-8"))
        db.execute("INSERT INTO conversation_sessions VALUES ('session', '{}')")
        db.execute(
            "INSERT INTO conversation_session_events VALUES ('session', 'model_exchanges', 0, ?)",
            (dumps(logical, ensure_ascii=False, separators=(",", ":")),),
        )
        db.execute(
            """INSERT INTO conversation_artifacts
               (artifact_id,session_id,kind,relative_path,media_type,encoding,
                size_bytes,sha256,status,created_at,metadata_json)
               VALUES ('artifact','session','model_http_exchange','','application/json',
                       'utf-8',?,?,'completed','2026-10-01T00:00:00Z','{}')""",
            (len(content), sha256(content).hexdigest()),
        )
        packed = compress(content)
        db.execute(
            "INSERT INTO conversation_artifact_payloads VALUES ('artifact','gzip',?,?)",
            (len(packed), packed),
        )
        db.commit()
    return logical, http


def _global_v48(path: Path) -> None:
    with closing(sqlite3.connect(path)) as db:
        db.executescript((FIXTURES / "global_v48.sql").read_text(encoding="utf-8"))
        db.execute(
            "INSERT INTO workspace_activity_records VALUES ('run','item',123,'2026-10-01')"
        )
        db.commit()


def test_project_v5_upgrade_converts_both_audit_streams_and_preserves_backup(tmp_path):
    path = tmp_path / "tiance.db"
    logical, http = _project_v5(path)
    session_dir = tmp_path / "conversations" / "sessions" / "session"
    assert read_events(session_dir, "model_exchanges") == [logical]
    backups = list(tmp_path.glob("*.bak"))
    assert len(backups) == 1
    backup = backups[0]
    with closing(sqlite3.connect(backup)) as old:
        assert old.execute("SELECT version FROM conversation_schema").fetchone()[0] == 5
        assert old.execute("SELECT compression FROM conversation_artifact_payloads").fetchone()[0] == "gzip"
    with read_connection_for_path(path) as db:
        assert db is not None
        assert db.execute("SELECT COUNT(*) FROM conversation_sessions").fetchone()[0] == 1
        raw = db.execute("SELECT payload_json FROM conversation_session_events").fetchone()[0]
        assert restore_audit_snapshot(db, "session", "model_exchanges", loads(raw)) == logical
        compression, packed = db.execute(
            "SELECT compression,payload_blob FROM conversation_artifact_payloads"
        ).fetchone()
        assert compression == "gzip+audit-manifest-v2"
        assert restore_audit_snapshot(
            db, "session", "model_http_exchange", loads(decompress(packed))
        ) == http
    assert read_events(session_dir, "model_exchanges") == [logical]
    artifacts = list_embedded_artifacts_range(
        tmp_path, session_id="session", kind="model_http_exchange", offset=0, limit=10,
    )
    assert len(artifacts) == 1 and artifacts[0]["content"] == http
    assert list(tmp_path.glob("*.bak")) == backups


@pytest.mark.parametrize("failure_stage", ["audit", "indexes"])
def test_project_failure_rolls_back_entire_version_chain(tmp_path, monkeypatch, failure_stage):
    path = tmp_path / "tiance.db"
    _project_v5(path)

    def fail(*_args):
        raise RuntimeError("injected audit failure")

    module, name = (
        (v5_to_v6, "store_audit_snapshot") if failure_stage == "audit" else (v6_to_v7, "upgrade")
    )
    original = getattr(module, name)
    monkeypatch.setattr(module, name, fail)
    with pytest.raises(RuntimeError, match="injected"):
        ensure_database(tmp_path)
    with closing(sqlite3.connect(path)) as db:
        assert db.execute("SELECT version FROM conversation_schema").fetchone()[0] == 5
        assert db.execute("SELECT payload_json FROM conversation_session_events").fetchone()[0].startswith('{"request"')
        assert db.execute(
            "SELECT name FROM sqlite_master WHERE name='conversation_audit_snapshots'"
        ).fetchone() is None
    assert len(list(tmp_path.glob("*.bak"))) == 1
    monkeypatch.setattr(module, name, original)
    # Deploying repaired migration code restarts the backend. Unchanged validation
    # failures in a running process must not cause repeated backups on UI refresh.
    from app.migrations import attempts
    monkeypatch.setattr(attempts, "_failures", {})
    ensure_database(tmp_path)
    with closing(sqlite3.connect(path)) as db:
        assert db.execute("SELECT version FROM conversation_schema").fetchone()[0] == SCHEMA_VERSION


def test_global_v48_upgrade_is_additive_and_keeps_legacy_backup(tmp_path):
    path = tmp_path / "global.db"
    _global_v48(path)
    ensure_database_schema(path)
    backups = list(tmp_path.glob("*.bak"))
    assert len(backups) == 1
    backup = backups[0]
    with closing(sqlite3.connect(backup)) as old:
        assert old.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == 48
    with closing(sqlite3.connect(path)) as db:
        assert db.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == 49
        assert db.execute(
            "SELECT activity_type,source_id,amount,project_id,session_id,user_message_id "
            "FROM workspace_activity_records"
        ).fetchone() == ("run", "item", 123, None, None, None)


def test_global_upgrade_preserves_unrelated_retired_project_rows(tmp_path):
    path = tmp_path / "global.db"
    _global_v48(path)
    with closing(sqlite3.connect(path)) as db:
        db.execute("CREATE TABLE projects(project_id TEXT)")
        db.execute("INSERT INTO projects VALUES ('must-not-disappear')")
        db.commit()
    ensure_database_schema(path)
    with closing(sqlite3.connect(path)) as db:
        assert db.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == 49
        assert db.execute("SELECT project_id FROM projects").fetchone()[0] == "must-not-disappear"


def test_concurrent_global_openers_upgrade_once(tmp_path):
    path = tmp_path / "global.db"
    _global_v48(path)
    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(lambda _: ensure_database_schema(path), range(16)))
    with closing(sqlite3.connect(path)) as db:
        assert db.execute("SELECT COUNT(*) FROM schema_migrations WHERE version=49").fetchone()[0] == 1
    assert len(list(tmp_path.glob("*.bak"))) == 1


def test_backup_failure_prevents_project_migration(tmp_path, monkeypatch):
    path = tmp_path / "tiance.db"
    _project_v5(path)

    def fail(*_args):
        raise OSError("backup unavailable")

    monkeypatch.setattr(runner, "backup_database", fail)
    with pytest.raises(OSError, match="backup unavailable"):
        ensure_database(tmp_path)
    with closing(sqlite3.connect(path)) as db:
        assert db.execute("SELECT version FROM conversation_schema").fetchone()[0] == 5
        assert db.execute("SELECT COUNT(*) FROM conversation_session_events").fetchone()[0] == 1
        assert db.execute(
            "SELECT name FROM sqlite_master WHERE name='conversation_audit_snapshots'"
        ).fetchone() is None


@pytest.mark.parametrize("indexes_already_present", [False, True])
def test_project_v6_index_variants_upgrade_to_same_current_schema(tmp_path, indexes_already_present):
    path = tmp_path / "tiance.db"
    with closing(sqlite3.connect(path)) as db:
        db.executescript((FIXTURES / "project_v6.sql").read_text(encoding="utf-8"))
        if indexes_already_present:
            db.execute("""CREATE INDEX IF NOT EXISTS idx_compression_record_id
                ON conversation_session_events(session_id, json_extract(payload_json, '$.compression_id'))
                WHERE kind = 'compressions'""")
            db.execute("""CREATE INDEX IF NOT EXISTS idx_compression_status
                ON conversation_session_events(session_id, json_extract(payload_json, '$.source_type'),
                    json_extract(payload_json, '$.status'), ordinal DESC)
                WHERE kind = 'compressions'""")
        db.commit()
    ensure_database(tmp_path)
    with closing(sqlite3.connect(path)) as db:
        assert db.execute("SELECT version FROM conversation_schema").fetchone()[0] == SCHEMA_VERSION
        assert db.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='index' AND name LIKE 'idx_compression_%'"
        ).fetchone()[0] == 2
    assert len(list(tmp_path.glob("*.bak"))) == 1


def test_project_backup_includes_committed_wal_data(tmp_path):
    path = tmp_path / "tiance.db"
    _project_v5(path)
    with closing(sqlite3.connect(path)) as old:
        old.execute("PRAGMA journal_mode=WAL")
        old.execute("INSERT INTO conversation_meta VALUES ('wal_marker','123')")
        old.commit()
        assert Path(f"{path}-wal").is_file()
        ensure_database(tmp_path)
        backup = next(tmp_path.glob("*.bak"))
        with closing(sqlite3.connect(backup)) as saved:
            assert saved.execute(
                "SELECT value_json FROM conversation_meta WHERE key='wal_marker'"
            ).fetchone()[0] == "123"


def test_independent_project_connections_migrate_once(tmp_path):
    from app.repositories.project.conversation_schema import ensure_current_schema

    path = tmp_path / "tiance.db"
    _project_v5(path)

    def open_database(_):
        with closing(sqlite3.connect(path, timeout=10)) as db:
            ensure_current_schema(db)

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(open_database, range(16)))
    with closing(sqlite3.connect(path)) as db:
        assert db.execute("SELECT version FROM conversation_schema").fetchone()[0] == SCHEMA_VERSION
        assert db.execute("SELECT COUNT(*) FROM conversation_audit_snapshots").fetchone()[0] == 2
    assert len(list(tmp_path.glob("*.bak"))) == 1
