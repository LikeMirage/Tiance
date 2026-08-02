from __future__ import annotations

from functools import lru_cache

from app.core.errors import NotFoundError
from app.domain.llm.usage import LlmUsageSummary
from app.domain.project.project import Project
from app.domain.project.project_conversation import (
    ProjectConversationSession,
    ProjectConversationSessionState,
)
from app.domain.project.project_overview import (
    ProjectCategoryOverview,
    ProjectOverviewItem,
    ProjectOverviewSession,
    ProjectOverviewUsage,
)
from app.services.llm.usage import LlmUsageService, get_llm_usage_service
from app.services.project.project_conversations import (
    ProjectConversationService,
    get_project_conversation_service,
)
from app.services.project.projects import ProjectService, get_project_service


class ProjectCategoryOverviewService:
    def __init__(
        self,
        project_service: ProjectService,
        conversation_service: ProjectConversationService,
        usage_service: LlmUsageService,
    ) -> None:
        self._project_service = project_service
        self._conversation_service = conversation_service
        self._usage_service = usage_service

    def get_category_overview(self, category_id: str) -> ProjectCategoryOverview:
        category = next(
            (
                item
                for item in self._project_service.list_project_categories()
                if item.category_id == category_id
            ),
            None,
        )
        if category is None:
            raise NotFoundError(f"项目分类 '{category_id}' 不存在。")

        projects = tuple(
            project
            for project in self._project_service.list_projects()
            if project.category_id == category.category_id
        )
        items = tuple(self._build_project_overview(project) for project in projects)
        return ProjectCategoryOverview(
            category_id=category.category_id,
            category_name=category.name,
            project_count=len(items),
            session_count=sum(len(item.sessions) for item in items),
            active_session_count=sum(item.active_count for item in items),
            idle_session_count=sum(item.idle_count for item in items),
            error_session_count=sum(item.error_count for item in items),
            projects=items,
        )

    def get_project_overview(self, project_id: str) -> ProjectOverviewItem:
        project = self._project_service.get_project(project_id)
        if project is None:
            raise NotFoundError(f"项目 '{project_id}' 不存在。")
        return self._build_project_overview(project)

    def _build_project_overview(self, project: Project) -> ProjectOverviewItem:
        sessions, session_relations, active_session_id, session_states = (
            self._conversation_service.get_overview_data(project.project_id)
        )
        session_usage = self._usage_service.get_session_totals(
            project_id=project.project_id,
            session_ids=tuple(session.session_id for session in sessions),
        )
        overview_sessions = tuple(
            _session_to_overview(
                session,
                session_states.get(session.session_id),
                session_usage.get(session.session_id),
            )
            for session in sessions
        )
        return ProjectOverviewItem(
            project=project,
            active_session_id=active_session_id,
            active_count=sum(
                1 for session in overview_sessions if session.runtime_status == "running"
            ),
            idle_count=sum(
                1 for session in overview_sessions if session.runtime_status == "idle"
            ),
            error_count=sum(
                1 for session in overview_sessions if session.runtime_status == "error"
            ),
            usage=_sum_overview_usage(tuple(session.usage for session in overview_sessions)),
            sessions=overview_sessions,
            session_relations=session_relations,
        )


def _session_to_overview(
    session: ProjectConversationSession,
    state: ProjectConversationSessionState | None,
    usage: LlmUsageSummary | None,
) -> ProjectOverviewSession:
    runtime_status = state.runtime_status if state is not None else "idle"
    if runtime_status not in {"idle", "running", "error"}:
        runtime_status = "idle"
    return ProjectOverviewSession(
        session_id=session.session_id,
        sequence_number=session.sequence_number,
        title=session.title,
        runtime_status=runtime_status,
        provider_id=session.provider_id,
        model_id=session.model_id,
        message_count=session.message_count,
        created_at=session.created_at,
        updated_at=session.updated_at,
        pinned=session.pinned,
        usage=_usage_to_overview(usage),
    )


def _usage_to_overview(usage: LlmUsageSummary | None) -> ProjectOverviewUsage:
    if usage is None:
        return ProjectOverviewUsage(
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            reasoning_tokens=0,
            prompt_cache_hit_tokens=0,
            prompt_cache_miss_tokens=0,
            cost_amount=0,
            cost_currency=None,
            record_count=0,
        )
    return ProjectOverviewUsage(
        prompt_tokens=usage.prompt_tokens,
        completion_tokens=usage.completion_tokens,
        total_tokens=usage.total_tokens,
        reasoning_tokens=usage.reasoning_tokens,
        prompt_cache_hit_tokens=usage.prompt_cache_hit_tokens,
        prompt_cache_miss_tokens=usage.prompt_cache_miss_tokens,
        cost_amount=usage.cost_amount,
        cost_currency=usage.cost_currency,
        record_count=usage.record_count,
    )


def _sum_overview_usage(items: tuple[ProjectOverviewUsage, ...]) -> ProjectOverviewUsage:
    cost_amount, cost_currency = _sum_usage_costs(items)
    return ProjectOverviewUsage(
        prompt_tokens=sum(item.prompt_tokens for item in items),
        completion_tokens=sum(item.completion_tokens for item in items),
        total_tokens=sum(item.total_tokens for item in items),
        reasoning_tokens=sum(item.reasoning_tokens for item in items),
        prompt_cache_hit_tokens=sum(item.prompt_cache_hit_tokens for item in items),
        prompt_cache_miss_tokens=sum(item.prompt_cache_miss_tokens for item in items),
        cost_amount=cost_amount,
        cost_currency=cost_currency,
        record_count=sum(item.record_count for item in items),
    )


def _sum_usage_costs(items: tuple[ProjectOverviewUsage, ...]) -> tuple[float | None, str | None]:
    priced_items = tuple(item for item in items if item.record_count > 0)
    if not priced_items:
        return 0, None

    currency: str | None = None
    total = 0.0
    for item in priced_items:
        if item.cost_amount is None:
            return None, None
        if currency is None:
            currency = item.cost_currency
        elif item.cost_currency != currency:
            return None, None
        total += item.cost_amount
    return total, currency


@lru_cache
def get_project_category_overview_service() -> ProjectCategoryOverviewService:
    return ProjectCategoryOverviewService(
        get_project_service(),
        get_project_conversation_service(),
        get_llm_usage_service(),
    )
