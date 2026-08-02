from __future__ import annotations

from functools import lru_cache
from typing import Any

from app.domain.llm.generation_params import LlmOutputFormat, LlmReasoningMode
from app.domain.llm.provider_adaptation import (
    DEFAULT_PROMPT_CACHE_RETENTION_SECONDS,
    LlmCapabilityRules,
    LlmProtocolBehaviorRules,
    LlmRequestRules,
    ProviderAdaptationRules,
    merge_adaptation_rules,
)
from app.repositories.llm.provider_file_store import (
    PROVIDER_MODEL_RULES_FILE,
    PROVIDER_MANIFEST_FILE,
    PROVIDER_MODELS_FILE,
    PROVIDER_RULES_FILE,
    ProviderFileStore,
    ProviderFileStoreError,
    get_provider_file_store,
)


_SAMPLING_PARAMETERS = {
    "temperature",
    "top_p",
    "presence_penalty",
    "frequency_penalty",
}
_REQUEST_PARAMETERS = _SAMPLING_PARAMETERS | {"max_tokens", "max_completion_tokens"}
_MAX_OUTPUT_TOKEN_PARAMETERS = {"max_tokens", "max_completion_tokens"}
_INPUT_MODALITIES = {"text", "image"}


class ProviderAdaptationRulesRepository:
    def __init__(self, store: ProviderFileStore) -> None:
        self._store = store

    def resolve(
        self,
        *,
        provider_id: str,
        model_id: str | None,
        expected_profile_id: str | None = None,
    ) -> ProviderAdaptationRules | None:
        if expected_profile_id is not None:
            manifest = self._store.read_provider_file(
                provider_id,
                PROVIDER_MANIFEST_FILE,
                required=False,
            )
            stored_profile_id = manifest.get("profileId") if manifest else None
            if stored_profile_id != expected_profile_id:
                return None
        provider_payload = self._store.read_provider_file(
            provider_id,
            PROVIDER_RULES_FILE,
            required=False,
        )
        model_payload = self._store.read_provider_file(
            provider_id,
            PROVIDER_MODEL_RULES_FILE,
            required=False,
        )
        if provider_payload is None and model_payload is None:
            return None

        resolved = _parse_rules_file(provider_payload or _empty_rules_file(), PROVIDER_RULES_FILE)
        if model_payload is None:
            return resolved if resolved != ProviderAdaptationRules() else None

        families, models = _parse_model_rules_file(model_payload)
        if not model_id:
            return resolved if resolved != ProviderAdaptationRules() else None

        family_group = self._find_family_group(provider_id, model_id)
        if family_group and family_group in families:
            resolved = merge_adaptation_rules(resolved, families[family_group])
        exact_rules = models.get(model_id.strip().lower())
        if exact_rules is not None:
            resolved = merge_adaptation_rules(resolved, exact_rules)
        return resolved if resolved != ProviderAdaptationRules() else None

    def resolve_prompt_cache_retention_seconds(
        self,
        *,
        provider_id: str,
        model_id: str | None = None,
    ) -> int:
        rules = self.resolve(provider_id=provider_id, model_id=model_id)
        configured = (
            rules.behavior.prompt_cache_retention_seconds
            if rules is not None
            else None
        )
        return configured or DEFAULT_PROMPT_CACHE_RETENTION_SECONDS

    def save_prompt_cache_retention_seconds(
        self,
        *,
        provider_id: str,
        seconds: int,
    ) -> int:
        if isinstance(seconds, bool) or not isinstance(seconds, int) or seconds < 1:
            raise ProviderFileStoreError(
                "Prompt cache retention seconds must be a positive integer."
            )

        def update(payload: dict[str, Any]) -> dict[str, Any]:
            behavior = payload.get("behavior", {})
            if not isinstance(behavior, dict):
                raise ProviderFileStoreError(
                    f"{PROVIDER_RULES_FILE} behavior must be an object."
                )
            updated = {
                **payload,
                "behavior": {
                    **behavior,
                    "promptCacheRetentionSeconds": seconds,
                },
            }
            _parse_rules_file(updated, PROVIDER_RULES_FILE)
            return updated

        self._store.update_provider_file(provider_id, PROVIDER_RULES_FILE, update)
        return seconds

    def _find_family_group(self, provider_id: str, model_id: str) -> str | None:
        payload = self._store.read_provider_file(
            provider_id,
            PROVIDER_MODELS_FILE,
            required=False,
        ) or {}
        items = payload.get("items")
        if not isinstance(items, list):
            return None
        normalized_model_id = model_id.strip().lower()
        for item in items:
            if not isinstance(item, dict):
                continue
            item_model_id = item.get("modelId")
            if not isinstance(item_model_id, str) or item_model_id.strip().lower() != normalized_model_id:
                continue
            family_group = item.get("familyGroup")
            return family_group.strip() if isinstance(family_group, str) and family_group.strip() else None
        return None


