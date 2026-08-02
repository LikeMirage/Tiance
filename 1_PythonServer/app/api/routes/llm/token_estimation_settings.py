from fastapi import APIRouter

from app.schemas.llm.token_estimation_settings import (
    JsonTokenEstimateRequest,
    TokenEstimateResponse,
    TokenEstimationSettingsResponse,
    TokenEstimationSettingsSaveRequest,
)
from app.services.llm.token_estimation_settings import (
    get_token_estimation_settings_service,
)


router = APIRouter(prefix="/llm/token-estimation-settings", tags=["llm"])


@router.get(
    "",
    response_model=TokenEstimationSettingsResponse,
    summary="Get token estimation settings",
)
def get_token_estimation_settings() -> TokenEstimationSettingsResponse:
    service = get_token_estimation_settings_service()
    return TokenEstimationSettingsResponse.from_domain(service.get_settings())


@router.put(
    "",
    response_model=TokenEstimationSettingsResponse,
    summary="Save token estimation settings",
)
def save_token_estimation_settings(
    payload: TokenEstimationSettingsSaveRequest,
) -> TokenEstimationSettingsResponse:
    service = get_token_estimation_settings_service()
    settings = service.save_settings(payload.settings.to_domain())
    return TokenEstimationSettingsResponse.from_domain(settings)


@router.post(
    "/estimate-json",
    response_model=TokenEstimateResponse,
    summary="Estimate JSON token count",
)
def estimate_json_tokens(
    payload: JsonTokenEstimateRequest,
) -> TokenEstimateResponse:
    service = get_token_estimation_settings_service()
    return TokenEstimateResponse(
        token_count=service.estimate_json_tokens(payload.value),
    )
