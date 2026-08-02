from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.domain.llm.token_estimation_settings import (
    DEFAULT_TOKEN_ESTIMATION_SETTINGS,
    TokenEstimationSettings,
)


class TokenEstimationSettingsPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ascii_chars_per_token: float = Field(ge=0.1, le=16, allow_inf_nan=False)
    other_chars_per_token: float = Field(ge=0.1, le=16, allow_inf_nan=False)
    message_overhead_tokens: int = Field(ge=0, le=128)
    image_placeholder_tokens: int = Field(ge=0, le=32768)

    def to_domain(self) -> TokenEstimationSettings:
        return TokenEstimationSettings(**self.model_dump())

    @classmethod
    def from_domain(
        cls,
        settings: TokenEstimationSettings,
    ) -> "TokenEstimationSettingsPayload":
        return cls(
            ascii_chars_per_token=settings.ascii_chars_per_token,
            other_chars_per_token=settings.other_chars_per_token,
            message_overhead_tokens=settings.message_overhead_tokens,
            image_placeholder_tokens=settings.image_placeholder_tokens,
        )


class TokenEstimationSettingsSaveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    settings: TokenEstimationSettingsPayload


class JsonTokenEstimateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: Any


class TokenEstimateResponse(BaseModel):
    token_count: int


class TokenEstimationSettingsResponse(BaseModel):
    settings: TokenEstimationSettingsPayload
    default_settings: TokenEstimationSettingsPayload
    updated_at: str | None

    @classmethod
    def from_domain(
        cls,
        settings: TokenEstimationSettings,
    ) -> "TokenEstimationSettingsResponse":
        return cls(
            settings=TokenEstimationSettingsPayload.from_domain(settings),
            default_settings=TokenEstimationSettingsPayload.from_domain(
                DEFAULT_TOKEN_ESTIMATION_SETTINGS,
            ),
            updated_at=settings.updated_at,
        )
