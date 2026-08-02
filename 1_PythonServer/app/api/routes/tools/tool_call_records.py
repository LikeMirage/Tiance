from fastapi import APIRouter

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
) -> ToolCallRecordListResponse:
    records = get_tool_call_record_service().list_project_records(category_id, project_id)
    return ToolCallRecordListResponse(
        category_id=category_id,
        project_id=project_id,
        count=len(records),
        items=[ToolCallRecordResponse.from_domain(record) for record in records],
    )
