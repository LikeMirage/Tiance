from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from json import dumps, loads
import sqlite3

from app.repositories.project import conversation_database as conversation_database_module
from app.repositories.project.conversation_database import (
    append_journal_event,
    count_journal_events,
    database_path_from_workspace,
    ensure_database,
    journal_mode,
    list_journal_events_range,
    write_artifact_record,
)
from app.domain.project import Project
from app.domain.llm.chat import ChatCompletionRequest, ChatMessage, ChatMessageRole, ChatUsage
from app.domain.llm.chat_http_exchange import ChatHttpExchange
from app.domain.project.project_conversation import ProjectConversationMessage
from app.repositories.project.conversation_data_view_repository import ConversationDataViewRepository
from app.repositories.project.conversation_repository import ProjectConversationRepository
from app.services.project.conversation_model_exchange import build_model_exchange_record
from app.services.project.conversation_audit import ConversationAuditService


class _Projects:
    def __init__(self, root: Path) -> None:
        self.project = Project(
            project_id="project-1",
            name="project",
            root_path=str(root),
            is_default=False,
            sort_order=0,
            created_at="now",
            updated_at="now",
        )

    def get_project(self, project_id: str):
        return self.project if project_id == self.project.project_id else None


def test_new_project_database_uses_wal(tmp_path: Path) -> None:
    workspace = tmp_path / ".Tiance"

    ensure_database(workspace)
    assert journal_mode(database_path_from_workspace(workspace)) == "wal"


def test_version_one_database_migrates_to_journal_and_artifact_schema(tmp_path: Path) -> None:
    workspace = tmp_path / ".Tiance"
    workspace.mkdir()
    database_path = database_path_from_workspace(workspace)
    connection = sqlite3.connect(database_path)
    connection.executescript(
        """
        CREATE TABLE conversation_schema (version INTEGER NOT NULL);
        INSERT INTO conversation_schema(version) VALUES (1);
        """
    )
    connection.commit()
    connection.close()

    ensure_database(workspace)

    connection = sqlite3.connect(database_path)
    try:
        assert connection.execute("SELECT version FROM conversation_schema").fetchone()[0] == 2
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    finally:
        connection.close()
    assert "conversation_journal" in tables
    assert "conversation_artifacts" in tables


def test_journal_keeps_project_order_and_artifact_reference(tmp_path: Path) -> None:
    projects = _Projects(tmp_path)
    conversations = ProjectConversationRepository(projects)
    session = conversations.create_session(
        "project-1",
        title="journal",
        provider_id="provider",
        model_id="model",
        reasoning_mode=None,
    )
    workspace = tmp_path / ".Tiance"
    write_artifact_record(
        workspace,
        artifact_id="artifact-1",
        session_id=session.session_id,
        kind="model_http_exchange",
        relative_path="conversations/sessions/session/artifacts/artifact-1.json",
        media_type="application/json",
        encoding="utf-8",
        size_bytes=12,
        sha256="abc",
        status="complete",
        created_at="2026-08-18T00:00:00+00:00",
        metadata={"round": 1},
    )
    first_id = append_journal_event(
        workspace,
        session_id=session.session_id,
        run_id="run-1",
        turn_id="turn-1",
        tool_call_id=None,
        event_type="model.exchange.completed",
        occurred_at="2026-08-18T00:00:01+00:00",
        payload={"provider_id": "provider"},
        artifact_id="artifact-1",
    )
    second_id = append_journal_event(
        workspace,
        session_id=session.session_id,
        run_id="run-1",
        turn_id="turn-1",
        tool_call_id="call-1",
        event_type="tool.completed",
        occurred_at="2026-08-18T00:00:02+00:00",
        payload={"tool_name": "example"},
    )

    events = list_journal_events_range(
        workspace,
        session_id=session.session_id,
        offset=0,
        limit=20,
    )

    assert second_id > first_id
    assert count_journal_events(workspace, session_id=session.session_id) == 2
    assert [event["event_type"] for event in events] == [
        "model.exchange.completed",
        "tool.completed",
    ]
    assert events[0]["artifact_id"] == "artifact-1"


