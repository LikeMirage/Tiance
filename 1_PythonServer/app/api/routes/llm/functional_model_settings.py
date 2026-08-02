from fastapi import APIRouter

from app.schemas.llm.functional_model_settings import (
    LlmFunctionalModelSettingsResponse,
    LlmFunctionalModelSettingsSaveRequest,
)
from app.services.application.functional_model_settings import (
    get_functional_model_settings_application_service,
)
from app.services.llm.functional_model_settings import (
    get_llm_functional_model_settings_service,
)

router = APIRouter(prefix="/llm/functional-model-settings", tags=["llm"])


@router.get(
    "/{profile_key}",
    response_model=LlmFunctionalModelSettingsResponse,
    summary="Get functional model profile settings",
)
def get_functional_model_settings(
    profile_key: str,
) -> LlmFunctionalModelSettingsResponse:
    service = get_llm_functional_model_settings_service()
    settings = service.get_profile_settings(profile_key)
    default_settings = service.get_default_profile_settings(profile_key)
    if settings is None:
        return LlmFunctionalModelSettingsResponse.empty(
            default_settings=default_settings,
            profile_key=profile_key,
            version=None,
        )
    return LlmFunctionalModelSettingsResponse.from_domain(
        settings,
        default_settings=default_settings,
    )


@router.put(
    "/{profile_key}",
    response_model=LlmFunctionalModelSettingsResponse,
    summary="Save functional model profile settings",
)
def save_functional_model_settings(
    profile_key: str,
    payload: LlmFunctionalModelSettingsSaveRequest,
) -> LlmFunctionalModelSettingsResponse:
    service = get_llm_functional_model_settings_service()
    application_service = get_functional_model_settings_application_service()
    settings = application_service.save_profile_settings(
        profile_key=profile_key,
        settings=payload.settings,
        version=payload.version,
    )
    return LlmFunctionalModelSettingsResponse.from_domain(
        settings,
        default_settings=service.get_default_profile_settings(profile_key),
    )
