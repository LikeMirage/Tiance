from fastapi import APIRouter, Query

from app.schemas.tools import (
    ToolExampleDetailListResponse,
    ToolExampleDetailResponse,
    ToolExampleQueryRequest,
    ToolExampleSummaryListResponse,
    ToolExampleSummaryResponse,
    ToolParameterDetailResponse,
    ToolSummaryListResponse,
    ToolSummaryResponse,
)
from app.services.tools import get_tool_catalog_service
from app.services.tools.catalog_access import assert_session_tool_allowed

router = APIRouter(prefix="/tools/catalog", tags=["tools"])


@router.get(
    "/summaries",
    response_model=ToolSummaryListResponse,
    summary="List lightweight tool summaries",
)
def list_tool_summaries() -> ToolSummaryListResponse:
    service = get_tool_catalog_service()
    items = [
        ToolSummaryResponse.from_domain(summary)
        for summary in service.list_tool_summaries()
    ]
    return ToolSummaryListResponse(count=len(items), items=items)


@router.get(
    "/{tool_name}/parameters",
    response_model=ToolParameterDetailResponse,
    summary="Get tool input parameter detail",
)
def get_tool_parameters(
    tool_name: str,
    project_id: str | None = Query(default=None),
    session_id: str | None = Query(default=None),
) -> ToolParameterDetailResponse:
    assert_session_tool_allowed(
        tool_name,
        project_id=project_id,
        session_id=session_id,
    )
    service = get_tool_catalog_service()
    return ToolParameterDetailResponse.from_domain(
        service.get_tool_parameters(tool_name),
    )


@router.get(
    "/{tool_name}/example-titles",
    response_model=ToolExampleSummaryListResponse,
    summary="List tool example titles",
)
def list_tool_example_titles(
    tool_name: str,
    project_id: str | None = Query(default=None),
    session_id: str | None = Query(default=None),
) -> ToolExampleSummaryListResponse:
    assert_session_tool_allowed(
        tool_name,
        project_id=project_id,
        session_id=session_id,
    )
    service = get_tool_catalog_service()
    items = [
        ToolExampleSummaryResponse.from_domain(summary)
        for summary in service.list_tool_example_summaries(tool_name)
    ]
    return ToolExampleSummaryListResponse(
        name=tool_name,
        count=len(items),
        items=items,
    )


@router.post(
    "/{tool_name}/examples/query",
    response_model=ToolExampleDetailListResponse,
    summary="Get selected tool examples",
)
def query_tool_examples(
    tool_name: str,
    payload: ToolExampleQueryRequest,
    project_id: str | None = Query(default=None),
    session_id: str | None = Query(default=None),
) -> ToolExampleDetailListResponse:
    assert_session_tool_allowed(
        tool_name,
        project_id=project_id,
        session_id=session_id,
    )
    service = get_tool_catalog_service()
    examples = service.get_tool_examples(
        tool_name,
        titles=tuple(payload.titles),
        indexes=tuple(payload.indexes),
        include_all=payload.include_all,
    )
    items = [ToolExampleDetailResponse.from_domain(example) for example in examples]
    return ToolExampleDetailListResponse(
        name=tool_name,
        count=len(items),
        items=items,
    )
