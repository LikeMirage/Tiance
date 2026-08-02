# 项目文件 Pydantic 模型
# 文件节点、文件树、创建请求的序列化

from typing import Literal

from pydantic import BaseModel, Field

from app.domain.project.project_file import ProjectFileKind, ProjectFileNode


class ProjectFileNodeResponse(BaseModel):
    """文件节点响应：递归包含子节点"""

    id: str
    name: str
    path: str
    kind: ProjectFileKind
    has_children: bool = False
    mtime_ms: int | None = None
    children: list["ProjectFileNodeResponse"] = Field(default_factory=list)

    @classmethod
    def from_domain(cls, node: ProjectFileNode) -> "ProjectFileNodeResponse":
        return cls(
            id=node.id,
            name=node.name,
            path=node.path,
            kind=node.kind,
            has_children=node.has_children,
            mtime_ms=node.mtime_ms,
            children=[cls.from_domain(child) for child in node.children],
        )


class ProjectFileTreeResponse(BaseModel):
    """文件树响应"""

    project_id: str
    parent_path: str | None = None
    items: list[ProjectFileNodeResponse] = Field(default_factory=list)


class ProjectFileCreateRequest(BaseModel):
    """创建文件或文件夹的请求"""

    kind: ProjectFileKind
    parent_path: str | None = None
    name: str | None = None


class ProjectFileRenameRequest(BaseModel):
    """重命名文件或文件夹的请求"""

    path: str
    name: str


class ProjectFileMoveRequest(BaseModel):
    """移动文件或文件夹的请求"""

    path: str
    target_parent_path: str | None = None


class ProjectFileCopyRequest(BaseModel):
    """复制文件或文件夹的请求"""

    path: str
    target_parent_path: str | None = None


class ProjectFileRevealRequest(BaseModel):
    """在系统资源管理器中显示文件或文件夹的请求"""

    path: str


class ProjectFileOpenExternalRequest(BaseModel):
    """用本机程序打开项目文件的请求"""

    path: str


class ProjectFileOpenExternalResponse(BaseModel):
    """用本机程序打开项目文件的结果"""

    project_id: str
    path: str
    app_name: str
    used_default_app: bool


# ------------------------------------------------------------------
# 文件内容
# ------------------------------------------------------------------


class ProjectFileContentResponse(BaseModel):
    """文件内容响应"""

    project_id: str
    path: str
    content: str
    mtime_ms: int


class ProjectFileContentSaveRequest(BaseModel):
    """文件内容保存请求"""

    content: str
    expected_mtime_ms: int | None = None


class ProjectMarkdownToDocxRequest(BaseModel):
    """Markdown 生成 Word 请求"""

    path: str
    content: str
    page_orientation: Literal["portrait", "landscape"] = "portrait"
    page_size: Literal["letter", "a4"] = "letter"


class ProjectMarkdownToDocxResponse(BaseModel):
    """Markdown 生成 Word 结果"""

    project_id: str
    source_path: str
    output_path: str
    node: ProjectFileNodeResponse
    warnings: list[str] = Field(default_factory=list)


# ------------------------------------------------------------------
# 上传文件
# ------------------------------------------------------------------


class ProjectImageUploadRequest(BaseModel):
    """粘贴图片上传请求"""

    filename: str | None = None
    mime_type: str
    data_base64: str = Field(min_length=1)


class ProjectImageUploadResponse(BaseModel):
    """粘贴图片上传结果"""

    project_id: str
    path: str
    mime_type: str
    size_bytes: int
    node: ProjectFileNodeResponse


class ProjectUserFileUploadRequest(BaseModel):
    """用户拖入文件上传请求"""

    filename: str = Field(min_length=1)
    mime_type: str | None = None
    data_base64: str = Field(min_length=1)


class ProjectUserFileUploadResponse(BaseModel):
    """用户拖入文件上传结果"""

    project_id: str
    path: str
    original_filename: str
    mime_type: str | None = None
    size_bytes: int
    node: ProjectFileNodeResponse


# ------------------------------------------------------------------
# 工作区状态
# ------------------------------------------------------------------

WorkspaceDashboardName = Literal[
    "conversation_overview",
    "role_configuration",
    "theme_configuration",
    "basics",
    "examples",
    "dependencies",
    "callRecords",
]


class ProjectWorkspaceStateResponse(BaseModel):
    """工作区状态响应"""

    project_id: str
    expanded_paths: list[str] = Field(default_factory=list)
    open_file_paths: list[str] = Field(default_factory=list)
    active_file_path: str | None = None
    active_dashboard: WorkspaceDashboardName | None = None


class ProjectWorkspaceStateSaveRequest(BaseModel):
    """工作区状态保存请求"""

    expanded_paths: list[str] = Field(default_factory=list)
    open_file_paths: list[str] = Field(default_factory=list)
    active_file_path: str | None = None
    active_dashboard: WorkspaceDashboardName | None = None


class ProjectWorkspaceStatePatchRequest(BaseModel):
    """工作区状态局部保存请求"""

    expanded_paths: list[str] | None = None
    open_file_paths: list[str] | None = None
    active_file_path: str | None = None
    active_dashboard: WorkspaceDashboardName | None = None


class ProjectWorkspaceTabsActionRequest(BaseModel):
    """未加载项目的编辑器标签操作。"""

    action: Literal[
        "list_tabs",
        "open_file",
        "focus_file",
        "close_clean_tabs",
        "close_others_clean",
    ]
    path: str | None = None
    paths: list[str] | None = None


class ProjectWorkspaceTabsActionResponse(ProjectWorkspaceStateResponse):
    """工作区标签操作结果。"""

    action: str
    closed_file_paths: list[str] = Field(default_factory=list)
    missing_file_paths: list[str] = Field(default_factory=list)


ProjectFileNodeResponse.model_rebuild()
