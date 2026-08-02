from pydantic import BaseModel, Field

from app.domain.tools import ToolFolder, Toolset


class ToolsetResponse(BaseModel):
    category_id: str
    name: str
    scope: str
    root_path: str
    readonly: bool
    created_at: str
    updated_at: str

    @classmethod
    def from_domain(cls, toolset: Toolset) -> "ToolsetResponse":
        return cls(
            category_id=toolset.category_id,
            name=toolset.name,
            scope=toolset.scope,
            root_path=toolset.root_path,
            readonly=toolset.readonly,
            created_at=toolset.created_at,
            updated_at=toolset.updated_at,
        )


class ToolsetListResponse(BaseModel):
    count: int
    items: list[ToolsetResponse] = Field(default_factory=list)


class ToolsetCreateRequest(BaseModel):
    name: str | None = None


class ToolsetRenameRequest(BaseModel):
    name: str


class ToolFolderResponse(BaseModel):
    project_id: str
    category_id: str
    name: str
    root_path: str
    created_at: str
    updated_at: str

    @classmethod
    def from_domain(cls, folder: ToolFolder) -> "ToolFolderResponse":
        return cls(
            project_id=folder.project_id,
            category_id=folder.category_id,
            name=folder.name,
            root_path=folder.root_path,
            created_at=folder.created_at,
            updated_at=folder.updated_at,
        )


class ToolFolderListResponse(BaseModel):
    count: int
    items: list[ToolFolderResponse] = Field(default_factory=list)


class ToolFolderCreateRequest(BaseModel):
    name: str | None = None


class ToolFolderRenameRequest(BaseModel):
    name: str


class ToolFolderMoveRequest(BaseModel):
    target_category_id: str


class ToolFolderDynamicLoadingRequest(BaseModel):
    dynamic: bool


class ToolFolderDynamicLoadingResponse(BaseModel):
    category_id: str
    project_id: str
    dynamic: bool
    updated_at: str
