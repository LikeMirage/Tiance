from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Query

from app.schemas.global_memory import (
    GlobalMemoryEventListResponse,
    GlobalMemoryEventResponse,
    GlobalMemoryOperationRequest,
    GlobalMemoryOperationResponse,
    GlobalMemoryRecordListResponse,
    GlobalMemoryRecordResponse,
)
from app.services.project import get_project_memory_management_service


router = APIRouter(prefix="/memory/global", tags=["memory"])


@router.get(
    "/records",
    response_model=GlobalMemoryRecordListResponse,
    summary="List active or deleted global memory records",
)
def list_global_memory_records(
    status: Literal["active", "deleted", "all"] = Query(default="active"),
    query: str = Query(default=""),
    page: int | None = Query(default=None, ge=1),
    page_size: int = Query(default=50, ge=1),
) -> GlobalMemoryRecordListResponse:
    report = get_project_memory_management_service().list_memory_records(
        scope="global",
        status=status,
        query=query,
        page=page,
        page_size=page_size,
    )
    return GlobalMemoryRecordListResponse(**{
        **report,
        "items": [GlobalMemoryRecordResponse(**item) for item in report["items"]],
    })


@router.get(
    "/events",
    response_model=GlobalMemoryEventListResponse,
    summary="List the complete global memory event log",
)
def list_global_memory_events(
    query: str = Query(default=""),
    page: int | None = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1),
) -> GlobalMemoryEventListResponse:
    report = get_project_memory_management_service().list_memory_events(
        scope="global",
        query=query,
        page=page,
        page_size=page_size,
    )
    return GlobalMemoryEventListResponse(**{
        **report,
        "items": [GlobalMemoryEventResponse(**item) for item in report["items"]],
    })


@router.post(
    "/operations",
    response_model=GlobalMemoryOperationResponse,
    summary="Append a manual global memory operation",
)
def apply_global_memory_operation(
    payload: GlobalMemoryOperationRequest,
) -> GlobalMemoryOperationResponse:
    service = get_project_memory_management_service()
    result = service.apply_operation(
        scope="global",
        operation=payload.operation,
        memory_id=payload.memory_id,
        content=payload.content,
        keywords=payload.keywords,
        reason=payload.reason,
    )
    status = "deleted" if payload.operation == "delete" else "active"
    report = service.list_memory_records(scope="global", status=status)
    memory = _find_record(report["items"], result["memory_id"])
    if memory is None:
        raise RuntimeError("The committed global memory event has no record projection.")
    return GlobalMemoryOperationResponse(
        operation=payload.operation,
        memory_id=result["memory_id"],
        memory=GlobalMemoryRecordResponse(**memory),
    )


def _find_record(items: list[dict], memory_id: str) -> dict | None:
    for item in items:
        if item.get("id") == memory_id:
            return item
    return None
