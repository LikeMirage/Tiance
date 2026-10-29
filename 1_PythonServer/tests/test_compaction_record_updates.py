from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from app.domain.project import Project
from app.repositories.project import conversation_database as db
from app.repositories.project import conversation_compaction_repository as compaction
from app.repositories.project.conversation_compression_records import (
    active_compression_records, append_compression_record, latest_completed_compression_id,
    read_compression_record, update_compression_record,
)
from app.repositories.project.conversation_memory_repository import ProjectConversationMemoryRepository
from app.repositories.project.conversation_repository import ProjectConversationRepository


@pytest.fixture
def setup(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    project = Project(project_id="p", name="test", root_path=str(root), is_default=False,
        sort_order=0, created_at="now", updated_at="now")
    projects = SimpleNamespace(get_project=lambda pid: project if pid == "p" else None)
    repository = ProjectConversationRepository(projects)
    source = repository.create_session("p", title="source", provider_id=None, model_id=None, reasoning_mode=None)
    message = repository.append_message("p", source.session_id, role="user", content="history")
    source_path = repository.message_sync_target("p", source.session_id)
    records = [{"compression_id": f"cmp_{i}", "status": "completed", "source_type": "conversation_context",
                "source_message_ids": [message.message_id], "result": {"handoff": "summary", "items": []}}
               for i in range(100)]
    db.replace_events(source_path, "compressions", records)
    tasks = compaction.ProjectConversationCompactionRepository(projects)
    def create(compression_id="current"):
        return tasks.create_task("p", source.session_id, compression_id=compression_id,
            source_boundary_message_id=message.message_id, snapshot_boundary_message_id=message.message_id,
            source_message_ids=(message.message_id,), newly_covered_message_ids=(message.message_id,),
            supersedes_compression_id="cmp_99", target_provider_id="provider", target_model_id="model",
            target_reasoning_mode=None, target_settings=source.settings, mode="session", trigger={},
            configuration_fingerprint="test")
    return SimpleNamespace(repository=repository, source=source, source_path=source_path, projects=projects,
        tasks=tasks, create=create, records=records)


@contextmanager
def observe_events(source_path):
    with db.transaction_for_conversations(source_path.parent.parent) as connection:
        connection.execute("CREATE TEMP TABLE observed(action TEXT, session_id TEXT, ordinal INTEGER)")
        for operation, alias in (("INSERT", "NEW"), ("UPDATE", "NEW"), ("DELETE", "OLD")):
            connection.execute(f"""CREATE TEMP TRIGGER observed_{operation} AFTER {operation}
                ON conversation_session_events WHEN {alias}.kind = 'compressions'
                BEGIN INSERT INTO observed VALUES ('{operation}', {alias}.session_id, {alias}.ordinal); END""")
        yield connection


def counts(connection, session_id):
    return dict(connection.execute("SELECT action, COUNT(*) FROM observed WHERE session_id=? GROUP BY action",
                                   (session_id,)).fetchall())


def test_create_appends_one_source_record_and_running_updates_one_row(setup):
    with observe_events(setup.source_path) as connection:
        created = setup.create()
        assert counts(connection, setup.source.session_id) == {"INSERT": 1}
        connection.execute("DELETE FROM observed")
        setup.tasks.mark_task_running("p", created.session.session_id)
        assert counts(connection, setup.source.session_id) == {"UPDATE": 1}
        assert read_compression_record(setup.source_path, "current")["status"] == "running"
        connection.execute("DELETE FROM observed")
        setup.tasks.mark_task_running("p", created.session.session_id)
        assert counts(connection, setup.source.session_id) == {}
    assert db.read_events(setup.source_path, "compressions")[:100] == setup.records


def test_completion_updates_source_appends_function_and_repeated_submit_is_idempotent(setup):
    created = setup.create()
    function_id = created.session.session_id
    result = {"items": [{"content": "complete summary", "keywords": ["summary"]}], "handoff": "next"}
    with observe_events(setup.source_path) as connection:
        completed = setup.tasks.submit_result("p", function_id, result=result, token_measurements=(100, "test", 10, "test"))
        assert completed["status"] == "completed"
        assert counts(connection, setup.source.session_id) == {"UPDATE": 1}
        assert counts(connection, function_id) == {"INSERT": 1}
        connection.execute("DELETE FROM observed")
        assert setup.tasks.submit_result("p", function_id, result=result, token_measurements=(100, "test", 10, "test")) == completed
        assert connection.execute("SELECT COUNT(*) FROM observed").fetchone()[0] == 0
    assert db.read_events(setup.source_path, "compressions")[:100] == setup.records


def test_failure_and_stale_recovery_only_update_the_affected_record(setup):
    created = setup.create()
    with observe_events(setup.source_path) as connection:
        setup.tasks.mark_task_failed("p", created.session.session_id, stage="test", reason="test", message="failed")
        assert counts(connection, setup.source.session_id) == {"UPDATE": 1}
    second = setup.create("second")
    with db.transaction_for_conversations(setup.source_path.parent.parent):
        update_compression_record(setup.source_path, "second", {"created_at": "2000-01-01T00:00:00+00:00"})
    with observe_events(setup.source_path) as connection:
        setup.tasks.request_manual_compaction("p", setup.source.session_id,
            newly_covered_token_count=100, protected_tail_token_count=10)
        assert counts(connection, setup.source.session_id) == {"UPDATE": 1}
    assert setup.tasks.read_task("p", second.session.session_id)["status"] == "failed"
    assert db.read_events(setup.source_path, "compressions")[:100] == setup.records


@pytest.mark.parametrize("operation", ["running", "failed", "completed"])
def test_task_document_failure_rolls_back_compression_changes(setup, monkeypatch, operation):
    created = setup.create()
    function_id = created.session.session_id
    function_path = setup.repository.message_sync_target("p", function_id)
    source_before = db.read_events(setup.source_path, "compressions")
    function_before = db.read_events(function_path, "compressions")
    task_before = setup.tasks.read_task("p", function_id)
    def fail(*args, **kwargs):
        raise OSError("injected task save failure")
    monkeypatch.setattr(compaction, "_write_json_object", fail)
    with pytest.raises(OSError):
        if operation == "running":
            setup.tasks.mark_task_running("p", function_id)
        elif operation == "failed":
            setup.tasks.mark_task_failed("p", function_id, stage="test", reason="test", message="failed")
        else:
            setup.tasks.submit_result("p", function_id, result={"items": [], "handoff": "done"}, token_measurements=(100, "test", 10, "test"))
    assert db.read_events(setup.source_path, "compressions") == source_before
    assert db.read_events(function_path, "compressions") == function_before
    assert setup.tasks.read_task("p", function_id) == task_before


def test_memory_repository_append_uses_one_insert(setup, tmp_path):
    repository = ProjectConversationMemoryRepository(setup.projects, global_memory_root=tmp_path / "memory")
    with observe_events(setup.source_path) as connection:
        repository.append_compression("p", setup.source.session_id, {"compression_id": "new", "result": {}})
        assert counts(connection, setup.source.session_id) == {"INSERT": 1}


def test_record_lookup_and_status_queries_use_indexes(setup):
    with db.read_connection_for_path(db.database_path_from_session(setup.source_path)) as connection:
        lookup = connection.execute("""EXPLAIN QUERY PLAN SELECT payload_json FROM conversation_session_events
            WHERE session_id=? AND kind='compressions' AND json_extract(payload_json, '$.compression_id')=?""",
            (setup.source.session_id, "cmp_99")).fetchall()
        latest = connection.execute("""EXPLAIN QUERY PLAN SELECT payload_json FROM conversation_session_events
            WHERE session_id=? AND kind='compressions' AND json_extract(payload_json, '$.source_type')='conversation_context'
            AND json_extract(payload_json, '$.status')='completed' ORDER BY ordinal DESC LIMIT 1""",
            (setup.source.session_id,)).fetchall()
    assert "idx_compression_record_id" in str(lookup)
    assert "idx_compression_status" in str(latest)
    assert latest_completed_compression_id(setup.source_path) == "cmp_99"
    assert active_compression_records(setup.source_path) == []


def test_create_failure_rolls_back_source_session_list_and_graph(setup, monkeypatch):
    sessions_before = setup.repository.get_list_data("p")[:5]
    original = compaction.append_compression_record
    def fail_after_append(path, payload):
        original(path, payload)
        raise OSError("injected create failure")
    monkeypatch.setattr(compaction, "append_compression_record", fail_after_append)
    with pytest.raises(OSError):
        setup.create()
    assert db.read_events(setup.source_path, "compressions") == setup.records
    assert setup.repository.get_list_data("p")[:5] == sessions_before


def test_existing_database_gains_indexes_without_changing_records(setup):
    path = db.database_path_from_session(setup.source_path)
    with db.connection_for_path(path) as connection:
        connection.execute("DROP INDEX idx_compression_record_id")
        connection.execute("DROP INDEX idx_compression_status")
    # Simulate reopening a database created before these additive indexes existed.
    db._initialized_database_paths.discard(path.resolve())
    db.ensure_database(path.parent)
    assert db.read_events(setup.source_path, "compressions") == setup.records
    with db.read_connection_for_path(path) as connection:
        indexes = {row[1] for row in connection.execute("PRAGMA index_list(conversation_session_events)")}
    assert {"idx_compression_record_id", "idx_compression_status"} <= indexes
