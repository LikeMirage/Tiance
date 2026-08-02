from functools import lru_cache
import math

from app.core.errors import BadRequestError
from app.domain.llm.token_estimation_settings import (
    DEFAULT_TOKEN_ESTIMATION_SETTINGS,
    TokenEstimationSettings,
)
from app.repositories.llm.token_estimation_settings_repository import (
    TokenEstimationSettingsRepository,
    get_token_estimation_settings_repository,
)
from app.services.llm.usage.estimation import estimate_json_token_count


class TokenEstimationSettingsService:
    def __init__(self, repository: TokenEstimationSettingsRepository) -> None:
        self._repository = repository

    def get_settings(self) -> TokenEstimationSettings:
        settings = self._repository.get_settings()
        return settings or DEFAULT_TOKEN_ESTIMATION_SETTINGS

    def save_settings(
        self,
        settings: TokenEstimationSettings,
    ) -> TokenEstimationSettings:
        _validate_settings(settings)
        return self._repository.save_settings(settings)

    def estimate_json_tokens(self, value: object) -> int:
        return estimate_json_token_count(value, self.get_settings())


def _validate_settings(settings: TokenEstimationSettings) -> None:
    ratio_fields = (
        ("ASCII 字符换算比例", settings.ascii_chars_per_token),
        ("其他字符换算比例", settings.other_chars_per_token),
    )
    for label, value in ratio_fields:
        if not math.isfinite(value) or not 0.1 <= value <= 16:
            raise BadRequestError(f"{label}必须在 0.1 到 16 之间。")
    if not 0 <= settings.message_overhead_tokens <= 128:
        raise BadRequestError("每条消息结构开销必须在 0 到 128 之间。")
    if not 0 <= settings.image_placeholder_tokens <= 32768:
        raise BadRequestError("每张图片占位 Token 必须在 0 到 32768 之间。")


@lru_cache
def get_token_estimation_settings_service() -> TokenEstimationSettingsService:
    return TokenEstimationSettingsService(
        get_token_estimation_settings_repository(),
    )
