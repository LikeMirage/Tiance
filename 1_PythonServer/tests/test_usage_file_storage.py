import sqlite3

import pytest

from app.domain.llm.chat import ChatUsage
from app.infra.database import ensure_database_schema, run_database_migrations
from app.infra.database.schema import MIGRATIONS
from app.repositories.llm.usage_repository import LlmUsageRepository
from app.repositories.llm.usage_file_store import UsageFileStore
from app.services.application.usage_file_migration import ensure_usage_file_storage


def test_legacy_usage_is_exported_before_sqlite_tables_are_removed(tmp_path):
    database_path = tmp_path / "tiance.db"
    usage_path = tmp_path / "usage"
    run_database_migrations(
        database_path,
        tuple(migration for migration in MIGRATIONS if migration.version <= 45),
    )
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO llm_usage_records (
                usage_id, project_id, session_id, message_id,
                provider_id, model_id, usage_feature_key,
                prompt_tokens, completion_tokens, total_tokens, reasoning_tokens,
                prompt_cache_hit_tokens, prompt_cache_miss_tokens,
                cost_amount, cost_currency, is_estimated, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "usage_legacy",
                "project-1",
                "session-1",
                "message-1",
                "deepseek",
                "deepseek-v4",
                "main_chat",
                12,
                3,
                15,
                2,
                5,
                7,
                0.25,
                "CNY",
                0,
                "2026-08-01T00:00:00+00:00",
            ),
        )

    ensure_usage_file_storage(database_path, usage_path)
    original_content = (usage_path / "usage_records.jsonl").read_text(encoding="utf-8")
    ensure_usage_file_storage(database_path, usage_path)
    assert (usage_path / "usage_records.jsonl").read_text(encoding="utf-8") == original_content

    ensure_database_schema(database_path)

    with sqlite3.connect(database_path) as connection:
        table_names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    assert "llm_usage_records" not in table_names
    assert "llm_conversation_session_index" not in table_names

    summary = LlmUsageRepository(usage_path).get_session_summary(
        project_id="project-1",
        session_id="session-1",
    )
    assert summary.total.record_count == 1
    assert summary.total.total_tokens == 15
    assert summary.total.prompt_cache_hit_tokens == 5
    assert summary.total.cost_amount == 0.25


def test_usage_event_replay_preserves_upsert_and_model_delete_semantics(tmp_path):
    repository = LlmUsageRepository(tmp_path / "usage")
    repository.record_usage(
        project_id="project-1",
        session_id="session-1",
        message_id="message-1",
        provider_id="provider-1",
        model_id="model-1",
        usage=ChatUsage(prompt_tokens=10, completion_tokens=2, total_tokens=12),
    )
    repository.record_usage(
        project_id="project-1",
        session_id="session-1",
        message_id="message-1",
        provider_id="provider-1",
        model_id="model-1",
        usage=ChatUsage(prompt_tokens=20, completion_tokens=4, total_tokens=24),
    )

    summary = repository.get_session_summary(project_id="project-1", session_id="session-1")
    assert summary.total.record_count == 1
    assert summary.total.total_tokens == 24

    repository.delete_model_usage(provider_id="provider-1", model_id="model-1")
    deleted_summary = repository.get_session_summary(
        project_id="project-1",
        session_id="session-1",
    )
    assert deleted_summary.total.record_count == 0
    assert deleted_summary.total.total_tokens == 0


def _record_usage(repository, message_id="message-1"):
    return repository.record_usage(
        project_id="project-1", session_id="session-1", message_id=message_id,
        provider_id="provider-1", model_id="model-1",
        usage=ChatUsage(prompt_tokens=10, completion_tokens=2, total_tokens=12),
    )


@pytest.mark.parametrize("tail", [b'{"version":1,"record":', b'{"text":"\xe4\xb8', b'\x00\x00'])
def test_startup_recovers_only_torn_tail_and_can_append_again(tmp_path, tail):
    usage_path = tmp_path / "usage"
    _record_usage(LlmUsageRepository(usage_path))
    ledger = usage_path / "usage_records.jsonl"
    healthy = ledger.read_bytes()
    with ledger.open("ab") as output:
        output.write(tail)

    ensure_usage_file_storage(tmp_path / "unused.db", usage_path)

    assert ledger.read_bytes() == healthy
    backups = list(usage_path.glob("*.corrupt-tail"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == tail
    _record_usage(LlmUsageRepository(usage_path), message_id="message-2")
    assert len(UsageFileStore(usage_path).list_records()) == 2
    ensure_usage_file_storage(tmp_path / "unused.db", usage_path)
    assert list(usage_path.glob("*.corrupt-tail")) == backups


def test_complete_event_without_newline_is_preserved_before_next_append(tmp_path):
    _record_usage(LlmUsageRepository(tmp_path))
    ledger = tmp_path / "usage_records.jsonl"
    ledger.write_bytes(ledger.read_bytes().rstrip(b"\r\n"))
    _record_usage(LlmUsageRepository(tmp_path), message_id="message-2")
    assert len(UsageFileStore(tmp_path).list_records()) == 2
    assert not list(tmp_path.glob("*.corrupt-tail"))


@pytest.mark.parametrize("suffix", [b'\n', b'\n{"version":1}\n'])
def test_complete_corrupt_line_is_not_silently_discarded(tmp_path, suffix):
    _record_usage(LlmUsageRepository(tmp_path))
    ledger = tmp_path / "usage_records.jsonl"
    content = ledger.read_bytes() + b'{"partial":' + suffix
    ledger.write_bytes(content)
    with pytest.raises(ValueError, match="line 2"):
        UsageFileStore(tmp_path).list_records()
    assert ledger.read_bytes() == content
    assert not list(tmp_path.glob("*.corrupt-tail"))


@pytest.mark.parametrize("tail", [b'{"version":2}', b'{"version":1,"operation":"unknown"}', b'{"version":1,"operation":"upsert","record":{}}'])
def test_semantically_invalid_tail_is_not_mistaken_for_torn_json(tmp_path, tail):
    ledger = tmp_path / "usage_records.jsonl"
    ledger.write_bytes(tail)
    with pytest.raises(ValueError):
        UsageFileStore(tmp_path).list_records()
    assert ledger.read_bytes() == tail
    assert not list(tmp_path.glob("*.corrupt-tail"))


def test_failure_to_backup_torn_tail_leaves_original_untouched(tmp_path, monkeypatch):
    from pathlib import Path

    _record_usage(LlmUsageRepository(tmp_path))
    ledger = tmp_path / "usage_records.jsonl"
    content = ledger.read_bytes() + b'{"partial":'
    ledger.write_bytes(content)
    real_open = Path.open

    def failing_backup(path, *args, **kwargs):
        if path.name.endswith(".corrupt-tail"):
            raise OSError("backup disk full")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", failing_backup)
    with pytest.raises(OSError, match="disk full"):
        UsageFileStore(tmp_path).list_records()
    assert ledger.read_bytes() == content


def test_single_partial_first_record_does_not_prevent_startup(tmp_path):
    (tmp_path / "usage_records.jsonl").write_bytes(b'{"version":')
    ensure_usage_file_storage(tmp_path / "unused.db", tmp_path)
    _record_usage(LlmUsageRepository(tmp_path))
    assert len(UsageFileStore(tmp_path).list_records()) == 1
