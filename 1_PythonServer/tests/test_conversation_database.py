from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.repositories.project import conversation_database as conversation_database_module
from app.repositories.project.conversation_database import (
    database_path_from_workspace,
    ensure_database,
    journal_mode,
)
from app.domain.project import Project
from app.repositories.project.conversation_data_view_repository import ConversationDataViewRepository
from app.repositories.project.conversation_repository import ProjectConversationRepository


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

    content, revision, total_count, truncated = view.read(
        "project-1",
        name="messages.jsonl",
        session_id=session.session_id,
    )

    assert "数据库里的原始消息" in content
    assert revision > 0
    assert total_count == 1
    assert truncated is False
    assert not (
        tmp_path
        / ".Tiance"
        / "conversations"
        / "sessions"
        / session.session_id
        / "messages.jsonl"
    ).exists()
