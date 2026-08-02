from fastapi import APIRouter, Query

from app.core.errors import AppError, BadRequestError, NotFoundError
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
from app.services.project.project_conversations import get_project_conversation_service
from app.services.tools import get_tool_catalog_service
from app.services.tools.tool_metadata import normalize_tool_name

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
    _assert_session_tool_allowed(
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
    _assert_session_tool_allowed(
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
    _assert_session_tool_allowed(
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


def _assert_session_tool_allowed(
    tool_name: str,
    *,
    project_id: str | None,
    session_id: str | None,
) -> None:
    if not project_id and not session_id:
        return
    if not project_id or not session_id:
        raise BadRequestError("project_id 和 session_id 必须同时提供。")

    try:
        normalized_tool_name = normalize_tool_name(tool_name)
    except AppError as exc:
        raise BadRequestError("工具调用名称无效。") from exc

    session = get_project_conversation_service().get_session(project_id, session_id)
    if session is None:
        raise NotFoundError("当前会话不存在，无法确认目标工具是否在会话中启用。")

    if not session.settings.tools_enabled:
        raise NotFoundError("会话工具总开关已关闭。")

    enabled_tool_names = session.settings.enabled_tool_names
    if enabled_tool_names is None:
        return

    normalized_allowed_names: set[str] = set()
    for enabled_tool_name in enabled_tool_names:
        try:
            normalized_allowed_names.add(normalize_tool_name(enabled_tool_name))
        except AppError as exc:
            raise BadRequestError("会话工具启用配置无效。") from exc

    if normalized_tool_name not in normalized_allowed_names:
        raise NotFoundError("此工具已关闭。")
