from contextlib import closing
from dataclasses import asdict
from gzip import compress
from hashlib import sha256
import json
from pathlib import Path
import sqlite3

import pytest

from app.domain.project.project_conversation import ProjectConversationSessionSettings, conversation_session_configuration_hash
from app.repositories.project.conversation_serialization import _session_from_payload
from app.repositories.project.conversation_database import read_connection_for_path
from app.repositories.project.conversation_audit_snapshots import restore_audit_snapshot
from app.repositories.project.conversation_schema import SCHEMA_VERSION


@pytest.mark.parametrize("version", [6, 7])
def test_mixed_legacy_audit_payloads_and_role_hash_are_upgraded(tmp_path, version):
    path = tmp_path / "tiance.db"
    settings = asdict(ProjectConversationSessionSettings())
    # The legacy fixture must not contain settings introduced after v6/v7.
    for key in ("automatic_naming_enabled", "output_limit_action", "output_limit_save_partial", "output_limit_message", "output_limit_max_recoveries"):
        settings.pop(key)
    settings.update(return_cancelled_messages=False, return_user_before_cancelled=True)
    configuration = {"provider_id": "p", "model_id": "m", "reasoning_mode": "high", "settings": settings}
    old_hash = sha256(json.dumps(configuration, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()).hexdigest()
    session = {**configuration, "session_id": "session", "role_project_id": "role", "role_configuration_hash": old_hash}
    expected_hash = conversation_session_configuration_hash(_session_from_payload(session))
    audit = {"request": {"messages": [{"role": "user", "content": "keep"}]}, "response": "preserved"}
    content = json.dumps(audit, ensure_ascii=False, separators=(",", ":")).encode()
    packed = compress(content)
    fixture = Path(__file__).parent / "fixtures/database/project_v6.sql"
    with closing(sqlite3.connect(path)) as db:
        db.executescript(fixture.read_text(encoding="utf-8"))
        db.execute("UPDATE conversation_schema SET version=?", (version,))
        db.execute("INSERT INTO conversation_sessions VALUES ('session',?)", (json.dumps(session),))
        custom = {**session, "session_id": "custom", "role_configuration_hash": "custom-hash"}
        db.execute("INSERT INTO conversation_sessions VALUES ('custom',?)", (json.dumps(custom),))
        db.execute("INSERT INTO conversation_session_events VALUES ('session','model_exchanges',0,?)", (content.decode(),))
        db.execute("INSERT INTO conversation_artifacts VALUES ('artifact','session','model_http_exchange','','application/json','utf-8',?,?,'completed','2026-01-01','{}')",
                   (len(content), sha256(content).hexdigest()))
        db.execute("INSERT INTO conversation_artifact_payloads VALUES ('artifact','gzip',?,?)", (len(packed), packed))
        db.commit()
    with read_connection_for_path(path) as db:
        assert db.execute("SELECT version FROM conversation_schema").fetchone()[0] == SCHEMA_VERSION
        migrated = json.loads(db.execute("SELECT payload_json FROM conversation_sessions WHERE session_id='session'").fetchone()[0])
        assert migrated == {**session, "role_configuration_hash": expected_hash}
        assert json.loads(db.execute("SELECT payload_json FROM conversation_sessions WHERE session_id='custom'").fetchone()[0]) == custom
        manifest = json.loads(db.execute("SELECT payload_json FROM conversation_session_events").fetchone()[0])
        assert restore_audit_snapshot(db, "session", "model_exchanges", manifest) == audit
        assert db.execute("SELECT compression FROM conversation_artifact_payloads").fetchone()[0] == "gzip+audit-manifest-v2"


def test_unknown_configuration_version_rolls_back_all_profile_changes(tmp_path):
    from app.infra.database.schema import ensure_database_schema
    from app.repositories.llm.functional_model_settings_repository import LlmFunctionalModelSettingsRepository
    from app.migrations.functional_settings import upgrade_profiles
    from app.core.errors import BadRequestError
    path = tmp_path / "global.db"
    ensure_database_schema(path)
    repository = LlmFunctionalModelSettingsRepository(path)
    first = repository.save_settings(settings_id="memoryCompression", version=32, settings={"prompt": "keep"})
    future = repository.save_settings(settings_id="naming", version=999, settings={"prompt": "future"})
    with pytest.raises(BadRequestError, match="999"):
        upgrade_profiles(path)
    assert repository.get_settings("memoryCompression") == first
    assert repository.get_settings("naming") == future
    assert not list(tmp_path.glob("*.bak"))
