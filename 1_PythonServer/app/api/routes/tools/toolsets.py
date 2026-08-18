from fastapi import APIRouter, status

from app.schemas.tools import (
    ToolFolderCreateRequest,
    ToolFolderRuntimeSettingsRequest,
    ToolFolderRuntimeSettingsResponse,
    ToolFolderListResponse,
    ToolFolderMoveRequest,
    ToolFolderRenameRequest,
    ToolFolderResponse,
    ToolsetCreateRequest,
    ToolsetListResponse,
    ToolsetRenameRequest,
    ToolsetResponse,
)
from app.services.tools import get_toolset_service

router = APIRouter(prefix="/tools/categories", tags=["tools"])


@router.get("", response_model=ToolsetListResponse, summary="List tool categories")
def list_tool_categories() -> ToolsetListResponse:
    items = [
        ToolsetResponse.from_domain(category)
        for category in get_toolset_service().list_toolsets()
    ]
    return ToolsetListResponse(count=len(items), items=items)


@router.post("", response_model=ToolsetResponse, status_code=status.HTTP_201_CREATED)
def create_tool_category(payload: ToolsetCreateRequest) -> ToolsetResponse:
    return ToolsetResponse.from_domain(get_toolset_service().create_toolset(name=payload.name))


@router.patch("/{category_id}", response_model=ToolsetResponse)
def rename_tool_category(category_id: str, payload: ToolsetRenameRequest) -> ToolsetResponse:
    return ToolsetResponse.from_domain(
        get_toolset_service().rename_toolset(category_id, name=payload.name)
    )


@router.delete("/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tool_category(category_id: str) -> None:
    get_toolset_service().delete_toolset(category_id)


@router.get("/{category_id}/projects", response_model=ToolFolderListResponse)
def list_tool_projects(category_id: str) -> ToolFolderListResponse:
    items = [
        ToolFolderResponse.from_domain(project)
        for project in get_toolset_service().list_tool_folders(category_id)
    ]
    return ToolFolderListResponse(count=len(items), items=items)


@router.post(
    "/{category_id}/projects",
    response_model=ToolFolderResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_tool_project(
    category_id: str,
    payload: ToolFolderCreateRequest,
) -> ToolFolderResponse:
    return ToolFolderResponse.from_domain(
        get_toolset_service().create_tool_folder(category_id, name=payload.name)
    )


@router.patch("/{category_id}/projects/{project_id}", response_model=ToolFolderResponse)
def rename_tool_project(
    category_id: str,
    project_id: str,
    payload: ToolFolderRenameRequest,
) -> ToolFolderResponse:
    return ToolFolderResponse.from_domain(
        get_toolset_service().rename_tool_folder(category_id, project_id, name=payload.name)
    )


@router.delete(
    "/{category_id}/projects/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_tool_project(category_id: str, project_id: str) -> None:
    get_toolset_service().delete_tool_folder(category_id, project_id)


@router.patch(
    "/{category_id}/projects/{project_id}/category",
    response_model=ToolFolderResponse,
)
def move_tool_project(
    category_id: str,
    project_id: str,
    payload: ToolFolderMoveRequest,
) -> ToolFolderResponse:
    return ToolFolderResponse.from_domain(
        get_toolset_service().move_tool_folder(
            category_id,
            project_id,
            target_category_id=payload.target_category_id,
        )
    )


@router.patch(
    "/{category_id}/projects/{project_id}/runtime-settings",
    response_model=ToolFolderRuntimeSettingsResponse,
)
def set_tool_project_runtime_settings(
    category_id: str,
    project_id: str,
    payload: ToolFolderRuntimeSettingsRequest,
) -> ToolFolderRuntimeSettingsResponse:
    result = get_toolset_service().set_tool_folder_runtime_settings(
        category_id,
        project_id,
        enabled=payload.enabled,
        dynamic=payload.dynamic,
        parallel=payload.parallel,
    )
    return ToolFolderRuntimeSettingsResponse(
        category_id=result.folder.category_id,
        project_id=result.folder.project_id,
        enabled=result.enabled,
        dynamic=result.dynamic,
        parallel=result.parallel,
        updated_at=result.folder.updated_at,
    )


@router.post(
    "/{category_id}/projects/{project_id}/reveal",
    status_code=status.HTTP_204_NO_CONTENT,
)
def reveal_tool_project(category_id: str, project_id: str) -> None:
    get_toolset_service().reveal_tool_folder(category_id, project_id)
