import json

from fastapi import APIRouter, Query, Response, status
from fastapi.responses import StreamingResponse

from app.schemas.project import (
    ProjectCategoryAssignRequest,
    ProjectCategoryCreateRequest,
    ProjectCategoryListResponse,
    ProjectCategoryOverviewResponse,
    ProjectCategoryRenameRequest,
    ProjectCategoryResponse,
    ProjectCreateRequest,
    ProjectListResponse,
    ProjectOrderResponse,
    ProjectOrderSaveRequest,
    ProjectOverviewItemResponse,
    ProjectRenameRequest,
    ProjectResponse,
    RoleCatalogCategoryResponse,
    RoleCatalogItemResponse,
    RoleCatalogResponse,
    RoleProjectCreateRequest,
)
from app.services.application.project_creation import (
    get_project_creation_application_service,
)
from app.services.application.project_category_deletion import (
    get_project_category_deletion_application_service,
)
from app.services.application.theme_project_policy import (
    ensure_theme_project_can_be_deleted,
)
from app.services.application.role_configuration import (
    get_role_configuration_application_service,
)
from app.services.project import get_project_service
from app.services.project.project_category_overview import (
    get_project_category_overview_service,
)
from app.services.project.project_workspace_watcher import (
    get_project_workspace_event_broker,
)

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("/events", summary="Watch ordinary project workspace changes")
async def watch_project_events() -> StreamingResponse:
    changes = get_project_workspace_event_broker().subscribe()

    async def event_generator():
        yield _sse_event({"kind": "ready"})
        async for paths in changes:
            yield _sse_event({"kind": "changed", "paths": paths})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("", response_model=ProjectListResponse, summary="List projects")
def list_projects() -> ProjectListResponse:
    service = get_project_service()
    items = [_project_response(service, project) for project in service.list_projects()]
    return ProjectListResponse(count=len(items), items=items)


@router.post(
    "",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a project",
)
def create_project(payload: ProjectCreateRequest) -> ProjectResponse:
    service = get_project_service()
    creation_service = get_project_creation_application_service()
    project = creation_service.create_project(
        name=payload.name,
        root_path=payload.root_path,
        category_id=payload.category_id,
        project_kind=payload.project_kind,
    )
    return _project_response(service, project)


@router.post(
    "/roles",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a role workspace",
)
def create_role_project(payload: RoleProjectCreateRequest) -> ProjectResponse:
    service = get_project_service()
    creation_service = get_project_creation_application_service()
    project = creation_service.create_role_project(
        name=payload.name,
        category_id=payload.category_id,
    )
    return _project_response(service, project)


@router.get(
    "/roles/catalog",
    response_model=RoleCatalogResponse,
    summary="List conversation roles",
)
def list_conversation_roles() -> RoleCatalogResponse:
    service = get_project_service()
    catalog = get_role_configuration_application_service().get_catalog()
    return RoleCatalogResponse(
        default_role_project_id=catalog.default_role_project_id,
        categories=[
            RoleCatalogCategoryResponse(
                category_id=category.category_id,
                name=category.name,
                sort_order=category.sort_order,
            )
            for category in catalog.categories
        ],
        roles=[
            RoleCatalogItemResponse(
                role_project_id=item.project.project_id,
                name=item.project.name,
                category_id=item.project.category_id,
                description=item.description,
                is_default=item.is_default,
                sort_order=item.project.sort_order,
            )
            for item in catalog.roles
        ],
    )


@router.get(
    "/categories",
    response_model=ProjectCategoryListResponse,
    summary="List project categories",
)
def list_project_categories() -> ProjectCategoryListResponse:
    service = get_project_service()
    items = [
        ProjectCategoryResponse.from_domain(category)
        for category in service.list_project_categories()
    ]
    return ProjectCategoryListResponse(count=len(items), items=items)


@router.post(
    "/categories",
    response_model=ProjectCategoryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a project category",
)
def create_project_category(payload: ProjectCategoryCreateRequest) -> ProjectCategoryResponse:
    service = get_project_service()
    category = service.create_project_category(
        name=payload.name,
        category_kind=payload.category_kind,
    )
    return ProjectCategoryResponse.from_domain(category)


@router.get(
    "/categories/{category_id}/overview",
    response_model=ProjectCategoryOverviewResponse,
    summary="Get project category overview",
)
def get_project_category_overview(category_id: str) -> ProjectCategoryOverviewResponse:
    service = get_project_category_overview_service()
    overview = service.get_category_overview(category_id)
    return ProjectCategoryOverviewResponse.from_domain(overview)


@router.get(
    "/{project_id}/overview",
    response_model=ProjectOverviewItemResponse,
    summary="Get project conversation overview",
)
def get_project_overview(project_id: str) -> ProjectOverviewItemResponse:
    service = get_project_category_overview_service()
    overview = service.get_project_overview(project_id)
    return ProjectOverviewItemResponse.from_domain(overview)


@router.patch(
    "/categories/{category_id}",
    response_model=ProjectCategoryResponse,
    summary="Rename a project category",
)
def rename_project_category(
    category_id: str,
    payload: ProjectCategoryRenameRequest,
) -> ProjectCategoryResponse:
    service = get_project_service()
    category = service.rename_project_category(category_id, name=payload.name)
    return ProjectCategoryResponse.from_domain(category)


@router.delete(
    "/categories/{category_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a project category",
)
def delete_project_category(category_id: str) -> Response:
    service = get_project_category_deletion_application_service()
    service.delete_category(category_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch(
    "/{project_id}",
    response_model=ProjectResponse,
    summary="Rename a project",
)
def rename_project(project_id: str, payload: ProjectRenameRequest) -> ProjectResponse:
    service = get_project_service()
    project = service.rename_project(project_id, name=payload.name)
    return _project_response(service, project)


@router.patch(
    "/{project_id}/category",
    response_model=ProjectResponse,
    summary="Move a project to another category",
)
def move_project_to_category(
    project_id: str,
    payload: ProjectCategoryAssignRequest,
) -> ProjectResponse:
    service = get_project_service()
    project = service.move_project_to_category(project_id, category_id=payload.category_id)
    return _project_response(service, project)


@router.delete(
    "/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a project",
)
def delete_project(
    project_id: str,
    delete_files: bool = Query(False, description="Delete imported project files from disk"),
) -> Response:
    service = get_project_service()
    current = service.get_project(project_id)
    if current is not None:
        ensure_theme_project_can_be_deleted(current)
    service.delete_project(project_id, delete_files=delete_files)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/order", response_model=ProjectOrderResponse, summary="Get project order")
def get_project_order() -> ProjectOrderResponse:
    service = get_project_service()
    ids = service.get_project_order()
    return ProjectOrderResponse(count=len(ids), project_ids=list(ids))


@router.put("/order", response_model=ProjectOrderResponse, summary="Save project order")
def save_project_order(payload: ProjectOrderSaveRequest) -> ProjectOrderResponse:
    service = get_project_service()
    ids = service.save_project_order(tuple(payload.project_ids))
    return ProjectOrderResponse(count=len(ids), project_ids=list(ids))


def _project_response(service, project) -> ProjectResponse:
    return ProjectResponse.from_domain(
        project,
        is_managed=service.is_managed_project(project),
    )


def _sse_event(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
