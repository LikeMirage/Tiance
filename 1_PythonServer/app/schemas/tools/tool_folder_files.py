from pydantic import BaseModel, Field

from app.domain.file_workspace import FileEntryKind, FileEntryNode


class ToolFolderFileNodeResponse(BaseModel):
    id: str
    name: str
    path: str
    kind: FileEntryKind
    has_children: bool = False
    mtime_ms: int | None = None
    children: list["ToolFolderFileNodeResponse"] = Field(default_factory=list)

    @classmethod
    def from_domain(cls, node: FileEntryNode) -> "ToolFolderFileNodeResponse":
        return cls(
            id=node.id,
            name=node.name,
            path=node.path,
            kind=node.kind,
            has_children=node.has_children,
            mtime_ms=node.mtime_ms,
            children=[cls.from_domain(child) for child in node.children],
        )


class ToolFolderFileTreeResponse(BaseModel):
    category_id: str
    project_id: str
    parent_path: str | None = None
    items: list[ToolFolderFileNodeResponse] = Field(default_factory=list)


class ToolFolderFileCreateRequest(BaseModel):
    kind: FileEntryKind
    parent_path: str | None = None
    name: str | None = None


class ToolFolderFileRenameRequest(BaseModel):
    path: str
    name: str


class ToolFolderFileMoveRequest(BaseModel):
    path: str
    target_parent_path: str | None = None


class ToolFolderFileCopyRequest(BaseModel):
    path: str
    target_parent_path: str | None = None


class ToolFolderFileRevealRequest(BaseModel):
    path: str


class ToolFolderFileOpenExternalRequest(BaseModel):
    path: str


class ToolFolderFileOpenExternalResponse(BaseModel):
    category_id: str
    project_id: str
    path: str
    app_name: str
    used_default_app: bool


class ToolFolderFileContentResponse(BaseModel):
    category_id: str
    project_id: str
    path: str
    content: str
    mtime_ms: int


class ToolFolderFileContentSaveRequest(BaseModel):
    content: str
    expected_mtime_ms: int | None = None


ToolFolderFileNodeResponse.model_rebuild()
