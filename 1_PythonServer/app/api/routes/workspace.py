from fastapi import APIRouter

from app.schemas.workspace import (
    WorkspaceActivitySummaryResponse,
    WorkspaceLayoutPreferencesResponse,
    WorkspaceLayoutPreferencesSaveRequest,
    WorkspaceLastOpenedResponse,
    WorkspaceLastOpenedSaveRequest,
)
from app.services.workspace_state import get_workspace_state_service
from app.services.workspace_activity import (
    get_workspace_activity_management_service,
    get_workspace_activity_service,
)

router = APIRouter(prefix="/workspace", tags=["workspace"])


@router.get(
    "/activity-summary",
    response_model=WorkspaceActivitySummaryResponse,
    summary="Get cumulative workspace activity",
)
def get_workspace_activity_summary() -> WorkspaceActivitySummaryResponse:
    activity_service = get_workspace_activity_service()
    return WorkspaceActivitySummaryResponse(
        conversation_count=activity_service.get_conversation_count(),
        sent_message_count=activity_service.get_sent_message_count(),
        ai_runtime_ms=activity_service.get_ai_runtime_ms(),
    )


@router.post(
    "/activity-summary/conversation-count/clear",
    response_model=WorkspaceActivitySummaryResponse,
    summary="Clear cumulative conversation count",
)
def clear_workspace_conversation_count() -> WorkspaceActivitySummaryResponse:
    activity_service = get_workspace_activity_service()
    return WorkspaceActivitySummaryResponse(
        conversation_count=get_workspace_activity_management_service().clear_conversation_count(),
        sent_message_count=activity_service.get_sent_message_count(),
        ai_runtime_ms=activity_service.get_ai_runtime_ms(),
    )


@router.post(
    "/activity-summary/conversation-count/sync-current",
    response_model=WorkspaceActivitySummaryResponse,
    summary="Synchronize cumulative conversation count with current sessions",
)
def synchronize_workspace_conversation_count() -> WorkspaceActivitySummaryResponse:
    activity_service = get_workspace_activity_service()
    return WorkspaceActivitySummaryResponse(
        conversation_count=(
            get_workspace_activity_management_service().synchronize_conversation_count()
        ),
        sent_message_count=activity_service.get_sent_message_count(),
        ai_runtime_ms=activity_service.get_ai_runtime_ms(),
    )


@router.get(
    "/last-opened",
    response_model=WorkspaceLastOpenedResponse,
    summary="Get last opened workspace selection",
)
def get_workspace_last_opened() -> WorkspaceLastOpenedResponse:
    service = get_workspace_state_service()
    return WorkspaceLastOpenedResponse.from_domain(service.get_last_opened())


@router.put(
    "/last-opened",
    response_model=WorkspaceLastOpenedResponse,
    summary="Save last opened workspace selection",
)
def save_workspace_last_opened(
    payload: WorkspaceLastOpenedSaveRequest,
) -> WorkspaceLastOpenedResponse:
    service = get_workspace_state_service()
    return WorkspaceLastOpenedResponse.from_domain(
        service.save_last_opened(
            category_id=payload.category_id,
            project_id=payload.project_id,
            session_id=payload.session_id,
        ),
    )


@router.get(
    "/layout-preferences",
    response_model=WorkspaceLayoutPreferencesResponse,
    summary="Get workspace layout preferences",
)
def get_workspace_layout_preferences() -> WorkspaceLayoutPreferencesResponse:
    service = get_workspace_state_service()
    return WorkspaceLayoutPreferencesResponse.from_domain(service.get_layout_preferences())


@router.put(
    "/layout-preferences",
    response_model=WorkspaceLayoutPreferencesResponse,
    summary="Save workspace layout preferences",
)
def save_workspace_layout_preferences(
    payload: WorkspaceLayoutPreferencesSaveRequest,
) -> WorkspaceLayoutPreferencesResponse:
    service = get_workspace_state_service()
    project_overview_layout = payload.project_overview_layout
    project_overview_maximized = payload.project_overview_maximized
    project_overview_view = payload.project_overview_view
    tool_overview_view = payload.tool_overview_view
    collection_overview_view = payload.collection_overview_view
    return WorkspaceLayoutPreferencesResponse.from_domain(
        service.save_layout_preferences(
            side_panel_width=payload.side_panel_width,
            ai_panel_width=payload.ai_panel_width,
            composer_height=payload.composer_height,
            project_overview_category_id=(
                project_overview_layout.category_id
                if project_overview_layout is not None
                else None
            ),
            project_overview_layout_mode=(
                project_overview_layout.layout_mode
                if project_overview_layout is not None
                else None
            ),
            project_overview_maximized_category_id=(
                project_overview_maximized.category_id
                if project_overview_maximized is not None
                else None
            ),
            project_overview_maximized_project_id=(
                project_overview_maximized.project_id
                if project_overview_maximized is not None
                else None
            ),
            update_project_overview_maximized=project_overview_maximized is not None,
            project_overview_view_category_id=(
                project_overview_view.category_id
                if project_overview_view is not None
                else None
            ),
            project_overview_view=(
                project_overview_view.view
                if project_overview_view is not None
                else None
            ),
            tool_overview_view_category_id=(
                tool_overview_view.category_id
                if tool_overview_view is not None
                else None
            ),
            tool_overview_view=(
                tool_overview_view.view
                if tool_overview_view is not None
                else None
            ),
            collection_overview_view_category_id=(
                collection_overview_view.category_id
                if collection_overview_view is not None
                else None
            ),
            collection_overview_view=(
                collection_overview_view.view
                if collection_overview_view is not None
                else None
            ),
        ),
    )