def _parse_rules_file(payload: dict[str, Any], file_name: str) -> ProviderAdaptationRules:
    _reject_unknown(
        payload,
        {"schemaVersion", "capabilities", "request", "behavior"},
        file_name,
    )
    if payload.get("schemaVersion") != 1:
        raise ProviderFileStoreError(f"{file_name} schemaVersion must be 1.")
    return _parse_rules(payload, file_name)


def _parse_model_rules_file(
    payload: dict[str, Any],
) -> tuple[dict[str, ProviderAdaptationRules], dict[str, ProviderAdaptationRules]]:
    _reject_unknown(payload, {"schemaVersion", "families", "models"}, PROVIDER_MODEL_RULES_FILE)
    if payload.get("schemaVersion") != 1:
        raise ProviderFileStoreError(f"{PROVIDER_MODEL_RULES_FILE} schemaVersion must be 1.")
    return (
        _parse_named_rules(payload.get("families", {}), "families"),
        _parse_named_rules(payload.get("models", {}), "models", normalize_keys=True),
    )


def _parse_named_rules(
    value: object,
    field_name: str,
    *,
    normalize_keys: bool = False,
) -> dict[str, ProviderAdaptationRules]:
    if not isinstance(value, dict):
        raise ProviderFileStoreError(f"{PROVIDER_MODEL_RULES_FILE} {field_name} must be an object.")
    result: dict[str, ProviderAdaptationRules] = {}
    for raw_key, raw_rules in value.items():
        if not isinstance(raw_key, str) or not raw_key.strip() or not isinstance(raw_rules, dict):
            raise ProviderFileStoreError(
                f"{PROVIDER_MODEL_RULES_FILE} {field_name} entries must be named objects."
            )
        key = raw_key.strip().lower() if normalize_keys else raw_key.strip()
        _reject_unknown(
            raw_rules,
            {"capabilities", "request", "behavior"},
            f"{field_name}.{key}",
        )
        result[key] = _parse_rules(raw_rules, f"{field_name}.{key}")
    return result


def _parse_rules(payload: dict[str, Any], location: str) -> ProviderAdaptationRules:
    return ProviderAdaptationRules(
        capabilities=_parse_capabilities(payload.get("capabilities", {}), location),
        request=_parse_request(payload.get("request", {}), location),
        behavior=_parse_behavior(payload.get("behavior", {}), location),
    )


def _parse_capabilities(value: object, location: str) -> LlmCapabilityRules:
    if not isinstance(value, dict):
        raise ProviderFileStoreError(f"{location} capabilities must be an object.")
    _reject_unknown(
        value,
        {
            "outputFormats",
            "reasoning",
            "sampling",
            "maxOutputTokens",
            "toolCalling",
            "inputModalities",
        },
        f"{location}.capabilities",
    )
    reasoning = _optional_object(value, "reasoning", location)
    sampling = _optional_object(value, "sampling", location)
    max_tokens = _optional_object(value, "maxOutputTokens", location)
    tool_calling = _optional_object(value, "toolCalling", location)
    _reject_unknown(reasoning, {"supported", "modes"}, f"{location}.capabilities.reasoning")
    _reject_unknown(
        sampling,
        {"supported", "parameters", "disabledWhenReasoning", "disabledReason"},
        f"{location}.capabilities.sampling",
    )
    _reject_unknown(max_tokens, {"supported", "min", "max"}, f"{location}.capabilities.maxOutputTokens")
    _reject_unknown(tool_calling, {"supported"}, f"{location}.capabilities.toolCalling")
    return LlmCapabilityRules(
        output_formats=_optional_enum_tuple(value, "outputFormats", LlmOutputFormat, location),
        reasoning_supported=_optional_bool(reasoning, "supported", location),
        reasoning_modes=_optional_enum_tuple(reasoning, "modes", LlmReasoningMode, location),
        sampling_supported=_optional_bool(sampling, "supported", location),
        sampling_parameters=_optional_string_tuple(
            sampling,
            "parameters",
            allowed=_SAMPLING_PARAMETERS,
            location=location,
        ),
        sampling_disabled_when_reasoning=_optional_bool(
            sampling,
            "disabledWhenReasoning",
            location,
        ),
        sampling_disabled_reason=_optional_text(sampling, "disabledReason", location),
        max_output_tokens_supported=_optional_bool(max_tokens, "supported", location),
        max_output_tokens_min=_optional_positive_int(max_tokens, "min", location),
        max_output_tokens_max=_optional_positive_int(max_tokens, "max", location),
        tool_calling_supported=_optional_bool(tool_calling, "supported", location),
        input_modalities=_optional_string_tuple(
            value,
            "inputModalities",
            allowed=_INPUT_MODALITIES,
            location=location,
        ),
    )


