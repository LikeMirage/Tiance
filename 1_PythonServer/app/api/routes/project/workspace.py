from fastapi import APIRouter

from app.schemas.project import (
    ProjectWorkspaceStatePatchRequest,
    ProjectWorkspaceStateResponse,
    ProjectWorkspaceStateSaveRequest,
    ProjectWorkspaceTabsActionRequest,
    ProjectWorkspaceTabsActionResponse,
)
from app.core.errors import AppError
from app.services.project import get_project_file_service, get_project_workspace_service

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get(
    "/{project_id}/workspace-state",
    response_model=ProjectWorkspaceStateResponse,
    summary="Get workspace state for a project",
)
def get_project_workspace_state(project_id: str) -> ProjectWorkspaceStateResponse:
    service = get_project_workspace_service()
    state = service.get_state(project_id)
    if state is None:
        return ProjectWorkspaceStateResponse(project_id=project_id)
    return ProjectWorkspaceStateResponse(
        project_id=project_id,
        expanded_paths=state.get("expanded_paths", []),
        open_file_paths=state.get("open_file_paths", []),
        active_file_path=state.get("active_file_path"),
        active_dashboard=state.get("active_dashboard"),
    )


@router.put(
    "/{project_id}/workspace-state",
    response_model=ProjectWorkspaceStateResponse,
    summary="Save workspace state for a project",
)
def save_project_workspace_state(
    project_id: str,
    payload: ProjectWorkspaceStateSaveRequest,
) -> ProjectWorkspaceStateResponse:
    service = get_project_workspace_service()
    state = service.save_state(
        project_id,
        expanded_paths=payload.expanded_paths,
        open_file_paths=payload.open_file_paths,
        active_file_path=payload.active_file_path,
        active_dashboard=payload.active_dashboard,
    )
    return ProjectWorkspaceStateResponse(project_id=project_id, **state)


@router.patch(
    "/{project_id}/workspace-state",
    response_model=ProjectWorkspaceStateResponse,
    summary="Patch workspace state for a project",
)
def patch_project_workspace_state(
    project_id: str,
    payload: ProjectWorkspaceStatePatchRequest,
) -> ProjectWorkspaceStateResponse:
    service = get_project_workspace_service()
    state = service.patch_state(
        project_id,
        expanded_paths=payload.expanded_paths,
        should_update_expanded_paths="expanded_paths" in payload.model_fields_set,
        open_file_paths=payload.open_file_paths,
        should_update_open_file_paths="open_file_paths" in payload.model_fields_set,
        active_file_path=payload.active_file_path,
        should_update_active_file_path="active_file_path" in payload.model_fields_set,
        active_dashboard=payload.active_dashboard,
        should_update_active_dashboard="active_dashboard" in payload.model_fields_set,
    )
    return ProjectWorkspaceStateResponse(project_id=project_id, **state)


@router.post(
    "/{project_id}/workspace-state/editor-tabs",
    response_model=ProjectWorkspaceTabsActionResponse,
    summary="Apply an editor tab action to an unloaded project workspace",
)
def apply_project_workspace_tabs_action(
    project_id: str,
    payload: ProjectWorkspaceTabsActionRequest,
) -> ProjectWorkspaceTabsActionResponse:
    file_service = get_project_file_service()
    if payload.action == "open_file" and payload.path:
        file_service.get_file_path(project_id, payload.path)

    state = get_project_workspace_service().apply_editor_tabs_action(
        project_id,
        action=payload.action,
        path=payload.path,
        paths=payload.paths,
    )
    missing_file_paths: list[str] = []
    for file_path in state["open_file_paths"]:
        try:
            file_service.get_file_path(project_id, file_path)
        except AppError:
            missing_file_paths.append(file_path)

    return ProjectWorkspaceTabsActionResponse(
        project_id=project_id,
        **state,
        missing_file_paths=missing_file_paths,
    )
