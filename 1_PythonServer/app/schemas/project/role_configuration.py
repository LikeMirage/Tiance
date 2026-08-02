from pydantic import BaseModel, Field

from app.schemas.project.project_conversations import (
    ProjectConversationSessionResponse,
)
from app.schemas.project.projects import ProjectResponse


class RoleCatalogCategoryResponse(BaseModel):
    category_id: str
    name: str
    sort_order: int


class RoleCatalogItemResponse(BaseModel):
    role_project_id: str
    name: str
    category_id: str
    description: str | None = None
    is_default: bool = False
    sort_order: int


class RoleCatalogResponse(BaseModel):
    default_role_project_id: str
    categories: list[RoleCatalogCategoryResponse] = Field(default_factory=list)
    roles: list[RoleCatalogItemResponse] = Field(default_factory=list)


class ApplyConversationRoleRequest(BaseModel):
    role_project_id: str = Field(min_length=1)


class SaveConversationAsRoleRequest(BaseModel):
    name: str = Field(min_length=1)
    category_id: str | None = None


class SaveConversationAsRoleResponse(BaseModel):
    role: ProjectResponse
    session: ProjectConversationSessionResponse
