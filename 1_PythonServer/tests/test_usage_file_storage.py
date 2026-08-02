import sqlite3

from app.domain.llm.chat import ChatUsage
from app.infra.database import ensure_database_schema, run_database_migrations
from app.infra.database.schema import MIGRATIONS
from app.repositories.llm.usage_repository import LlmUsageRepository
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
