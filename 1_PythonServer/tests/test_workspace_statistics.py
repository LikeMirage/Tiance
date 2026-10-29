from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.core.errors import BadRequestError, NotFoundError
from app.domain.llm.chat import ChatUsage
from app.domain.tools import ToolCallRecordDraft
from app.domain.usage_statistics import StatisticsMonth
from app.infra.database import ensure_database_schema, database_transaction
from app.repositories.llm.usage_repository import LlmUsageRepository
from app.repositories.tools.tool_call_record_repository import ToolCallRecordRepository
from app.repositories.workspace_activity_repository import WorkspaceActivityRepository
from app.services.workspace_statistics import WorkspaceStatisticsService


@pytest.mark.parametrize(("month", "days"), [("2024-02", 29), ("2025-02", 28), ("2026-04", 30), ("2026-10", 31)])
def test_month_contains_every_natural_day(month, days):
    window = StatisticsMonth.parse(month, "Asia/Shanghai")
    assert len(window.dates) == days
    assert window.day_index(window.bounds[0][0]) == 0
    assert window.day_index(window.bounds[-1][1]) is None


def test_day_boundaries_follow_dst_and_local_midnight():
    window = StatisticsMonth.parse("2026-03", "America/New_York")
    start, end = window.bounds[7]
    assert (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds() == 23 * 3600
    china = StatisticsMonth.parse("2026-10", "Asia/Shanghai")
    assert china.day_index("2026-09-30T16:00:00+00:00") == 0
    assert china.day_index("2026-10-31T16:00:00+00:00") is None


@pytest.mark.parametrize(("month", "zone"), [("2026-13", "UTC"), ("2026-2", "UTC"), ("0000-01", "UTC"), ("2026-01", "no/such/zone")])
def test_invalid_statistics_window_is_rejected(month, zone):
    with pytest.raises(BadRequestError):
        StatisticsMonth.parse(month, zone)


def activity_repo(tmp_path):
    path = tmp_path / "tiance.db"
    ensure_database_schema(path)
    return WorkspaceActivityRepository(path)


def record_runtime(repo, run_id, amount, ended="2026-10-01T00:00:00+00:00", message_id="same-user"):
    repo.record_ai_run_elapsed(run_id=run_id, project_id="project", session_id="session",
                               user_message_id=message_id, elapsed_ms=amount, finished_at=ended)


def test_runtime_deduplicates_run_not_message_and_ranks_before_reading_tasks(tmp_path):
    repo = activity_repo(tmp_path)
    record_runtime(repo, "run-1", 1000)
    record_runtime(repo, "run-1", 999999)  # Repeated settlement must not count twice.
    record_runtime(repo, "run-2", 2000)  # Same message, another real run.
    record_runtime(repo, "run-3", 3000, "2026-10-31T16:00:00+00:00")
    record_runtime(repo, "run-4", 4000)
    conversations = Mock()
    conversations.get_session.return_value = SimpleNamespace(title="任务会话")
    conversations.get_task_excerpt.return_value = "分析订单"
    service = WorkspaceStatisticsService(repo, Mock(), conversations, Mock(), Mock())
    result = service.get_statistics("runtime", "2026-10", "Asia/Shanghai")
    assert result["total"] == 10000
    assert sum(day["value"] for day in result["daily"]) == 7000
    assert [item["id"] for item in result["ranking"]] == ["run-4", "run-3", "run-2"]
    assert result["ranking"][0]["detail"] == "分析订单"
    assert conversations.get_session.call_count == conversations.get_task_excerpt.call_count == 3
    conversations.list_sessions.assert_not_called()
    conversations.list_messages.assert_not_called()
    # Changing month never changes the all-time ranking or cumulative value.
    other = service.get_statistics("runtime", "2026-11", "Asia/Shanghai")
    assert other["ranking"] == result["ranking"]
    assert sum(day["value"] for day in other["daily"]) == 3000
    repo.set_conversation_baseline(0)
    assert repo.sum_ai_run_elapsed_ms() == 10000


def test_unlinked_and_deleted_tasks_keep_duration_without_global_search(tmp_path):
    repo = activity_repo(tmp_path)
    with database_transaction(repo._database_path) as connection:
        connection.execute("INSERT INTO workspace_activity_records(activity_type,source_id,amount,occurred_at) VALUES ('ai_run_elapsed_ms','unlinked',5000,'2026-10-01T00:00:00+00:00')")
    record_runtime(repo, "deleted", 2000)
    conversations = Mock()
    conversations.get_session.side_effect = NotFoundError("removed")
    result = WorkspaceStatisticsService(repo, Mock(), conversations, Mock(), Mock()).get_statistics("runtime", "2026-10", "UTC")
    assert result["total"] == 7000
    assert [item["id"] for item in result["ranking"]] == ["unlinked", "deleted"]
    conversations.get_session.assert_called_once_with("project", "session")
    conversations.get_task_excerpt.assert_not_called()


def test_tokens_use_effective_request_records_and_preserve_first_record_date(tmp_path, monkeypatch):
    repo = LlmUsageRepository(tmp_path)
    def record(request, amount, when):
        monkeypatch.setattr("app.repositories.llm.usage_repository._utc_now", lambda: when)
        repo.record_usage(project_id="p", session_id="s", message_id="assistant", provider_id="provider",
                          model_id="model", request_id=request,
                          usage=ChatUsage(total_tokens=amount))
    record("req-1", 100, "2026-09-30T16:00:00+00:00")
    record("req-1", 150, "2026-11-01T00:00:00+00:00")
    record("req-2", 200, "2026-10-31T16:00:00+00:00")
    result = repo.monthly_statistics(StatisticsMonth.parse("2026-10", "Asia/Shanghai"))
    assert result["total"] == 350
    assert result["daily"][0] == 150
    assert sum(result["daily"]) == 150
    repo.delete_model_usage(provider_id="provider", model_id="model")
    assert repo.monthly_statistics(StatisticsMonth.parse("2026-10", "UTC"))["total"] == 0


def test_model_ranking_keeps_distinct_providers_and_survives_configuration_deletion(tmp_path, monkeypatch):
    from app.repositories.llm.provider_file_store import ProviderFileStore
    from app.repositories.llm.provider_catalog_repository import ProviderCatalogRepository
    from app.repositories.llm.provider_custom_model_repository import ProviderCustomModelRepository
    from app.services.llm.provider.storage_bootstrap import ensure_provider_file_storage

    activity = activity_repo(tmp_path)
    providers_path = tmp_path / "providers"
    ensure_provider_file_storage(providers_path, tmp_path / "tiance.db")
    store = ProviderFileStore(providers_path)
    catalog = ProviderCatalogRepository(store)
    models = ProviderCustomModelRepository(store)
    store.write_provider_file("deepseek", "models.json", {"items": [
        {"modelId": "flash", "displayName": "Flash"},
    ]})
    usage_path = tmp_path / "usage"
    usage = LlmUsageRepository(usage_path)
    def record(request, provider, model, value, date="2026-10-01T00:00:00+00:00"):
        monkeypatch.setattr("app.repositories.llm.usage_repository._utc_now", lambda: date)
        usage.record_usage(project_id="p", session_id="s", message_id=request,
                           provider_id=provider, model_id=model, request_id=request,
                           usage=ChatUsage(total_tokens=value))
    record("a", "deepseek", "flash", 100)
    record("a", "deepseek", "flash", 150)
    record("b", "opencode", "flash", 200, "2026-09-01T00:00:00+00:00")
    record("c", "deepseek", "reasoner", 300)
    record("d", "old-provider", "old-model", 50)
    service = WorkspaceStatisticsService(activity, usage, Mock(), Mock(), catalog)
    result = service.get_statistics("tokens", "2026-10", "UTC")
    assert result["total"] == 700
    assert sum(day["value"] for day in result["daily"]) == 500
    assert [(item["provider_id"], item["model_id"], item["value"]) for item in result["ranking"]] == [
        ("deepseek", "reasoner", 300), ("opencode", "flash", 200), ("deepseek", "flash", 150),
    ]
    assert result["ranking"][0]["label"] == "DeepSeek · reasoner"
    assert len({item["id"] for item in result["ranking"]}) == 3
    assert service.get_statistics("tokens", "2026-09", "UTC")["ranking"] == result["ranking"]
    original_ledger = tuple(usage._store.iter_records())
    assert models.delete_model(provider_id="deepseek", model_id="flash")
    assert service.get_statistics("tokens", "2026-10", "UTC")["ranking"] == result["ranking"]
    assert catalog.delete_entry("deepseek")
    # Read from disk again to verify retention is not merely an old in-memory cache.
    after = WorkspaceStatisticsService(activity, LlmUsageRepository(usage_path), Mock(), Mock(), catalog)
    deleted = after.get_statistics("tokens", "2026-10", "UTC")
    assert deleted["total"] == 700
    assert deleted["ranking"][0]["label"] == "deepseek · reasoner"
    assert deleted["ranking"][2]["label"] == "deepseek · flash"
    assert tuple(LlmUsageRepository(usage_path)._store.iter_records()) == original_ledger


def draft(call_id="call-1", ok=True):
    return ToolCallRecordDraft(tool_project_id="tool", tool_name="search", call_id=call_id,
                              source_project_id="project", session_id="session", arguments_text="{}",
                              result_text="large result" * 1000, ok=ok, error=None, elapsed_ms=100, dynamic=False)


def test_tool_statistics_cache_reads_only_appended_rows_and_rebuilds_on_truncation(tmp_path, monkeypatch):
    import app.repositories.tools.tool_call_record_repository as module
    repo = ToolCallRecordRepository()
    repo.append(tmp_path, draft())
    decode = Mock(wraps=module.json.loads)
    monkeypatch.setattr(module.json, "loads", decode)
    roots = (str(tmp_path),)
    assert len(repo.list_statistics(roots)) == 1
    assert decode.call_count == 1
    assert len(repo.list_statistics(roots)) == 1
    assert decode.call_count == 1
    repo.append(tmp_path, draft("call-2", False))
    stats = repo.list_statistics(roots)
    assert len(stats) == 2
    assert decode.call_count == 2
    assert stats[1].ok is False
    assert not hasattr(stats[0], "result_text")
    repo.records_path(tmp_path).write_text("", encoding="utf-8")
    assert repo.list_statistics(roots) == ()
    repo.list_statistics(())
    assert not repo._statistics_cache


def test_task_excerpt_reads_one_message_not_the_turn(tmp_path):
    # Use the existing public project service to create the session schema correctly.
    from app.infra.projects import ProjectStorage
    from app.repositories.project.project_repository import ProjectRepository
    from app.repositories.project.conversation_repository import ProjectConversationRepository
    from app.services.project.projects import ProjectService
    from app.services.project.project_conversations import ProjectConversationService
    db = tmp_path / "app.db"
    ensure_database_schema(db)
    projects = ProjectRepository(db)
    project = ProjectService(projects, ProjectStorage(tmp_path / "projects")).create_project(name="Statistics")
    conversations = ProjectConversationRepository(projects)
    service = ProjectConversationService(conversations)
    session = service.create_session(project.project_id)
    message = service.append_message(project.project_id, session.session_id, role="user", content="x" * 500)
    assert conversations.get_task_excerpt(project.project_id, session.session_id, message.message_id) == "x" * 160 + "…"


def test_stream_persistence_records_run_location_and_actual_settlement_time(tmp_path):
    from app.domain.llm.chat import ChatCompletionRequest
    from app.domain.project.project_conversation import ProjectConversationMessage
    from app.services.project.project_conversations import ProjectConversationService
    from app.services.project.conversation_stream_persistence import ConversationStreamPersistence
    from app.services.workspace_activity import WorkspaceActivityService
    repo = activity_repo(tmp_path)
    conversations = ProjectConversationService(Mock(), WorkspaceActivityService(repo))
    persistence = ConversationStreamPersistence(conversation_service=conversations, usage_service=None,
        naming_service=None, memory_service=None, background_task_registry=None)
    user = ProjectConversationMessage(message_id="user", session_id="session", role="user", content="task",
        thinking_content="", usage=None, provider_id=None, model_id=None, status="done",
        created_at="2020-01-01T00:00:00+00:00", updated_at="2020-01-01T00:00:00+00:00")
    for run in ("run-a", "run-a", "run-b"):
        request = ChatCompletionRequest(provider_id="provider", model_id="model", project_id="project",
                                        session_id="session", run_id=run, messages=())
        persistence.record_ai_run_elapsed(request, user, None, elapsed_ms=1000)
    assert repo.sum_ai_run_elapsed_ms() == 2000
    with database_transaction(repo._database_path) as connection:
        rows = connection.execute("SELECT * FROM workspace_activity_records").fetchall()
    assert {row["source_id"] for row in rows} == {"run-a", "run-b"}
    assert all(row["project_id"] == "project" and row["session_id"] == "session" and row["user_message_id"] == "user" for row in rows)
    assert all(row["occurred_at"] > user.created_at for row in rows)


def test_statistics_route_validates_kind_and_month_and_returns_daily_data(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.routes import workspace
    service = Mock()
    service.get_statistics.return_value = {"total": 20, "daily": [{"date": "2026-10-01", "value": 10}]}
    monkeypatch.setattr(workspace, "get_workspace_statistics_service", lambda: service)
    app = FastAPI()
    app.include_router(workspace.router, prefix="/api")
    with TestClient(app) as client:
        response = client.get("/api/workspace/statistics/tokens?month=2026-10&timezone=Asia/Shanghai")
        assert response.status_code == 200
        assert response.json()["daily"] == [{"date": "2026-10-01", "value": 10}]
        service.get_statistics.assert_called_once_with("tokens", "2026-10", "Asia/Shanghai")
        assert client.get("/api/workspace/statistics/unknown?month=2026-10").status_code == 422
        assert client.get("/api/workspace/statistics/tokens?month=2026-10-01").status_code == 422
