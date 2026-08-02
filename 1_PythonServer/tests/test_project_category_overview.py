from datetime import UTC, datetime

from app.domain.llm.usage import LlmUsageSummary
from app.domain.project import Project, ProjectCategory
from app.domain.project.project_conversation import (
    ProjectConversationSession,
    ProjectConversationSessionSettings,
    ProjectConversationSessionState,
)
from app.services.project.project_category_overview import ProjectCategoryOverviewService


def test_project_category_overview_counts_sessions_and_usage(tmp_path):
    now = datetime.now(UTC).isoformat()
    project_root = tmp_path / "project"
    project_root.mkdir()

    category = ProjectCategory(
        category_id="cat-1",
        name="分类 1",
        is_default=False,
        sort_order=0,
        created_at=now,
        updated_at=now,
    )
    project = Project(
        project_id="project-1",
        name="项目 1",
        root_path=str(project_root),
        category_id=category.category_id,
        is_default=False,
        sort_order=0,
        created_at=now,
        updated_at=now,
    )
    sessions = (
        _session("session-1", 1, "运行中", 2, now),
        _session("session-2", 2, "空闲", 0, now),
        _session("session-3", 3, "异常", 1, now),
    )
    states = {
        "session-1": _state("session-1", "running", now),
        "session-3": _state("session-3", "error", now),
    }
    service = ProjectCategoryOverviewService(
        _FakeProjectService(category, (project,)),
        _FakeConversationService(sessions, active_session_id="session-1", states=states),
        _FakeUsageService({
            "session-1": _usage(total_tokens=100, prompt_tokens=80, completion_tokens=20),
            "session-3": _usage(total_tokens=15, prompt_tokens=10, completion_tokens=5),
        }),
    )

    overview = service.get_category_overview(category.category_id)

    assert overview.project_count == 1
    assert overview.session_count == 3
    assert overview.active_session_count == 1
    assert overview.idle_session_count == 1
    assert overview.error_session_count == 1
    assert overview.projects[0].active_session_id == "session-1"
    assert all(session.pinned is False for session in overview.projects[0].sessions)
    assert overview.projects[0].usage.total_tokens == 115
    assert [session.runtime_status for session in overview.projects[0].sessions] == [
        "running",
        "idle",
        "error",
    ]
    assert [session.usage.total_tokens for session in overview.projects[0].sessions] == [
        100,
        0,
        15,
    ]


class _FakeProjectService:
    def __init__(self, category: ProjectCategory, projects: tuple[Project, ...]) -> None:
        self._category = category
        self._projects = projects

    def list_project_categories(self) -> tuple[ProjectCategory, ...]:
        return (self._category,)

    def list_projects(self) -> tuple[Project, ...]:
        return self._projects


class _FakeConversationService:
    def __init__(
        self,
        sessions: tuple[ProjectConversationSession, ...],
        *,
        active_session_id: str | None,
        states: dict[str, ProjectConversationSessionState],
    ) -> None:
        self._active_session_id = active_session_id
        self._sessions = sessions
        self._states = states

    def get_overview_data(
        self,
        _project_id: str,
    ) -> tuple[
        tuple[ProjectConversationSession, ...],
        tuple,
        str | None,
        dict[str, ProjectConversationSessionState],
    ]:
        return self._sessions, (), self._active_session_id, self._states


class _FakeUsageService:
    def __init__(self, usage_by_session: dict[str, LlmUsageSummary]) -> None:
        self._usage_by_session = usage_by_session

    def get_session_totals(
        self,
        *,
        project_id: str,
        session_ids: tuple[str, ...],
    ) -> dict[str, LlmUsageSummary]:
        return {
            session_id: self._usage_by_session[session_id]
            for session_id in session_ids
            if session_id in self._usage_by_session
        }


def _session(
    session_id: str,
    sequence_number: int,
    title: str,
    message_count: int,
    timestamp: str,
) -> ProjectConversationSession:
    return ProjectConversationSession(
        session_id=session_id,
        sequence_number=sequence_number,
        title=title,
        provider_id="deepseek",
        model_id="deepseek-v4-flash",
        reasoning_mode=None,
        manual_title=False,
        settings=ProjectConversationSessionSettings(),
        created_at=timestamp,
        updated_at=timestamp,
        message_count=message_count,
    )


def _usage(
    *,
    total_tokens: int,
    prompt_tokens: int,
    completion_tokens: int,
) -> LlmUsageSummary:
    return LlmUsageSummary(
        provider_id=None,
        provider_display_name=None,
        model_id=None,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        reasoning_tokens=0,
        prompt_cache_hit_tokens=0,
        prompt_cache_miss_tokens=0,
        cost_amount=0,
        cost_currency=None,
        record_count=1,
    )


def _state(
    session_id: str,
    runtime_status: str,
    timestamp: str,
) -> ProjectConversationSessionState:
    return ProjectConversationSessionState(
        session_id=session_id,
        runtime_status=runtime_status,
        draft="",
        references=[],
        updated_at=timestamp,
    )
