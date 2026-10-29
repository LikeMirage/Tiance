from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from app.domain.tools.call_record_page import ToolCallRecordSnapshotExpired
from app.schemas.tools.tool_call_records import ToolCallRecordListItemResponse

from app.schemas.tools import (
    ToolCallRecordListResponse,
    ToolCallRecordOverviewResponse,
    ToolCallRecordResponse,
    ToolCallRecordSummaryResponse,
)
from app.services.tools import get_tool_call_record_service

router = APIRouter(prefix="/tools", tags=["tools"])


@router.get("/call-record-summary", response_model=ToolCallRecordOverviewResponse)
def summarize_all_tool_call_records() -> ToolCallRecordOverviewResponse:
    return ToolCallRecordOverviewResponse.from_domain(
        get_tool_call_record_service().summarize_global_records()
    )


@router.get(
    "/categories/{category_id}/call-record-summary",
    response_model=ToolCallRecordSummaryResponse,
)
def summarize_tool_category_call_records(category_id: str) -> ToolCallRecordSummaryResponse:
    return ToolCallRecordSummaryResponse.from_domain(
        get_tool_call_record_service().summarize_category_records(category_id)
    )


@router.get(
    "/categories/{category_id}/projects/{project_id}/call-records",
    response_model=ToolCallRecordListResponse,
)
def list_tool_project_call_records(
    category_id: str,
    project_id: str,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=2_147_483_647)] = 0,
    snapshot: Annotated[str | None, Query(max_length=100)] = None,
) -> ToolCallRecordListResponse:
    try:
        page = get_tool_call_record_service().list_project_page(
            category_id, project_id, limit=limit, offset=offset, snapshot=snapshot,
        )
    except ToolCallRecordSnapshotExpired as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ToolCallRecordListResponse(
        category_id=category_id,
        project_id=project_id,
        count=page.count,
        offset=page.offset,
        limit=page.limit,
        snapshot=page.snapshot,
        items=[ToolCallRecordListItemResponse.from_domain(record) for record in page.items],
    )


@router.get(
    "/categories/{category_id}/projects/{project_id}/call-records/{record_id}",
    response_model=ToolCallRecordResponse,
)
def get_tool_project_call_record(
    category_id: str, project_id: str, record_id: str,
) -> ToolCallRecordResponse:
    record = get_tool_call_record_service().get_project_record(category_id, project_id, record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="调用记录不存在或已被移除。")
    return ToolCallRecordResponse.from_domain(record)
