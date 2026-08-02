from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.domain.llm.functional_model_settings import LlmFunctionalModelSettings


class LlmFunctionalModelSettingsSaveRequest(BaseModel):
    version: int = Field(ge=1)
    settings: dict[str, Any]

    @field_validator("settings")
    @classmethod
    def validate_settings(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not value:
            raise ValueError("功能模型设置不能为空。")
        return value


class LlmFunctionalModelSettingsResponse(BaseModel):
    default_settings: dict[str, Any] | None = None
    has_settings: bool
    profile_key: str | None = None
    version: int | None = None
    settings: dict[str, Any] | None = None
    updated_at: str | None = None

    @classmethod
    def empty(
        cls,
        *,
        default_settings: dict[str, Any] | None = None,
        profile_key: str | None = None,
        version: int | None = None,
    ) -> "LlmFunctionalModelSettingsResponse":
        return cls(
            default_settings=default_settings,
            has_settings=False,
            profile_key=profile_key,
            version=version,
        )

    @classmethod
    def from_domain(
        cls,
        settings: LlmFunctionalModelSettings,
        *,
        default_settings: dict[str, Any] | None = None,
    ) -> "LlmFunctionalModelSettingsResponse":
        return cls(
            default_settings=default_settings,
            has_settings=True,
            profile_key=settings.settings_id,
            version=settings.version,
            settings=settings.settings,
            updated_at=settings.updated_at,
        )
