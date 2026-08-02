from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

from app.domain.llm.chat import ChatToolResult
from app.domain.project import Project, ProjectKind
from app.domain.project.project_conversation import ProjectConversationSession
from app.domain.tools import ToolCallRecordDraft, ToolFolder, ToolRegistryEntry, Toolset
from app.repositories.tools import ToolCallRecordRepository
from app.infra.database import ensure_database_schema
from app.services.tools.tool_call_records import ToolCallRecordService


def test_tool_call_record_repository_persists_all_records_in_tool_project(tmp_path):
    repository = ToolCallRecordRepository()
    project_root = tmp_path / "tool-project"
    for index in range(520):
        repository.append(
            project_root,
            _draft(call_id=f"call-{index}"),
        )

    records = repository.list_project_records(project_root)

    assert len(records) == 520
    assert records[0].record_id.startswith("tool_call_")
    assert records[0].tool_project_id == "tool-1"
    assert repository.records_path(project_root) == (
        project_root.resolve() / ".Tiance" / "tool-calls" / "records.jsonl"
    )


def test_fresh_database_has_no_tool_call_record_table(tmp_path):
    database_path = tmp_path / "tiance.db"
    ensure_database_schema(database_path)

    with sqlite3.connect(database_path) as connection:
        table_count = connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='tool_call_records'"
        ).fetchone()[0]

    assert table_count == 0


