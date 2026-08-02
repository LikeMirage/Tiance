from time import monotonic

import httpx
from fastapi import APIRouter

from app.infra.http_client import get_shared_http_client
from app.schemas.network_settings import (
    NetworkDiagnosticResponse,
    NetworkSettingsResponse,
    NetworkSettingsSaveRequest,
)
from app.services.network_settings import get_network_settings_service


router = APIRouter(prefix="/network", tags=["network"])
_GITHUB_TARGET = "https://github.com/"


@router.get("/settings", response_model=NetworkSettingsResponse)
def get_network_settings() -> NetworkSettingsResponse:
    return NetworkSettingsResponse.from_domain(
        get_network_settings_service().get_settings(),
    )


@router.put("/settings", response_model=NetworkSettingsResponse)
def save_network_settings(
    payload: NetworkSettingsSaveRequest,
) -> NetworkSettingsResponse:
    return NetworkSettingsResponse.from_domain(
        get_network_settings_service().save_settings(payload.settings.to_domain()),
    )


@router.post("/diagnostics/github", response_model=NetworkDiagnosticResponse)
async def diagnose_github_connection() -> NetworkDiagnosticResponse:
    started_at = monotonic()
    try:
        response = await get_shared_http_client().get(_GITHUB_TARGET)
        elapsed_ms = round((monotonic() - started_at) * 1000)
        return NetworkDiagnosticResponse(
            ok=response.is_success,
            target=_GITHUB_TARGET,
            status_code=response.status_code,
            elapsed_ms=elapsed_ms,
            error=None if response.is_success else f"HTTP {response.status_code}",
        )
    except httpx.RequestError as exc:
        return NetworkDiagnosticResponse(
            ok=False,
            target=_GITHUB_TARGET,
            elapsed_ms=round((monotonic() - started_at) * 1000),
            error=str(exc),
        )
