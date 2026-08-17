from __future__ import annotations

from fastapi import APIRouter, Query

from app.schemas.project import (
    ProjectMemoryItemResponse,
    ProjectMemoryListResponse,
    ProjectMemoryOperationRequest,
    ProjectMemoryOperationResponse,
)
from app.services.project import get_project_memory_management_service

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get(
    "/{project_id}/memory",
    response_model=ProjectMemoryListResponse,
    summary="List project or global long-term memories",
)
def list_project_memory(
    project_id: str,
    scope: str = Query(default="project", pattern="^(project|global)$"),
    query: str = Query(default=""),
    page: int | None = Query(default=None, ge=1),
    page_size: int = Query(default=50, ge=1),
) -> ProjectMemoryListResponse:
    service = get_project_memory_management_service()
    report = service.list_memory_records(
        scope=scope,
        project_id=project_id,
        query=query,
        page=page,
        page_size=page_size,
    )
    return ProjectMemoryListResponse(
        project_id=project_id,
        scope=report["scope"],
        count=report["count"],
        total_count=report["total_count"],
        page=report["page"],
        page_size=report["page_size"],
        total_pages=report["total_pages"],
        has_previous=report["has_previous"],
        has_next=report["has_next"],
        items=[ProjectMemoryItemResponse(**item) for item in report["items"]],
    )


@router.post(
    "/{project_id}/memory/operations",
    response_model=ProjectMemoryOperationResponse,
    summary="Apply a controlled long-term memory operation",
)
def apply_project_memory_operation(
    project_id: str,
    payload: ProjectMemoryOperationRequest,
) -> ProjectMemoryOperationResponse:
    service = get_project_memory_management_service()
    result = service.apply_operation(
        scope=payload.scope,
        operation=payload.operation,
        project_id=project_id,
        memory_id=payload.memory_id,
        content=payload.content,
        keywords=payload.keywords,
        reason=payload.reason,
    )
    report = service.list_memory_records(scope=payload.scope, project_id=project_id)
    memory = _find_item(report["items"], result["memory_id"])
    return ProjectMemoryOperationResponse(
        project_id=project_id,
        scope=result["scope"],
        operation=result["operation"],
        memory_id=result["memory_id"],
        memory=ProjectMemoryItemResponse(**memory) if memory is not None else None,
        items=[ProjectMemoryItemResponse(**item) for item in report["items"]],
    )


def _find_item(items: list[dict], memory_id: str) -> dict | None:
    for item in items:
        if item.get("id") == memory_id:
            return item
    return None
