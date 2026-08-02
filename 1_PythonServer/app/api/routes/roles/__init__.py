from fastapi import APIRouter, status

from app.schemas.roles import (
    RoleMarketConnectRequest,
    RoleMarketIndexResponse,
    RoleMarketInstallRequest,
    RoleMarketInstallResponse,
    RoleMarketSettingsResponse,
    RoleMarketSettingsUpdateRequest,
)
from app.services.application.role_market import get_role_market_application_service


router = APIRouter(prefix="/roles", tags=["roles"])


@router.get("/market/settings", response_model=RoleMarketSettingsResponse)
def read_role_market_settings() -> RoleMarketSettingsResponse:
    return get_role_market_application_service().get_settings()


@router.put("/market/settings", response_model=RoleMarketSettingsResponse)
def update_role_market_settings(
    payload: RoleMarketSettingsUpdateRequest,
) -> RoleMarketSettingsResponse:
    return get_role_market_application_service().save_filters(payload.filters)


@router.get("/market/index", response_model=RoleMarketIndexResponse)
async def read_role_market_index() -> RoleMarketIndexResponse:
    return await get_role_market_application_service().get_index()


@router.post("/market/connect", response_model=RoleMarketIndexResponse)
async def connect_role_market(
    payload: RoleMarketConnectRequest,
) -> RoleMarketIndexResponse:
    return await get_role_market_application_service().connect(payload.source)


@router.post(
    "/market/roles/{role_id}/install",
    response_model=RoleMarketInstallResponse,
    status_code=status.HTTP_201_CREATED,
)
async def install_role_market_role(
    role_id: str,
    payload: RoleMarketInstallRequest,
) -> RoleMarketInstallResponse:
    return await get_role_market_application_service().install_role(
        role_id=role_id,
        category_id=payload.category_id,
        replace_existing=payload.replace_existing,
    )
