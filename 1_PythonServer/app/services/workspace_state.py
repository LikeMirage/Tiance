from datetime import UTC, datetime
from functools import lru_cache
from json import dumps, loads
from re import fullmatch
from typing import Any

from app.core.errors import BadRequestError, NotFoundError
from app.domain.workspace_state import (
    WorkspaceCategorySelection,
    WorkspaceCollectionOverviewView,
    WorkspaceLayoutPreferences,
    WorkspaceLastOpenedState,
    WorkspaceProjectOverviewLayout,
    WorkspaceProjectOverviewMaximized,
    WorkspaceProjectOverviewView,
    WorkspaceToolOverviewView,
)
from app.domain.project.project import ProjectKind
from app.repositories.project import ProjectRepository, get_project_repository
from app.services.project.project_conversations import (
    ProjectConversationService,
    get_project_conversation_service,
)
from app.services.project.project_ids import normalize_project_id

WORKSPACE_LAST_OPENED_KEY = "workspace.last_opened"
WORKSPACE_LAYOUT_PREFERENCES_KEY = "workspace.layout_preferences"
DEFAULT_SIDE_PANEL_WIDTH = 250
MIN_SIDE_PANEL_WIDTH = 108
MAX_SIDE_PANEL_WIDTH = 560
DEFAULT_AI_PANEL_WIDTH = 364
MIN_AI_PANEL_WIDTH = 248
MAX_AI_PANEL_WIDTH = 900
DEFAULT_COMPOSER_HEIGHT = 144
MIN_COMPOSER_HEIGHT = 112
MAX_COMPOSER_HEIGHT = 280
PROJECT_OVERVIEW_LAYOUT_MODES = frozenset({"grid", "wide", "roller", "stack"})
PROJECT_OVERVIEW_VIEWS = frozenset({"projects", "conversation", "branches"})
TOOL_OVERVIEW_VIEWS = frozenset({"tools", "online", "projects", "conversation", "branches"})
COLLECTION_OVERVIEW_VIEWS = frozenset({"specialized", "online", "projects", "conversation"})


