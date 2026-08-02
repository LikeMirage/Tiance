# 项目 Pydantic 模型
# 项目响应、列表、创建请求的序列化

from pydantic import BaseModel, Field

from app.domain.project import Project, ProjectCategory, ProjectKind
from app.domain.project.project_overview import (
    ProjectCategoryOverview,
    ProjectOverviewItem,
    ProjectOverviewSession,
    ProjectOverviewUsage,
)
from app.schemas.project.project_conversations import (
    ProjectConversationBranchNodeResponse,
)


class ProjectResponse(BaseModel):
    """项目响应模型"""

    project_id: str
    name: str
    root_path: str
    category_id: str
    project_kind: ProjectKind
    is_default: bool
    is_managed: bool
    sort_order: int
    created_at: str
    updated_at: str

    @classmethod
    def from_domain(cls, project: Project, *, is_managed: bool = False) -> "ProjectResponse":
        """将领域对象转换为 Pydantic 响应模型"""

        return cls(
            project_id=project.project_id,
            name=project.name,
            root_path=project.root_path,
            category_id=project.category_id,
            project_kind=project.project_kind,
            is_default=project.is_default,
            is_managed=is_managed,
            sort_order=project.sort_order,
            created_at=project.created_at,
            updated_at=project.updated_at,
        )


class ProjectListResponse(BaseModel):
    count: int
    items: list[ProjectResponse] = Field(default_factory=list)


class ProjectCategoryResponse(BaseModel):
    """项目分类响应模型"""

    category_id: str
    name: str
    category_kind: ProjectKind
    is_default: bool
    sort_order: int
    created_at: str
    updated_at: str

    @classmethod
    def from_domain(cls, category: ProjectCategory) -> "ProjectCategoryResponse":
        return cls(
            category_id=category.category_id,
            name=category.name,
            category_kind=category.category_kind,
            is_default=category.is_default,
            sort_order=category.sort_order,
            created_at=category.created_at,
            updated_at=category.updated_at,
        )


class ProjectCategoryListResponse(BaseModel):
    count: int
    items: list[ProjectCategoryResponse] = Field(default_factory=list)


class ProjectCreateRequest(BaseModel):
    name: str | None = None
    root_path: str | None = None
    category_id: str | None = None
    project_kind: ProjectKind = ProjectKind.PROJECT


class RoleProjectCreateRequest(BaseModel):
    name: str | None = None
    category_id: str | None = None


class ProjectRenameRequest(BaseModel):
    """重命名项目的请求"""

    name: str


class ProjectCategoryCreateRequest(BaseModel):
    name: str | None = None
    category_kind: ProjectKind = ProjectKind.PROJECT


class ProjectCategoryRenameRequest(BaseModel):
    name: str


class ProjectCategoryAssignRequest(BaseModel):
    category_id: str


class ProjectOrderResponse(BaseModel):
    """项目排序响应"""

    count: int
    project_ids: list[str] = Field(default_factory=list)


class ProjectOrderSaveRequest(BaseModel):
    """保存项目排序的请求"""

    project_ids: list[str] = Field(default_factory=list)


class ProjectOverviewUsageResponse(BaseModel):
    """分类项目总览中的用量摘要"""

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    reasoning_tokens: int
    prompt_cache_hit_tokens: int
    prompt_cache_miss_tokens: int
    cost_amount: float | None = None
    cost_currency: str | None = None
    record_count: int

    @classmethod
    def from_domain(cls, usage: ProjectOverviewUsage) -> "ProjectOverviewUsageResponse":
        return cls(
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


class ProjectOverviewSessionResponse(BaseModel):
    """分类项目总览中的会话摘要"""

    session_id: str
    sequence_number: int
    title: str
    runtime_status: str
    provider_id: str | None = None
    model_id: str | None = None
    message_count: int
    created_at: str
    updated_at: str
    pinned: bool = False
    usage: ProjectOverviewUsageResponse

    @classmethod
    def from_domain(cls, session: ProjectOverviewSession) -> "ProjectOverviewSessionResponse":
        return cls(
            session_id=session.session_id,
            sequence_number=session.sequence_number,
            title=session.title,
            runtime_status=session.runtime_status,
            provider_id=session.provider_id,
            model_id=session.model_id,
            message_count=session.message_count,
            created_at=session.created_at,
            updated_at=session.updated_at,
            pinned=session.pinned,
            usage=ProjectOverviewUsageResponse.from_domain(session.usage),
        )


class ProjectOverviewItemResponse(BaseModel):
    """分类项目总览中的单个项目卡片数据"""

    project: ProjectResponse
    active_session_id: str | None = None
    active_count: int
    idle_count: int
    error_count: int
    usage: ProjectOverviewUsageResponse
    sessions: list[ProjectOverviewSessionResponse] = Field(default_factory=list)
    session_relations: list[ProjectConversationBranchNodeResponse] = Field(
        default_factory=list
    )

    @classmethod
    def from_domain(cls, item: ProjectOverviewItem) -> "ProjectOverviewItemResponse":
        return cls(
            project=ProjectResponse.from_domain(item.project),
            active_session_id=item.active_session_id,
            active_count=item.active_count,
            idle_count=item.idle_count,
            error_count=item.error_count,
            usage=ProjectOverviewUsageResponse.from_domain(item.usage),
            sessions=[
                ProjectOverviewSessionResponse.from_domain(session)
                for session in item.sessions
            ],
            session_relations=[
                ProjectConversationBranchNodeResponse.from_domain(node)
                for node in item.session_relations
            ],
        )


class ProjectCategoryOverviewResponse(BaseModel):
    """项目分类总览"""

    category_id: str
    category_name: str
    project_count: int
    session_count: int
    active_session_count: int
    idle_session_count: int
    error_session_count: int
    projects: list[ProjectOverviewItemResponse] = Field(default_factory=list)

    @classmethod
    def from_domain(cls, overview: ProjectCategoryOverview) -> "ProjectCategoryOverviewResponse":
        return cls(
            category_id=overview.category_id,
            category_name=overview.category_name,
            project_count=overview.project_count,
            session_count=overview.session_count,
            active_session_count=overview.active_session_count,
            idle_session_count=overview.idle_session_count,
            error_session_count=overview.error_session_count,
            projects=[
                ProjectOverviewItemResponse.from_domain(project)
                for project in overview.projects
            ],
        )
