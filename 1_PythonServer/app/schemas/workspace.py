from pydantic import BaseModel, Field

from app.domain.workspace_state import (
    CollectionOverviewView,
    ProjectOverviewLayoutMode,
    ProjectOverviewView,
    ToolOverviewView,
    WorkspaceCategorySelection,
    WorkspaceLayoutPreferences,
    WorkspaceLastOpenedState,
)


class WorkspaceCategorySelectionResponse(BaseModel):
    category_id: str
    project_id: str | None = None
    session_id: str | None = None
    updated_at: str | None = None

    @classmethod
    def from_domain(
        cls,
        selection: WorkspaceCategorySelection,
    ) -> "WorkspaceCategorySelectionResponse":
        return cls(
            category_id=selection.category_id,
            project_id=selection.project_id,
            session_id=selection.session_id,
            updated_at=selection.updated_at,
        )


class WorkspaceLastOpenedResponse(BaseModel):
    project_id: str | None = None
    category_id: str | None = None
    session_id: str | None = None
    updated_at: str | None = None
    category_selections: dict[str, WorkspaceCategorySelectionResponse] = Field(default_factory=dict)

    @classmethod
    def from_domain(cls, state: WorkspaceLastOpenedState) -> "WorkspaceLastOpenedResponse":
        return cls(
            project_id=state.project_id,
            category_id=state.category_id,
            session_id=state.session_id,
            updated_at=state.updated_at,
            category_selections={
                selection.category_id: WorkspaceCategorySelectionResponse.from_domain(selection)
                for selection in state.category_selections
            },
        )


class WorkspaceLastOpenedSaveRequest(BaseModel):
    category_id: str | None = None
    project_id: str | None = None
    session_id: str | None = None


class WorkspaceLayoutPreferencesResponse(BaseModel):
    version: int = 6
    side_panel_width: int
    ai_panel_width: int
    composer_height: int
    project_overview_layout_modes: dict[str, ProjectOverviewLayoutMode] = Field(
        default_factory=dict,
    )
    project_overview_maximized_project_ids: dict[str, str] = Field(
        default_factory=dict,
    )
    project_overview_views: dict[str, ProjectOverviewView] = Field(default_factory=dict)
    tool_overview_views: dict[str, ToolOverviewView] = Field(default_factory=dict)
    collection_overview_views: dict[str, CollectionOverviewView] = Field(default_factory=dict)

    @classmethod
    def from_domain(
        cls,
        preferences: WorkspaceLayoutPreferences,
    ) -> "WorkspaceLayoutPreferencesResponse":
        return cls(
            side_panel_width=preferences.side_panel_width,
            ai_panel_width=preferences.ai_panel_width,
            composer_height=preferences.composer_height,
            project_overview_layout_modes={
                item.category_id: item.layout_mode
                for item in preferences.project_overview_layouts
            },
            project_overview_maximized_project_ids={
                item.category_id: item.project_id
                for item in preferences.project_overview_maximized
            },
            project_overview_views={
                item.category_id: item.view
                for item in preferences.project_overview_views
            },
            tool_overview_views={
                item.category_id: item.view
                for item in preferences.tool_overview_views
            },
            collection_overview_views={
                item.category_id: item.view
                for item in preferences.collection_overview_views
            },
        )


class WorkspaceProjectOverviewLayoutSaveRequest(BaseModel):
    category_id: str
    layout_mode: ProjectOverviewLayoutMode


class WorkspaceProjectOverviewMaximizedSaveRequest(BaseModel):
    category_id: str
    project_id: str | None = None


class WorkspaceProjectOverviewViewSaveRequest(BaseModel):
    category_id: str
    view: ProjectOverviewView


class WorkspaceToolOverviewViewSaveRequest(BaseModel):
    category_id: str
    view: ToolOverviewView


class WorkspaceCollectionOverviewViewSaveRequest(BaseModel):
    category_id: str
    view: CollectionOverviewView


class WorkspaceLayoutPreferencesSaveRequest(BaseModel):
    side_panel_width: int | None = None
    ai_panel_width: int | None = None
    composer_height: int | None = None
    project_overview_layout: WorkspaceProjectOverviewLayoutSaveRequest | None = None
    project_overview_maximized: WorkspaceProjectOverviewMaximizedSaveRequest | None = None
    project_overview_view: WorkspaceProjectOverviewViewSaveRequest | None = None
    tool_overview_view: WorkspaceToolOverviewViewSaveRequest | None = None
    collection_overview_view: WorkspaceCollectionOverviewViewSaveRequest | None = None


class WorkspaceActivitySummaryResponse(BaseModel):
    conversation_count: int
    sent_message_count: int
    ai_runtime_ms: int


class ServerDirectoryEntryResponse(BaseModel):
    name: str
    path: str


class ServerDirectoryListingResponse(BaseModel):
    path: str
    parent_path: str | None = None
    roots: list[ServerDirectoryEntryResponse] = Field(default_factory=list)
    directories: list[ServerDirectoryEntryResponse] = Field(default_factory=list)