class WorkspaceStateService:
    def __init__(
        self,
        project_repository: ProjectRepository,
        conversation_service: ProjectConversationService,
    ) -> None:
        self._project_repository = project_repository
        self._conversation_service = conversation_service

    def get_last_opened(self) -> WorkspaceLastOpenedState:
        raw = self._project_repository.get_metadata_value(WORKSPACE_LAST_OPENED_KEY)
        if not raw:
            return _empty_last_opened()

        payload = _parse_last_opened_payload(raw)
        if payload is None:
            return _empty_last_opened()

        return self._state_from_payload(payload)

    def get_layout_preferences(self) -> WorkspaceLayoutPreferences:
        raw = self._project_repository.get_metadata_value(WORKSPACE_LAYOUT_PREFERENCES_KEY)
        if not raw:
            return _default_layout_preferences()

        payload = _parse_json_object(raw)
        if payload is None:
            return _default_layout_preferences()

        return _layout_preferences_from_payload(payload)

    def save_layout_preferences(
        self,
        *,
        side_panel_width: int | None = None,
        ai_panel_width: int | None = None,
        composer_height: int | None = None,
        project_overview_category_id: str | None = None,
        project_overview_layout_mode: str | None = None,
        project_overview_maximized_category_id: str | None = None,
        project_overview_maximized_project_id: str | None = None,
        update_project_overview_maximized: bool = False,
        project_overview_view_category_id: str | None = None,
        project_overview_view: str | None = None,
        tool_overview_view_category_id: str | None = None,
        tool_overview_view: str | None = None,
        collection_overview_view_category_id: str | None = None,
        collection_overview_view: str | None = None,
    ) -> WorkspaceLayoutPreferences:
        current = self.get_layout_preferences()
        project_overview_layouts = {
            item.category_id: item.layout_mode
            for item in current.project_overview_layouts
        }
        if project_overview_category_id is not None or project_overview_layout_mode is not None:
            category_id = _request_category_id(project_overview_category_id)
            if category_id is None:
                raise BadRequestError("必须提供项目分类。")
            if self._project_repository.get_project_category(category_id) is None:
                raise NotFoundError(f"项目分类 '{category_id}' 不存在。")
            if project_overview_layout_mode not in PROJECT_OVERVIEW_LAYOUT_MODES:
                raise BadRequestError("不支持的项目看板布局。")
            project_overview_layouts[category_id] = project_overview_layout_mode

        project_overview_maximized = {
            item.category_id: item.project_id
            for item in current.project_overview_maximized
        }
        if update_project_overview_maximized:
            category_id = _request_category_id(project_overview_maximized_category_id)
            if category_id is None:
                raise BadRequestError("必须提供项目分类。")
            if self._project_repository.get_project_category(category_id) is None:
                raise NotFoundError(f"项目分类 '{category_id}' 不存在。")
            if project_overview_maximized_project_id is None:
                project_overview_maximized.pop(category_id, None)
            else:
                project_id = normalize_project_id(project_overview_maximized_project_id)
                project = self._project_repository.get_project(project_id)
                if project is None:
                    raise NotFoundError(f"项目 '{project_id}' 不存在。")
                if project.category_id != category_id:
                    raise BadRequestError("项目不属于指定分类。")
                project_overview_maximized[category_id] = project_id

        project_overview_views = {
            item.category_id: item.view
            for item in current.project_overview_views
        }
        if project_overview_view_category_id is not None or project_overview_view is not None:
            category_id = _request_category_id(project_overview_view_category_id)
            if category_id is None:
                raise BadRequestError("必须提供项目分类。")
            if self._project_repository.get_project_category(category_id) is None:
                raise NotFoundError(f"项目分类 '{category_id}' 不存在。")
            if project_overview_view not in PROJECT_OVERVIEW_VIEWS:
                raise BadRequestError("不支持的项目总览视图。")
            project_overview_views[category_id] = _persisted_project_overview_view(
                project_overview_view,
            )

        tool_overview_views = {
            item.category_id: item.view
            for item in current.tool_overview_views
        }
        if tool_overview_view_category_id is not None or tool_overview_view is not None:
            category_id = _request_category_id(tool_overview_view_category_id)
            if category_id is None:
                raise BadRequestError("必须提供工具分类。")
            category = self._project_repository.get_project_category(category_id)
            if category is None:
                raise NotFoundError(f"工具分类 '{category_id}' 不存在。")
            if category.category_kind != ProjectKind.TOOL:
                raise BadRequestError("指定分类不是工具分类。")
            if tool_overview_view not in TOOL_OVERVIEW_VIEWS:
                raise BadRequestError("不支持的工具集看板。")
            tool_overview_views[category_id] = _persisted_tool_overview_view(
                tool_overview_view,
            )

        collection_overview_views = {
            item.category_id: item.view
            for item in current.collection_overview_views
        }
        if (
            collection_overview_view_category_id is not None
            or collection_overview_view is not None
        ):
            category_id = _request_category_id(collection_overview_view_category_id)
            if category_id is None:
                raise BadRequestError("必须提供角色或主题分类。")
            category = self._project_repository.get_project_category(category_id)
            if category is None:
                raise NotFoundError(f"分类 '{category_id}' 不存在。")
            if category.category_kind not in {ProjectKind.ROLE, ProjectKind.THEME}:
                raise BadRequestError("指定分类不是角色或主题分类。")
            if collection_overview_view not in COLLECTION_OVERVIEW_VIEWS:
                raise BadRequestError("不支持的集合看板。")
            collection_overview_views[category_id] = collection_overview_view

        preferences = WorkspaceLayoutPreferences(
            side_panel_width=_clamp_int(
                side_panel_width,
                current.side_panel_width,
                MIN_SIDE_PANEL_WIDTH,
                MAX_SIDE_PANEL_WIDTH,
            ),
            ai_panel_width=_clamp_int(
                ai_panel_width,
                current.ai_panel_width,
                MIN_AI_PANEL_WIDTH,
                MAX_AI_PANEL_WIDTH,
            ),
            composer_height=_clamp_int(
                composer_height,
                current.composer_height,
                MIN_COMPOSER_HEIGHT,
                MAX_COMPOSER_HEIGHT,
            ),
            project_overview_layouts=tuple(
                WorkspaceProjectOverviewLayout(
                    category_id=category_id,
                    layout_mode=layout_mode,
                )
                for category_id, layout_mode in sorted(project_overview_layouts.items())
            ),
            project_overview_maximized=tuple(
                WorkspaceProjectOverviewMaximized(
                    category_id=category_id,
                    project_id=project_id,
                )
                for category_id, project_id in sorted(project_overview_maximized.items())
            ),
            project_overview_views=tuple(
                WorkspaceProjectOverviewView(
                    category_id=category_id,
                    view=view,
                )
                for category_id, view in sorted(project_overview_views.items())
            ),
            tool_overview_views=tuple(
                WorkspaceToolOverviewView(
                    category_id=category_id,
                    view=view,
                )
                for category_id, view in sorted(tool_overview_views.items())
            ),
            collection_overview_views=tuple(
                WorkspaceCollectionOverviewView(
                    category_id=category_id,
                    view=view,
                )
                for category_id, view in sorted(collection_overview_views.items())
            ),
        )
        now = _utc_now()
        self._project_repository.set_metadata_value(
            key=WORKSPACE_LAYOUT_PREFERENCES_KEY,
            value=dumps(_layout_preferences_payload(preferences), ensure_ascii=False),
            updated_at=now,
        )
        return preferences

    def save_last_opened(
        self,
        *,
        category_id: str | None = None,
        project_id: str | None = None,
        session_id: str | None,
    ) -> WorkspaceLastOpenedState:
        category = _request_category_id(category_id)
        project = None
        normalized_session_id = _request_session_id(session_id)
        if project_id is not None and project_id.strip():
            normalized_project_id = normalize_project_id(project_id)
            project = self._project_repository.get_project(normalized_project_id)
            if project is None:
                raise NotFoundError(f"项目 '{normalized_project_id}' 不存在。")
            if category is not None and category != project.category_id:
                raise BadRequestError("项目不属于指定分类。")
            category = project.category_id
            if normalized_session_id and not self._session_exists(project.project_id, normalized_session_id):
                raise NotFoundError(f"Conversation session '{normalized_session_id}' was not found.")

        if category is None:
            raise BadRequestError("必须提供项目分类或项目。")
        if self._project_repository.get_project_category(category) is None:
            raise NotFoundError(f"项目分类 '{category}' 不存在。")

        now = _utc_now()
        current = self.get_last_opened()
        selections = {
            selection.category_id: selection
            for selection in current.category_selections
        }
        if project is not None:
            selections[category] = WorkspaceCategorySelection(
                category_id=category,
                project_id=project.project_id,
                session_id=normalized_session_id,
                updated_at=now,
            )
        else:
            current_selection = selections.get(category)
            selections[category] = WorkspaceCategorySelection(
                category_id=category,
                project_id=current_selection.project_id if current_selection else None,
                session_id=current_selection.session_id if current_selection else None,
                updated_at=now,
            )

        active_selection = selections[category]
        self._project_repository.set_metadata_value(
            key=WORKSPACE_LAST_OPENED_KEY,
            value=dumps(_state_payload(category, active_selection, selections), ensure_ascii=False),
            updated_at=now,
        )
        return self.get_last_opened()

    def _session_exists(self, project_id: str, session_id: str) -> bool:
        try:
            return self._conversation_service.get_session(project_id, session_id) is not None
        except NotFoundError:
            return False

    def _state_from_payload(self, payload: dict[str, Any]) -> WorkspaceLastOpenedState:
        selections = self._category_selections_from_payload(payload)
        active_category_id = _stored_category_id(payload.get("active_category_id"))
        if active_category_id and self._project_repository.get_project_category(active_category_id) is None:
            active_category_id = None

        fallback = self._selection_from_legacy_payload(payload)
        if fallback and fallback.category_id not in selections:
            selections[fallback.category_id] = fallback

        if active_category_id is None:
            active_category_id = fallback.category_id if fallback else None

        active_selection = selections.get(active_category_id or "") if active_category_id else None
        if active_selection is None and active_category_id:
            active_selection = WorkspaceCategorySelection(
                category_id=active_category_id,
                project_id=None,
                session_id=None,
                updated_at=_optional_text(payload.get("updated_at")),
            )

        return WorkspaceLastOpenedState(
            project_id=active_selection.project_id if active_selection else None,
            category_id=active_selection.category_id if active_selection else None,
            session_id=active_selection.session_id if active_selection else None,
            updated_at=active_selection.updated_at if active_selection else None,
            category_selections=tuple(selections.values()),
        )

    def _category_selections_from_payload(
        self,
        payload: dict[str, Any],
    ) -> dict[str, WorkspaceCategorySelection]:
        raw = payload.get("category_selections")
        if not isinstance(raw, dict):
            return {}

        selections: dict[str, WorkspaceCategorySelection] = {}
        for raw_category_id, raw_selection in raw.items():
            category_id = _stored_category_id(raw_category_id)
            if not category_id or not isinstance(raw_selection, dict):
                continue
            selection = self._selection_from_payload(category_id, raw_selection)
            if selection is not None:
                selections[category_id] = selection
        return selections

    def _selection_from_legacy_payload(
        self,
        payload: dict[str, Any],
    ) -> WorkspaceCategorySelection | None:
        project_id = _stored_project_id(payload.get("project_id"))
        if project_id is None:
            return None
        project = self._project_repository.get_project(project_id)
        if project is None:
            return None
        return self._selection_from_payload(project.category_id, payload)

    def _selection_from_payload(
        self,
        category_id: str,
        payload: dict[str, Any],
    ) -> WorkspaceCategorySelection | None:
        category = self._project_repository.get_project_category(category_id)
        if category is None:
            return None

        project_id = _stored_project_id(payload.get("project_id"))
        if project_id is None:
            return WorkspaceCategorySelection(
                category_id=category_id,
                project_id=None,
                session_id=None,
                updated_at=_optional_text(payload.get("updated_at")),
            )

        project = self._project_repository.get_project(project_id)
        if project is None or project.category_id != category_id:
            return None

        session_id = _stored_session_id(payload.get("session_id"))
        if session_id and not self._session_exists(project.project_id, session_id):
            session_id = None

        return WorkspaceCategorySelection(
            category_id=category_id,
            project_id=project.project_id,
            session_id=session_id,
            updated_at=_optional_text(payload.get("updated_at")),
        )