def _parse_request(value: object, location: str) -> LlmRequestRules:
    if not isinstance(value, dict):
        raise ProviderFileStoreError(f"{location} request must be an object.")
    _reject_unknown(
        value,
        {
            "omitParameters",
            "maxOutputTokensParameter",
            "jsonObjectResponseFormat",
            "streamUsage",
        },
        f"{location}.request",
    )
    parameter = value.get("maxOutputTokensParameter")
    if parameter is not None and parameter not in _MAX_OUTPUT_TOKEN_PARAMETERS:
        raise ProviderFileStoreError(
            f"{location} maxOutputTokensParameter is not supported: {parameter}"
        )
    return LlmRequestRules(
        omit_parameters=_optional_string_tuple(
            value,
            "omitParameters",
            allowed=_REQUEST_PARAMETERS,
            location=location,
        ),
        max_output_tokens_parameter=parameter,
        json_object_response_format=_optional_bool(value, "jsonObjectResponseFormat", location),
        stream_usage=_optional_bool(value, "streamUsage", location),
    )


def _parse_behavior(value: object, location: str) -> LlmProtocolBehaviorRules:
    if not isinstance(value, dict):
        raise ProviderFileStoreError(f"{location} behavior must be an object.")
    _reject_unknown(
        value,
        {
            "includeReasoningContentInMessages",
            "includeResponsesMessagePhase",
            "includeResponsesWebSearchSources",
            "promptCacheRetentionSeconds",
        },
        f"{location}.behavior",
    )
    return LlmProtocolBehaviorRules(
        include_reasoning_content_in_messages=_optional_bool(
            value,
            "includeReasoningContentInMessages",
            location,
        ),
        include_responses_message_phase=_optional_bool(
            value,
            "includeResponsesMessagePhase",
            location,
        ),
        include_responses_web_search_sources=_optional_bool(
            value,
            "includeResponsesWebSearchSources",
            location,
        ),
        prompt_cache_retention_seconds=_optional_positive_int(
            value,
            "promptCacheRetentionSeconds",
            location,
        ),
    )


def _optional_object(payload: dict[str, Any], key: str, location: str) -> dict[str, Any]:
    value = payload.get(key, {})
    if not isinstance(value, dict):
        raise ProviderFileStoreError(f"{location} {key} must be an object.")
    return value


def _optional_bool(payload: dict[str, Any], key: str, location: str) -> bool | None:
    if key not in payload:
        return None
    value = payload[key]
    if not isinstance(value, bool):
        raise ProviderFileStoreError(f"{location} {key} must be a boolean.")
    return value


def _optional_positive_int(payload: dict[str, Any], key: str, location: str) -> int | None:
    if key not in payload:
        return None
    value = payload[key]
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ProviderFileStoreError(f"{location} {key} must be a positive integer.")
    return value


def _optional_text(payload: dict[str, Any], key: str, location: str) -> str | None:
    if key not in payload:
        return None
    value = payload[key]
    if not isinstance(value, str) or not value.strip():
        raise ProviderFileStoreError(f"{location} {key} must be non-empty text.")
    return value.strip()


def _optional_string_tuple(
    payload: dict[str, Any],
    key: str,
    *,
    allowed: set[str],
    location: str,
) -> tuple[str, ...] | None:
    if key not in payload:
        return None
    value = payload[key]
    if not isinstance(value, list) or any(not isinstance(item, str) or item not in allowed for item in value):
        raise ProviderFileStoreError(f"{location} {key} contains an unsupported value.")
    return tuple(value)


def _optional_enum_tuple(payload, key, enum_type, location):
    if key not in payload:
        return None
    value = payload[key]
    if not isinstance(value, list):
        raise ProviderFileStoreError(f"{location} {key} must be an array.")
    try:
        return tuple(enum_type(item) for item in value)
    except (TypeError, ValueError) as exc:
        raise ProviderFileStoreError(f"{location} {key} contains an unsupported value.") from exc


def _reject_unknown(payload: dict[str, Any], allowed: set[str], location: str) -> None:
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise ProviderFileStoreError(f"{location} contains unknown fields: {', '.join(unknown)}")


def _empty_rules_file() -> dict[str, Any]:
    return {"schemaVersion": 1, "capabilities": {}, "request": {}, "behavior": {}}


@lru_cache
def get_provider_adaptation_rules_repository() -> ProviderAdaptationRulesRepository:
    return ProviderAdaptationRulesRepository(get_provider_file_store())
