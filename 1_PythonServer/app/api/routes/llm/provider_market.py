from fastapi import APIRouter, status

from app.schemas.llm.provider_market import (
    ProviderMarketConnectRequest,
    ProviderMarketIndexResponse,
    ProviderMarketInstallRequest,
    ProviderMarketInstallResponse,
    ProviderMarketSettingsResponse,
    ProviderMarketSettingsUpdateRequest,
)
from app.services.application.provider_market import get_provider_market_application_service


router = APIRouter(prefix="/llm/provider-market", tags=["llm"])


@router.get("/settings", response_model=ProviderMarketSettingsResponse)
def read_provider_market_settings() -> ProviderMarketSettingsResponse:
    return get_provider_market_application_service().get_settings()


@router.put("/settings", response_model=ProviderMarketSettingsResponse)
def update_provider_market_settings(
    payload: ProviderMarketSettingsUpdateRequest,
) -> ProviderMarketSettingsResponse:
    return get_provider_market_application_service().save_filters(payload.filters)


@router.get("/index", response_model=ProviderMarketIndexResponse)
async def read_provider_market_index() -> ProviderMarketIndexResponse:
    return await get_provider_market_application_service().get_index()


@router.post("/connect", response_model=ProviderMarketIndexResponse)
async def connect_provider_market(
    payload: ProviderMarketConnectRequest,
) -> ProviderMarketIndexResponse:
    return await get_provider_market_application_service().connect(payload.source)


@router.post(
    "/providers/{provider_id}/install",
    response_model=ProviderMarketInstallResponse,
    status_code=status.HTTP_201_CREATED,
)
async def install_provider_market_provider(
    provider_id: str,
    payload: ProviderMarketInstallRequest,
) -> ProviderMarketInstallResponse:
    return await get_provider_market_application_service().install_provider(
        provider_id=provider_id,
        category_id=payload.category_id,
        replace_existing=payload.replace_existing,
    )