def _empty_last_opened() -> WorkspaceLastOpenedState:
    return WorkspaceLastOpenedState(
        project_id=None,
        category_id=None,
        session_id=None,
        updated_at=None,
    )


def _parse_last_opened_payload(raw: str) -> dict[str, Any] | None:
    return _parse_json_object(raw)


def _parse_json_object(raw: str) -> dict[str, Any] | None:
    try:
        payload = loads(raw)
    except (TypeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _default_layout_preferences() -> WorkspaceLayoutPreferences:
    return WorkspaceLayoutPreferences(
        side_panel_width=DEFAULT_SIDE_PANEL_WIDTH,
        ai_panel_width=DEFAULT_AI_PANEL_WIDTH,
        composer_height=DEFAULT_COMPOSER_HEIGHT,
        project_overview_layouts=(),
        project_overview_maximized=(),
        project_overview_views=(),
        tool_overview_views=(),
        collection_overview_views=(),
    )


def _layout_preferences_from_payload(payload: dict[str, Any]) -> WorkspaceLayoutPreferences:
    project_overview_maximized = _project_overview_maximized_from_payload(
        payload.get("project_overview_maximized_project_ids"),
    )
    project_overview_views = _project_overview_views_from_payload(
        payload.get("project_overview_views"),
    )
    if "project_overview_views" not in payload:
        project_overview_views = tuple(
            WorkspaceProjectOverviewView(
                category_id=item.category_id,
                view="conversation",
            )
            for item in project_overview_maximized
        )
    return WorkspaceLayoutPreferences(
        side_panel_width=_clamp_int(
            payload.get("side_panel_width"),
            DEFAULT_SIDE_PANEL_WIDTH,
            MIN_SIDE_PANEL_WIDTH,
            MAX_SIDE_PANEL_WIDTH,
        ),
        ai_panel_width=_clamp_int(
            payload.get("ai_panel_width"),
            DEFAULT_AI_PANEL_WIDTH,
            MIN_AI_PANEL_WIDTH,
            MAX_AI_PANEL_WIDTH,
        ),
        composer_height=_clamp_int(
            payload.get("composer_height"),
            DEFAULT_COMPOSER_HEIGHT,
            MIN_COMPOSER_HEIGHT,
            MAX_COMPOSER_HEIGHT,
        ),
        project_overview_layouts=_project_overview_layouts_from_payload(
            payload.get("project_overview_layout_modes"),
        ),
        project_overview_maximized=project_overview_maximized,
        project_overview_views=project_overview_views,
        tool_overview_views=_tool_overview_views_from_payload(
            payload.get("tool_overview_views"),
        ),
        collection_overview_views=_collection_overview_views_from_payload(
            payload.get("collection_overview_views"),
        ),
    )


def _layout_preferences_payload(preferences: WorkspaceLayoutPreferences) -> dict[str, Any]:
    return {
        "version": 6,
        "side_panel_width": preferences.side_panel_width,
        "ai_panel_width": preferences.ai_panel_width,
        "composer_height": preferences.composer_height,
        "project_overview_layout_modes": {
            item.category_id: item.layout_mode
            for item in preferences.project_overview_layouts
        },
        "project_overview_maximized_project_ids": {
            item.category_id: item.project_id
            for item in preferences.project_overview_maximized
        },
        "project_overview_views": {
            item.category_id: item.view
            for item in preferences.project_overview_views
        },
        "tool_overview_views": {
            item.category_id: item.view
            for item in preferences.tool_overview_views
        },
        "collection_overview_views": {
            item.category_id: item.view
            for item in preferences.collection_overview_views
        },
    }


def _project_overview_layouts_from_payload(
    value: Any,
) -> tuple[WorkspaceProjectOverviewLayout, ...]:
    if not isinstance(value, dict):
        return ()
    layouts: list[WorkspaceProjectOverviewLayout] = []
    for raw_category_id, layout_mode in sorted(value.items()):
        category_id = _stored_category_id(raw_category_id)
        if (
            category_id is None
            or not isinstance(layout_mode, str)
            or layout_mode not in PROJECT_OVERVIEW_LAYOUT_MODES
        ):
            continue
        layouts.append(
            WorkspaceProjectOverviewLayout(
                category_id=category_id,
                layout_mode=layout_mode,
            ),
        )
    return tuple(layouts)


def _project_overview_maximized_from_payload(
    value: Any,
) -> tuple[WorkspaceProjectOverviewMaximized, ...]:
    if not isinstance(value, dict):
        return ()
    maximized: list[WorkspaceProjectOverviewMaximized] = []
    for raw_category_id, raw_project_id in sorted(value.items()):
        category_id = _stored_category_id(raw_category_id)
        project_id = _stored_project_id(raw_project_id)
        if category_id is None or project_id is None:
            continue
        maximized.append(
            WorkspaceProjectOverviewMaximized(
                category_id=category_id,
                project_id=project_id,
            ),
        )
    return tuple(maximized)


def _project_overview_views_from_payload(
    value: Any,
) -> tuple[WorkspaceProjectOverviewView, ...]:
    if not isinstance(value, dict):
        return ()
    views: list[WorkspaceProjectOverviewView] = []
    for raw_category_id, raw_view in sorted(value.items()):
        category_id = _stored_category_id(raw_category_id)
        if (
            category_id is None
            or not isinstance(raw_view, str)
            or raw_view not in PROJECT_OVERVIEW_VIEWS
        ):
            continue
        views.append(
            WorkspaceProjectOverviewView(
                category_id=category_id,
                view=_persisted_project_overview_view(raw_view),
            ),
        )
    return tuple(views)


def _tool_overview_views_from_payload(
    value: Any,
) -> tuple[WorkspaceToolOverviewView, ...]:
    if not isinstance(value, dict):
        return ()
    views: list[WorkspaceToolOverviewView] = []
    for raw_category_id, raw_view in sorted(value.items()):
        category_id = _stored_category_id(raw_category_id)
        if (
            category_id is None
            or not isinstance(raw_view, str)
            or raw_view not in TOOL_OVERVIEW_VIEWS
        ):
            continue
        views.append(
            WorkspaceToolOverviewView(
                category_id=category_id,
                view=_persisted_tool_overview_view(raw_view),
            ),
        )
    return tuple(views)


def _persisted_project_overview_view(view: str) -> str:
    return "projects" if view == "branches" else view


def _persisted_tool_overview_view(view: str) -> str:
    return "tools" if view == "branches" else view


def _collection_overview_views_from_payload(
    value: Any,
) -> tuple[WorkspaceCollectionOverviewView, ...]:
    if not isinstance(value, dict):
        return ()
    views: list[WorkspaceCollectionOverviewView] = []
    for raw_category_id, raw_view in sorted(value.items()):
        category_id = _stored_category_id(raw_category_id)
        if (
            category_id is None
            or not isinstance(raw_view, str)
            or raw_view not in COLLECTION_OVERVIEW_VIEWS
        ):
            continue
        views.append(
            WorkspaceCollectionOverviewView(
                category_id=category_id,
                view=raw_view,
            ),
        )
    return tuple(views)


def _clamp_int(value: Any, default: int, min_value: int, max_value: int) -> int:
    if isinstance(value, bool):
        candidate = default
    elif isinstance(value, int):
        candidate = value
    elif isinstance(value, float) and value.is_integer():
        candidate = int(value)
    else:
        candidate = default
    return min(max(candidate, min_value), max_value)


def _stored_project_id(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        return normalize_project_id(value)
    except BadRequestError:
        return None


def _stored_category_id(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _stored_session_id(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized or not fullmatch(r"[A-Za-z0-9_-]+", normalized):
        return None
    return normalized


def _request_category_id(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _request_session_id(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if not fullmatch(r"[A-Za-z0-9_-]+", normalized):
        raise BadRequestError("Conversation session id is invalid.")
    return normalized


def _optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _state_payload(
    active_category_id: str,
    active_selection: WorkspaceCategorySelection,
    selections: dict[str, WorkspaceCategorySelection],
) -> dict:
    return {
        "active_category_id": active_category_id,
        "project_id": active_selection.project_id,
        "session_id": active_selection.session_id,
        "updated_at": active_selection.updated_at,
        "category_selections": {
            category_id: {
                "project_id": selection.project_id,
                "session_id": selection.session_id,
                "updated_at": selection.updated_at,
            }
            for category_id, selection in selections.items()
        },
    }


@lru_cache
def get_workspace_state_service() -> WorkspaceStateService:
    return WorkspaceStateService(
        get_project_repository(),
        get_project_conversation_service(),
    )
