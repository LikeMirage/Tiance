from dataclasses import dataclass

from app.domain.project.conversation_branch import ProjectConversationBranchNode
from app.domain.project.project import Project


@dataclass(frozen=True, slots=True)
class ProjectOverviewUsage:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    reasoning_tokens: int
    prompt_cache_hit_tokens: int
    prompt_cache_miss_tokens: int
    cost_amount: float | None
    cost_currency: str | None
    record_count: int


@dataclass(frozen=True, slots=True)
class ProjectOverviewSession:
    session_id: str
    sequence_number: int
    title: str
    runtime_status: str
    provider_id: str | None
    model_id: str | None
    message_count: int
    created_at: str
    updated_at: str
    pinned: bool
    usage: ProjectOverviewUsage


@dataclass(frozen=True, slots=True)
class ProjectOverviewItem:
    project: Project
    active_session_id: str | None
    active_count: int
    idle_count: int
    error_count: int
    usage: ProjectOverviewUsage
    sessions: tuple[ProjectOverviewSession, ...]
    session_relations: tuple[ProjectConversationBranchNode, ...]


@dataclass(frozen=True, slots=True)
class ProjectCategoryOverview:
    category_id: str
    category_name: str
    project_count: int
    session_count: int
    active_session_count: int
    idle_session_count: int
    error_session_count: int
    projects: tuple[ProjectOverviewItem, ...]
