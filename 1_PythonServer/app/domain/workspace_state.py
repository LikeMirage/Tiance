from dataclasses import dataclass
from typing import Literal


ProjectOverviewView = Literal["projects", "conversation", "branches"]
ToolOverviewView = Literal["tools", "online", "projects", "conversation", "branches"]
CollectionOverviewView = Literal["specialized", "online", "projects", "conversation"]


@dataclass(frozen=True, slots=True)
class WorkspaceCategorySelection:
    category_id: str
    project_id: str | None
    updated_at: str | None


@dataclass(frozen=True, slots=True)
class WorkspaceLastOpenedState:
    project_id: str | None
    category_id: str | None
    updated_at: str | None
    category_selections: tuple[WorkspaceCategorySelection, ...] = ()


@dataclass(frozen=True, slots=True)
class WorkspaceProjectOverviewMaximized:
    category_id: str
    project_id: str


@dataclass(frozen=True, slots=True)
class WorkspaceProjectOverviewView:
    category_id: str
    view: ProjectOverviewView


@dataclass(frozen=True, slots=True)
class WorkspaceToolOverviewView:
    category_id: str
    view: ToolOverviewView


@dataclass(frozen=True, slots=True)
class WorkspaceCollectionOverviewView:
    category_id: str
    view: CollectionOverviewView


@dataclass(frozen=True, slots=True)
class WorkspaceLayoutPreferences:
    side_panel_width: int
    ai_panel_width: int
    composer_height: int
    project_overview_maximized: tuple[WorkspaceProjectOverviewMaximized, ...] = ()
    project_overview_views: tuple[WorkspaceProjectOverviewView, ...] = ()
    tool_overview_views: tuple[WorkspaceToolOverviewView, ...] = ()
    collection_overview_views: tuple[WorkspaceCollectionOverviewView, ...] = ()