def test_database_initialization_releases_project_directory(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    ensure_database(project_root / ".Tiance")

    archived_root = tmp_path / "archived-project"
    project_root.rename(archived_root)

    assert archived_root.is_dir()
    assert database_path_from_workspace(archived_root / ".Tiance").is_file()


def test_database_initialization_explicitly_closes_connection(monkeypatch, tmp_path: Path) -> None:
    calls: list[str] = []

    class FakeCursor:
        def fetchone(self):
            return ("wal",)

    class FakeConnection:
        def execute(self, _statement: str) -> FakeCursor:
            return FakeCursor()

        def commit(self) -> None:
            calls.append("commit")

        def close(self) -> None:
            calls.append("close")

    monkeypatch.setattr(
        conversation_database_module,
        "_open_connection",
        lambda _path: FakeConnection(),
    )
    monkeypatch.setattr(
        conversation_database_module,
        "_ensure_schema",
        lambda _connection: calls.append("schema"),
    )

    ensure_database(tmp_path / ".Tiance")

    assert calls == ["schema", "commit", "close"]


def test_database_initialization_runs_once_for_concurrent_access(
    monkeypatch,
    tmp_path: Path,
) -> None:
    workspace = tmp_path / ".Tiance"
    calls = 0
    real_ensure_schema = conversation_database_module._ensure_schema

    def counted_ensure_schema(connection) -> None:
        nonlocal calls
        calls += 1
        real_ensure_schema(connection)

    monkeypatch.setattr(
        conversation_database_module,
        "_ensure_schema",
        counted_ensure_schema,
    )

    with ThreadPoolExecutor(max_workers=12) as executor:
        paths = list(executor.map(lambda _index: ensure_database(workspace), range(24)))

    assert len(set(paths)) == 1
    assert calls == 1


def test_normal_connection_does_not_change_journal_mode_or_schema(
    monkeypatch,
    tmp_path: Path,
) -> None:
    workspace = tmp_path / ".Tiance"
    database_path = ensure_database(workspace)
    statements: list[str] = []
    real_connect = conversation_database_module.sqlite3.connect

    class RecordingConnection:
        def __init__(self, connection) -> None:
            self._connection = connection

        def execute(self, statement: str, *args, **kwargs):
            statements.append(statement)
            return self._connection.execute(statement, *args, **kwargs)

        def __getattr__(self, name: str):
            return getattr(self._connection, name)

    def recording_connect(*args, **kwargs):
        return RecordingConnection(real_connect(*args, **kwargs))

    def unexpected_schema_call(_connection) -> None:
        raise AssertionError("normal connections must not initialize the database")

    monkeypatch.setattr(
        conversation_database_module,
        "_ensure_schema",
        unexpected_schema_call,
    )
    monkeypatch.setattr(
        conversation_database_module.sqlite3,
        "connect",
        recording_connect,
    )

    with conversation_database_module.connection_for_path(database_path) as connection:
        assert connection.execute("SELECT 1").fetchone()[0] == 1

    assert not any("journal_mode" in statement.lower() for statement in statements)
    assert not any("create table" in statement.lower() for statement in statements)


def test_data_views_are_generated_from_database_without_json_mirrors(tmp_path: Path) -> None:
    projects = _Projects(tmp_path)
    conversations = ProjectConversationRepository(projects)
    session = conversations.create_session(
        "project-1",
        title="数据看板",
        provider_id="provider",
        model_id="model",
        reasoning_mode=None,
    )
    conversations.append_message(
        "project-1",
        session.session_id,
        role="user",
        content="数据库里的原始消息",
    )
    view = ConversationDataViewRepository(projects)

    result = view.read(
        "project-1",
        name="messages.jsonl",
        session_id=session.session_id,
        page=None,
        page_size=50,
    )

    assert "数据库里的原始消息" in result.content
    assert result.revision_ms > 0
    assert result.total_count == 1
    assert result.page == 1
    assert result.total_pages == 1
    assert not (
        tmp_path
        / ".Tiance"
        / "conversations"
        / "sessions"
        / session.session_id
        / "messages.jsonl"
    ).exists()


def test_conversation_list_revision_advances_with_committed_changes(tmp_path: Path) -> None:
    projects = _Projects(tmp_path)
    conversations = ProjectConversationRepository(projects)
    session = conversations.create_session(
        "project-1",
        title="revision",
        provider_id="provider",
        model_id="model",
        reasoning_mode=None,
    )

    first_revision, first_sessions, *_ = conversations.get_list_data("project-1")
    conversations.append_message(
        "project-1",
        session.session_id,
        role="user",
        content="revision change",
    )
    second_revision, second_sessions, *_ = conversations.get_list_data("project-1")

    assert second_revision > first_revision
    assert len(first_sessions) == 1
    assert second_sessions[0].message_count == 1


def test_model_exchange_view_keeps_all_appended_rounds(tmp_path: Path) -> None:
    projects = _Projects(tmp_path)
    conversations = ProjectConversationRepository(projects)
    session = conversations.create_session(
        "project-1",
        title="model exchanges",
        provider_id="provider",
        model_id="model",
        reasoning_mode=None,
    )
    conversations.append_model_exchange(
        "project-1",
        session.session_id,
        {"round_index": 1, "request": {"message_count": 2}},
    )
    conversations.append_model_exchange(
        "project-1",
        session.session_id,
        {"round_index": 2, "response": {"content": "done"}},
    )

    first_page = ConversationDataViewRepository(projects).read(
        "project-1",
        name="model_exchanges.jsonl",
        session_id=session.session_id,
        page=1,
        page_size=1,
    )
    second_page = ConversationDataViewRepository(projects).read(
        "project-1",
        name="model_exchanges.jsonl",
        session_id=session.session_id,
        page=2,
        page_size=1,
    )

    assert '"round_index": 1' in first_page.content
    assert '"round_index": 2' not in first_page.content
    assert '"round_index": 2' in second_page.content
    assert first_page.total_count == 2
    assert first_page.total_pages == 2
    assert first_page.has_next is True
    assert second_page.has_previous is True


def test_model_exchange_record_contains_logical_request_and_response() -> None:
    request = ChatCompletionRequest(
        provider_id="provider",
        model_id="model",
        project_id="project-1",
        session_id="session-1",
        messages=(
            ChatMessage(role=ChatMessageRole.SYSTEM, content="system"),
            ChatMessage(role=ChatMessageRole.USER, content="question"),
        ),
    )
    assistant = ProjectConversationMessage(
        message_id="assistant-1",
        session_id="session-1",
        role="assistant",
        content="answer",
        thinking_content="thinking",
        usage=None,
        provider_id="provider",
        model_id="model",
        status="done",
        created_at="now",
        updated_at="now",
    )

    record = build_model_exchange_record(
        request,
        assistant,
        round_index=1,
        usage=ChatUsage(prompt_tokens=10, completion_tokens=3, total_tokens=13),
    )

    assert record["request"]["message_count"] == 2
    assert record["request_snapshot"]["messages"][1]["content"] == "question"
    assert record["response"]["content"] == "answer"
    assert record["response"]["usage"]["total_tokens"] == 13
    assert "api_key" not in dumps(record)


def test_http_exchange_is_written_as_artifact_and_linked_from_journal(tmp_path: Path) -> None:
    projects = _Projects(tmp_path)
    conversations = ProjectConversationRepository(projects)
    session = conversations.create_session(
        "project-1",
        title="raw exchange",
        provider_id="provider",
        model_id="model",
        reasoning_mode=None,
    )
    request = ChatCompletionRequest(
        provider_id="provider",
        model_id="model",
        project_id="project-1",
        session_id=session.session_id,
        run_id="run-1",
        messages=(
            ChatMessage(
                role=ChatMessageRole.USER,
                content="question",
                message_id="turn-1",
            ),
        ),
    )

    ConversationAuditService(projects).record_http_exchange(
        request,
        ChatHttpExchange(
            started_at="2026-08-18T00:00:00+00:00",
            completed_at="2026-08-18T00:00:01+00:00",
            request_url="https://example.test/v1/responses",
            request_headers={"Authorization": "[REDACTED]"},
            request_body={"model": "model", "input": "question"},
            response_status=200,
            response_headers={"content-type": "application/json"},
            response_body=b'{"output":"answer"}',
        ),
    )

    events = list_journal_events_range(
        tmp_path / ".Tiance",
        session_id=session.session_id,
        offset=0,
        limit=20,
    )
    exchange_event = next(
        event
        for event in events
        if event["event_type"] == "model.http_exchange.completed"
    )
    artifact_files = list(
        (
            tmp_path
            / ".Tiance"
            / "conversations"
            / "sessions"
            / session.session_id
            / "artifacts"
        ).glob("*.json")
    )

    assert exchange_event["artifact_id"] is not None
    assert len(artifact_files) == 1
    artifact = loads(artifact_files[0].read_text(encoding="utf-8"))
    assert artifact["request"]["body"]["input"] == "question"
    assert artifact["response"]["body"]["content"] == '{"output":"answer"}'
