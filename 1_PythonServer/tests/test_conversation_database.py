from __future__ import annotations

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

    class FakeConnection:
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
