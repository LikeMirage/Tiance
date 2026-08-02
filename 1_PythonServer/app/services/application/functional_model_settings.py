from functools import lru_cache
from typing import Any

from app.domain.llm.functional_model_settings import LlmFunctionalModelSettings
from app.services.llm.functional_model_settings import (
    LlmFunctionalModelSettingsService,
    get_llm_functional_model_settings_service,
)
class FunctionalModelSettingsApplicationService:
    def __init__(
        self,
        settings_service: LlmFunctionalModelSettingsService,
    ) -> None:
        self._settings_service = settings_service

    def save_profile_settings(
        self,
        *,
        profile_key: str,
        settings: dict[str, Any],
        version: int,
    ) -> LlmFunctionalModelSettings:
        return self._settings_service.save_profile_settings(
            profile_key=profile_key,
            settings=settings,
            version=version,
        )


@lru_cache
def get_functional_model_settings_application_service() -> FunctionalModelSettingsApplicationService:
    return FunctionalModelSettingsApplicationService(
        get_llm_functional_model_settings_service(),
    )
