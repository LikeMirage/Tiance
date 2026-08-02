from fastapi import APIRouter, status

from app.schemas.tools import (
    ToolDependencyInstallTaskResponse,
    ToolDependencyInstallRequest,
    ToolDependencyInstallResponse,
    ToolDependencyListResponse,
    ToolDependencyUninstallRequest,
    ToolDependencyUninstallResponse,
)
from app.services.tools import get_tool_dependency_service, get_tool_dependency_task_service

router = APIRouter(prefix="/tools/categories", tags=["tools"])


@router.get(
    "/{category_id}/projects/{project_id}/dependencies",
    response_model=ToolDependencyListResponse,
    summary="List tool folder dependencies",
)
def list_tool_folder_dependencies(
    category_id: str,
    project_id: str,
) -> ToolDependencyListResponse:
    service = get_tool_dependency_service()
    report = service.list_dependencies(category_id, project_id)
    return ToolDependencyListResponse.from_domain(report)


@router.post(
    "/{category_id}/projects/{project_id}/dependencies/install",
    response_model=ToolDependencyInstallResponse,
    summary="Install tool folder dependencies",
)
def install_tool_folder_dependencies(
    category_id: str,
    project_id: str,
    payload: ToolDependencyInstallRequest,
) -> ToolDependencyInstallResponse:
    service = get_tool_dependency_service()
    result = service.install_dependencies(
        category_id,
        project_id,
        requirement=payload.requirement,
        index_url=payload.index_url,
    )
    return ToolDependencyInstallResponse.from_domain(result)


@router.post(
    "/{category_id}/projects/{project_id}/dependencies/install-tasks",
    response_model=ToolDependencyInstallTaskResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start a tool dependency install task",
)
def start_tool_folder_dependency_install_task(
    category_id: str,
    project_id: str,
    payload: ToolDependencyInstallRequest,
) -> ToolDependencyInstallTaskResponse:
    service = get_tool_dependency_task_service()
    task = service.start_install_task(
        category_id,
        project_id,
        requirement=payload.requirement,
        index_url=payload.index_url,
    )
    return ToolDependencyInstallTaskResponse.from_domain(task)


@router.get(
    "/dependency-install-tasks/{task_id}",
    response_model=ToolDependencyInstallTaskResponse,
    summary="Get a tool dependency install task",
)
def get_tool_dependency_install_task(task_id: str) -> ToolDependencyInstallTaskResponse:
    service = get_tool_dependency_task_service()
    return ToolDependencyInstallTaskResponse.from_domain(service.get_task(task_id))


@router.post(
    "/{category_id}/projects/{project_id}/dependencies/uninstall",
    response_model=ToolDependencyUninstallResponse,
    summary="Uninstall a tool folder dependency",
)
def uninstall_tool_folder_dependency(
    category_id: str,
    project_id: str,
    payload: ToolDependencyUninstallRequest,
) -> ToolDependencyUninstallResponse:
    service = get_tool_dependency_service()
    result = service.uninstall_dependency(
        category_id,
        project_id,
        requirement=payload.requirement,
    )
    return ToolDependencyUninstallResponse.from_domain(result)
