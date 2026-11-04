"""Upgrade independent snapshots extracted from the pre-cleanup release."""

from contextlib import closing
from gzip import decompress
from json import loads, dumps
from pathlib import Path
import sqlite3

import pytest

from app.infra.database.schema import ensure_database_schema
from app.repositories.project.conversation_database import read_connection_for_path
from app.repositories.project.conversation_schema import SCHEMA_VERSION

FIXTURES = Path(__file__).parent / "fixtures" / "database"
GLOBAL_HISTORY = loads(decompress((FIXTURES / "global_history.json.gz").read_bytes()))


@pytest.mark.parametrize("version", sorted(GLOBAL_HISTORY, key=int))
def test_all_published_global_snapshots_upgrade(tmp_path, version):
    path = tmp_path / "global.db"
    with closing(sqlite3.connect(path)) as db:
        db.executescript(GLOBAL_HISTORY[version])
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "app_metadata" in tables:
            db.execute("INSERT INTO app_metadata VALUES ('user.custom','keep','2026-01-01')")
            db.commit()
    ensure_database_schema(path)
    ensure_database_schema(path)
    with closing(sqlite3.connect(path)) as db:
        assert db.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == 49
        assert db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        assert not db.execute("PRAGMA foreign_key_check").fetchall()
        if "app_metadata" in tables:
            assert db.execute("SELECT value FROM app_metadata WHERE key='user.custom'").fetchone()[0] == "keep"
    assert len(list(tmp_path.glob("*.bak"))) == (0 if version == "49" else 1)


@pytest.mark.parametrize("version", [1, 2, 3, 4])
def test_old_project_versions_preserve_sessions_and_embedded_state(tmp_path, version):
    path = tmp_path / "tiance.db"
    with closing(sqlite3.connect(path)) as db:
        db.executescript((FIXTURES / f"project_v{version}.sql").read_text(encoding="utf-8"))
        db.execute("INSERT INTO conversation_sessions VALUES ('session',?)", (dumps({"title": "keep title"}),))
        db.execute("INSERT INTO conversation_messages VALUES ('session',0,'message',?)", (dumps({"content": "keep content"}),))
        if version < 4:
            db.execute("INSERT INTO conversation_meta VALUES ('conversation_index',?)", (dumps({
                "active_session_id": "session", "pinned_session_ids": ["session"],
                "session_states": {"session": {"draft": "keep draft", "references": [{"path": "keep.txt"}],
                    "runtime_status": "idle", "updated_at": "2026-01-01"}},
            }),))
        db.commit()
    with read_connection_for_path(path) as db:
        assert db.execute("SELECT version FROM conversation_schema").fetchone()[0] == SCHEMA_VERSION
        assert loads(db.execute("SELECT payload_json FROM conversation_messages").fetchone()[0])["content"] == "keep content"
        if version < 4:
            assert db.execute("SELECT draft FROM conversation_session_drafts").fetchone()[0] == "keep draft"
            assert loads(db.execute("SELECT payload_json FROM conversation_session_references").fetchone()[0]) == [{"path": "keep.txt"}]
    assert len(list(tmp_path.glob("*.bak"))) == 1


def test_global_failed_cross_version_upgrade_rolls_back_and_retries(tmp_path, monkeypatch):
    from app.migrations.global_db import history
    path = tmp_path / "global.db"
    with closing(sqlite3.connect(path)) as db:
        db.executescript(GLOBAL_HISTORY["11"])
        before = list(db.iterdump())
    original = history.execute_script
    def fail_late(connection, script):
        if "CREATE TABLE network_settings" in script:
            raise RuntimeError("injected late failure")
        original(connection, script)
    with monkeypatch.context() as patch:
        patch.setattr(history, "execute_script", fail_late)
        with pytest.raises(RuntimeError, match="injected"):
            ensure_database_schema(path)
    with closing(sqlite3.connect(path)) as db:
        assert list(db.iterdump()) == before
    ensure_database_schema(path)


def test_configuration_versions_upgrade_without_losing_custom_values(tmp_path):
    from app.repositories.llm.functional_model_settings_repository import LlmFunctionalModelSettingsRepository
    from app.services.llm.functional_model_settings import LlmFunctionalModelSettingsService
    path = tmp_path / "global.db"
    ensure_database_schema(path)
    repository = LlmFunctionalModelSettingsRepository(path)
    settings = {"prompt": "my exact custom prompt", "modelKey": "custom:model", "modelSource": "dedicated",
                "generation": {"maxOutputTokens": 12345, "temperature": 0.71}, "blockingEnabled": True}
    repository.save_settings(settings_id="memoryCompression", version=31, settings=settings)
    loaded = LlmFunctionalModelSettingsService(repository).get_profile_settings("memoryCompression")
    assert loaded.version == 34
    for key, value in settings.items():
        if key != "generation":
            assert loaded.settings[key] == value
    assert loaded.settings["generation"]["maxOutputTokens"] == 12345
    assert loaded.settings["generation"]["temperature"] == 0.71
    assert len(list(tmp_path.glob("*.bak"))) == 1
    ensure_database_schema(path)
    assert len(list(tmp_path.glob("*.bak"))) == 1


def test_all_known_default_configuration_revisions_follow_current_contract(tmp_path):
    from app.migrations.functional_settings import _history, convert
    from app.domain.llm.functional_model_defaults import get_default_functional_model_profile_settings
    for profile, versions in _history().items():
        current = get_default_functional_model_profile_settings(profile)
        for version, variants in versions.items():
            for source in variants:
                target, migrated = convert(profile, int(version), source)
                assert target == max(map(int, versions))
                if int(version) < target:
                    assert migrated["prompt"] == current["prompt"]