def test_tool_call_record_repository_rejects_corrupted_record_file(tmp_path):
    repository = ToolCallRecordRepository()
    records_path = repository.records_path(tmp_path / "tool-project")
    records_path.parent.mkdir(parents=True)
    records_path.write_text("{broken}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="第 1 行"):
        repository.list_project_records(tmp_path / "tool-project")


def test_tool_call_record_service_appends_to_resolved_tool_project(tmp_path):
    repository = ToolCallRecordRepository()
    fixtures = _FakeToolProjects(tmp_path)
    service = _service(repository, fixtures)

    saved = service.append_result(
        ChatToolResult(
            call_id="call-1",
            name="read_text_file",
            arguments="{}",
            ok=True,
            content='{"ok":true}',
            error=None,
            tool_project_id="tool-1",
            elapsed_ms=123,
            dynamic=True,
        ),
        project_id="source-project",
        session_id="session-1",
    )

    assert saved is not None
    records = service.list_project_records("category-1", "tool-1")
    assert records[0].source_project_name == "当前项目名"
    assert records[0].session_title == "当前会话名"
    assert records[0].elapsed_ms == 123


def test_tool_call_record_service_ignores_unresolved_tool_project(tmp_path):
    service = _service(ToolCallRecordRepository(), _FakeToolProjects(tmp_path))

    saved = service.append_result(
        ChatToolResult(
            call_id="call-1",
            name="unknown_tool",
            arguments="{}",
            ok=False,
            content='{"ok":false}',
            error="unknown",
        ),
        project_id=None,
        session_id=None,
    )

    assert saved is None
    assert service.get_total_call_count() == 0


def test_tool_call_record_service_summarizes_current_category(tmp_path):
    repository = ToolCallRecordRepository()
    fixtures = _FakeToolProjects(tmp_path)
    for project_id, ok, elapsed_ms, dynamic in (
        ("tool-1", True, 100, True),
        ("tool-1", True, 300, False),
        ("tool-2", False, 50, True),
    ):
        repository.append(
            fixtures.projects[project_id].root_path,
            _draft(
                tool_project_id=project_id,
                tool_name="read_text_file" if project_id == "tool-1" else "write_text_file",
                call_id=f"call-{project_id}-{elapsed_ms}",
                ok=ok,
                elapsed_ms=elapsed_ms,
                dynamic=dynamic,
            ),
        )
    service = _service(repository, fixtures)

    summary = service.summarize_category_records("category-1")

    assert summary.total_call_count == 3
    assert summary.category_call_count == 3
    first = summary.items[0]
    assert first.project_id == "tool-1"
    assert first.call_count == 2
    assert first.average_elapsed_ms == 200
    assert first.dynamic_count == 1
    assert first.full_load_count == 1
    assert first.global_call_share == pytest.approx(2 / 3)
    overview = service.summarize_global_records()
    assert overview.total_call_count == 3
    assert overview.top_tools[0].display_name == "文本读取"


def _draft(
    *,
    tool_project_id: str = "tool-1",
    tool_name: str = "read_text_file",
    call_id: str = "call-1",
    ok: bool = True,
    elapsed_ms: int | None = None,
    dynamic: bool | None = None,
) -> ToolCallRecordDraft:
    return ToolCallRecordDraft(
        tool_project_id=tool_project_id,
        tool_name=tool_name,
        call_id=call_id,
        source_project_id="source-project",
        session_id="session-1",
        arguments_text="{}",
        result_text='{"ok":true}',
        ok=ok,
        error=None if ok else "failed",
        elapsed_ms=elapsed_ms,
        dynamic=dynamic,
    )


def _service(
    repository: ToolCallRecordRepository,
    fixtures: "_FakeToolProjects",
) -> ToolCallRecordService:
    return ToolCallRecordService(
        repository,
        project_service=_FakeProjectService(),
        conversation_service=_FakeConversationService(),
        tool_project_service=fixtures,
        tool_registry_service=_FakeToolRegistryService(fixtures),
    )


class _FakeToolProjects:
    def __init__(self, root: Path) -> None:
        self.projects = {
            project_id: Project(
                project_id=project_id,
                name=name,
                root_path=str(root / project_id),
                category_id="category-1",
                project_kind=ProjectKind.TOOL,
                is_default=False,
                sort_order=index,
                created_at="now",
                updated_at="now",
            )
            for index, (project_id, name) in enumerate(
                (("tool-1", "文本读取"), ("tool-2", "文本写入"))
            )
        }

    def get_tool_project(self, project_id: str):
        return self.projects.get(project_id)

    def require_tool_project(self, category_id: str, project_id: str):
        project = self.projects[project_id]
        assert project.category_id == category_id
        return project

    def list_toolsets(self):
        return (
            Toolset(
                category_id="category-1",
                name="基础工具",
                scope="local",
                root_path="",
                readonly=False,
                created_at="now",
                updated_at="now",
            ),
        )

    def list_tool_folders(self, category_id: str):
        assert category_id == "category-1"
        return tuple(self.folder_for_project(project) for project in self.projects.values())

    @staticmethod
    def folder_for_project(project: Project):
        return ToolFolder(
            project_id=project.project_id,
            category_id=project.category_id,
            name=project.name,
            root_path=project.root_path,
            created_at=project.created_at,
            updated_at=project.updated_at,
        )


class _FakeToolRegistryService:
    def __init__(self, fixtures: _FakeToolProjects) -> None:
        self._fixtures = fixtures

    def list_entries(self, *, enabled_only=False):
        del enabled_only
        return tuple(
            ToolRegistryEntry(
                project_id=project.project_id,
                category_id=project.category_id,
                category_name="基础工具",
                tool_name="read_text_file" if project.project_id == "tool-1" else "write_text_file",
                display_name=project.name,
                description="",
                keywords=(),
                enabled=True,
                dynamic=True,
                root_path=project.root_path,
                runtime_entry="",
                parameter_names=(),
                example_titles=(),
                indexed_at="now",
                updated_at="now",
                full_injection_char_count=128,
                dynamic_injection_char_count=64,
            )
            for project in self._fixtures.projects.values()
        )


class _FakeProjectService:
    def get_project(self, project_id: str):
        if project_id != "source-project":
            return None
        return Project(
            project_id=project_id,
            name="当前项目名",
            root_path="C:/work",
            category_id="daily-project",
            project_kind=ProjectKind.PROJECT,
            is_default=False,
            sort_order=0,
            created_at="now",
            updated_at="now",
        )


class _FakeConversationService:
    def get_session(self, _project_id: str, session_id: str):
        return ProjectConversationSession(
            session_id=session_id,
            sequence_number=1,
            title="当前会话名",
            provider_id=None,
            model_id=None,
            created_at="now",
            updated_at="now",
            message_count=0,
        )
