from fastapi import APIRouter, status

from app.schemas.tools.tool_market import (
    ToolMarketConnectRequest,
    ToolMarketIndexResponse,
    ToolMarketInstallRequest,
    ToolMarketInstallResponse,
    ToolMarketSettingsResponse,
    ToolMarketSettingsUpdateRequest,
)
from app.services.application.tool_market import get_tool_market_application_service


router = APIRouter(prefix="/tools/market", tags=["tools"])


@router.get("/settings", response_model=ToolMarketSettingsResponse)
def read_tool_market_settings() -> ToolMarketSettingsResponse:
    return get_tool_market_application_service().get_settings()


@router.put("/settings", response_model=ToolMarketSettingsResponse)
def update_tool_market_settings(
    payload: ToolMarketSettingsUpdateRequest,
) -> ToolMarketSettingsResponse:
    return get_tool_market_application_service().save_filters(payload.filters)


@router.get("/index", response_model=ToolMarketIndexResponse)
async def read_tool_market_index() -> ToolMarketIndexResponse:
    return await get_tool_market_application_service().get_index()


@router.post("/connect", response_model=ToolMarketIndexResponse)
async def connect_tool_market(payload: ToolMarketConnectRequest) -> ToolMarketIndexResponse:
    return await get_tool_market_application_service().connect(payload.source)


@router.post(
    "/tools/{tool_id}/install",
    response_model=ToolMarketInstallResponse,
    status_code=status.HTTP_201_CREATED,
)
async def install_tool_market_tool(
    tool_id: str,
    payload: ToolMarketInstallRequest,
) -> ToolMarketInstallResponse:
    return await get_tool_market_application_service().install_tool(
        tool_id=tool_id,
        category_id=payload.category_id,
        call_name=payload.call_name,
    )
