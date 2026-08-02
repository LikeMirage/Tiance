from functools import lru_cache
from typing import Any

from app.core.errors import BadRequestError
from app.domain.llm.functional_model_defaults import (
    get_default_functional_model_profile_settings,
    get_functional_model_profile_settings_version,
)
from app.domain.llm.functional_model_settings import LlmFunctionalModelSettings
from app.repositories.llm.functional_model_settings_repository import (
    LlmFunctionalModelSettingsRepository,
    get_llm_functional_model_settings_repository,
)


FUNCTIONAL_MODEL_PROFILE_KEYS = frozenset(
    (
        "defaultConversation",
        "projectMemoryManagement",
        "globalMemoryManagement",
        "memoryCompression",
        "naming",
    ),
)


class LlmFunctionalModelSettingsService:
    def __init__(self, repository: LlmFunctionalModelSettingsRepository) -> None:
        self._repository = repository

    def get_profile_settings(self, profile_key: str) -> LlmFunctionalModelSettings | None:
        _validate_profile_key(profile_key)
        expected_version = get_functional_model_profile_settings_version(profile_key)
        settings = self._repository.get_settings(profile_key)
        if settings is not None and settings.version == expected_version:
            return settings

        default_settings = get_default_functional_model_profile_settings(profile_key)
        if default_settings is None:
            return None

        return self._repository.save_settings(
            settings_id=profile_key,
            settings=default_settings,
            version=expected_version,
        )

    def get_default_profile_settings(self, profile_key: str) -> dict[str, Any]:
        _validate_profile_key(profile_key)
        default_settings = get_default_functional_model_profile_settings(profile_key)
        if default_settings is None:
            raise BadRequestError("未知的功能模型配置项。")
        return default_settings

    def save_profile_settings(
        self,
        *,
        profile_key: str,
        settings: dict[str, Any],
        version: int,
    ) -> LlmFunctionalModelSettings:
        _validate_profile_key(profile_key)
        expected_version = get_functional_model_profile_settings_version(profile_key)
        if version != expected_version:
            raise BadRequestError("功能模型设置版本号必须与当前后端版本一致。")
        if not settings:
            raise BadRequestError("功能模型设置不能为空。")

        return self._repository.save_settings(
            settings_id=profile_key,
            settings=settings,
            version=expected_version,
        )


def _validate_profile_key(profile_key: str) -> None:
    if profile_key not in FUNCTIONAL_MODEL_PROFILE_KEYS:
        raise BadRequestError("未知的功能模型配置项。")


@lru_cache
def get_llm_functional_model_settings_service() -> LlmFunctionalModelSettingsService:
    return LlmFunctionalModelSettingsService(
        get_llm_functional_model_settings_repository(),
    )
