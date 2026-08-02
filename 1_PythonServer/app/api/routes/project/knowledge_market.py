from fastapi import APIRouter, status
from fastapi.responses import FileResponse

from app.schemas.project.project_market import (
    ProjectMarketConnectRequest,
    ProjectMarketIndexResponse,
    ProjectMarketInstallOperation,
    ProjectMarketInstallRequest,
    ProjectMarketSettingsResponse,
    ProjectMarketSettingsUpdateRequest,
)
from app.services.application.project_market import (
    get_knowledge_market_application_service,
)


router = APIRouter(prefix="/knowledge/market", tags=["knowledge-market"])


@router.get("/settings", response_model=ProjectMarketSettingsResponse)
def read_knowledge_market_settings() -> ProjectMarketSettingsResponse:
    return get_knowledge_market_application_service().get_settings()


@router.put("/settings", response_model=ProjectMarketSettingsResponse)
def update_knowledge_market_settings(
    payload: ProjectMarketSettingsUpdateRequest,
) -> ProjectMarketSettingsResponse:
    return get_knowledge_market_application_service().save_filters(payload.filters)


@router.get("/index", response_model=ProjectMarketIndexResponse)
async def read_knowledge_market_index() -> ProjectMarketIndexResponse:
    return await get_knowledge_market_application_service().get_index()


@router.post("/connect", response_model=ProjectMarketIndexResponse)
async def connect_knowledge_market(
    payload: ProjectMarketConnectRequest,
) -> ProjectMarketIndexResponse:
    return await get_knowledge_market_application_service().connect(payload.source)


@router.post("/restore-default", response_model=ProjectMarketIndexResponse)
async def restore_default_knowledge_market() -> ProjectMarketIndexResponse:
    return await get_knowledge_market_application_service().restore_default_source()


@router.get("/previews/{market_project_id}", response_class=FileResponse)
async def read_knowledge_market_preview(market_project_id: str) -> FileResponse:
    path = await get_knowledge_market_application_service().get_preview_path(
        market_project_id
    )
    return FileResponse(path)


@router.post(
    "/projects/{market_project_id}/install",
    response_model=ProjectMarketInstallOperation,
    status_code=status.HTTP_202_ACCEPTED,
)
async def install_knowledge_market_project(
    market_project_id: str,
    payload: ProjectMarketInstallRequest,
) -> ProjectMarketInstallOperation:
    return await get_knowledge_market_application_service().start_install(
        market_project_id=market_project_id,
        category_id=payload.category_id,
    )


@router.get(
    "/operations/{operation_id}",
    response_model=ProjectMarketInstallOperation,
)
def read_knowledge_market_operation(operation_id: str) -> ProjectMarketInstallOperation:
    return get_knowledge_market_application_service().get_operation(operation_id)
