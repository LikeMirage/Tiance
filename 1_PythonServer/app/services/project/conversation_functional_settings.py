from __future__ import annotations

from typing import Any

from app.domain.llm.generation_params import (
    LlmGenerationParams,
    LlmOutputFormat,
    LlmOutputOptions,
    LlmReasoningMode,
    LlmReasoningOptions,
)


def parse_model_key(value: str) -> tuple[str | None, str | None]:
    provider_id, separator, model_id = value.partition(":")
    if not separator:
        return None, None
    provider_id = provider_id.strip()
    model_id = model_id.strip()
    if not provider_id or not model_id:
        return None, None
    return provider_id, model_id


def generation_from_settings(value: object) -> LlmGenerationParams:
    settings = value if isinstance(value, dict) else {}
    return LlmGenerationParams(
        temperature=_optional_float(settings.get("temperature")),
        top_p=_optional_float(settings.get("topP")),
        max_output_tokens=_optional_int(settings.get("maxOutputTokens")),
        reasoning=_reasoning_from_settings(settings.get("reasoning")),
    )


def output_from_settings(value: object) -> LlmOutputOptions:
    settings = value if isinstance(value, dict) else {}
    try:
        output_format = LlmOutputFormat(
            str(settings.get("format") or LlmOutputFormat.JSON_OBJECT.value)
        )
    except ValueError:
        output_format = LlmOutputFormat.JSON_OBJECT
    return LlmOutputOptions(format=output_format)


def string_setting(settings: dict[str, Any], key: str) -> str:
    value = settings.get(key)
    return value.strip() if isinstance(value, str) else ""


def bool_setting(
    settings: dict[str, Any],
    key: str,
    *,
    default_value: bool,
) -> bool:
    value = settings.get(key)
    return value if isinstance(value, bool) else default_value


def int_setting(
    settings: dict[str, Any],
    key: str,
    *,
    default_value: int,
    minimum: int,
    maximum: int | None = None,
) -> int:
    value = _optional_int(settings.get(key))
    if value is None:
        return default_value
    min_bounded = max(minimum, value)
    return min_bounded if maximum is None else min(maximum, min_bounded)


def _reasoning_from_settings(value: object) -> LlmReasoningOptions | None:
    if not isinstance(value, dict):
        return None
    try:
        mode = LlmReasoningMode(
            str(value.get("mode") or LlmReasoningMode.DEFAULT.value)
        )
    except ValueError:
        mode = LlmReasoningMode.DEFAULT
    return LlmReasoningOptions(mode=mode)


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _optional_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None
