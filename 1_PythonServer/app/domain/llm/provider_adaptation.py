from __future__ import annotations

from dataclasses import dataclass, replace

from app.domain.llm.generation_params import LlmOutputFormat, LlmReasoningMode
from app.domain.llm.runtime_capabilities import (
    LlmMaxOutputTokensCapabilities,
    LlmReasoningCapabilities,
    LlmRuntimeCapabilities,
    LlmSamplingCapabilities,
    LlmToolCallingCapabilities,
)


DEFAULT_PROMPT_CACHE_RETENTION_SECONDS = 5 * 60


@dataclass(frozen=True, slots=True)
class LlmCapabilityRules:
    output_formats: tuple[LlmOutputFormat, ...] | None = None
    reasoning_supported: bool | None = None
    reasoning_modes: tuple[LlmReasoningMode, ...] | None = None
    sampling_supported: bool | None = None
    sampling_parameters: tuple[str, ...] | None = None
    sampling_disabled_when_reasoning: bool | None = None
    sampling_disabled_reason: str | None = None
    max_output_tokens_supported: bool | None = None
    max_output_tokens_min: int | None = None
    max_output_tokens_max: int | None = None
    tool_calling_supported: bool | None = None
    input_modalities: tuple[str, ...] | None = None


@dataclass(frozen=True, slots=True)
class LlmRequestRules:
    omit_parameters: tuple[str, ...] | None = None
    max_output_tokens_parameter: str | None = None
    json_object_response_format: bool | None = None
    stream_usage: bool | None = None


@dataclass(frozen=True, slots=True)
class LlmProtocolBehaviorRules:
    include_reasoning_content_in_messages: bool | None = None
    include_responses_message_phase: bool | None = None
    include_responses_web_search_sources: bool | None = None
    prompt_cache_retention_seconds: int | None = None


@dataclass(frozen=True, slots=True)
class ProviderAdaptationRules:
    capabilities: LlmCapabilityRules = LlmCapabilityRules()
    request: LlmRequestRules = LlmRequestRules()
    behavior: LlmProtocolBehaviorRules = LlmProtocolBehaviorRules()


def merge_adaptation_rules(
    base: ProviderAdaptationRules,
    override: ProviderAdaptationRules,
) -> ProviderAdaptationRules:
    return ProviderAdaptationRules(
        capabilities=_merge_dataclass(base.capabilities, override.capabilities),
        request=_merge_dataclass(base.request, override.request),
        behavior=_merge_dataclass(base.behavior, override.behavior),
    )


def apply_capability_rules(
    capabilities: LlmRuntimeCapabilities,
    rules: LlmCapabilityRules,
) -> LlmRuntimeCapabilities:
    reasoning = capabilities.reasoning
    sampling = capabilities.sampling
    max_output_tokens = capabilities.max_output_tokens
    tool_calling = capabilities.tool_calling

    if rules.reasoning_supported is not None or rules.reasoning_modes is not None:
        reasoning = LlmReasoningCapabilities(
            supported=(
                rules.reasoning_supported
                if rules.reasoning_supported is not None
                else reasoning.supported
            ),
            modes=rules.reasoning_modes if rules.reasoning_modes is not None else reasoning.modes,
        )
    if (
        rules.sampling_supported is not None
        or rules.sampling_parameters is not None
        or rules.sampling_disabled_when_reasoning is not None
        or rules.sampling_disabled_reason is not None
    ):
        sampling = LlmSamplingCapabilities(
            supported=(
                rules.sampling_supported
                if rules.sampling_supported is not None
                else sampling.supported
            ),
            parameters=(
                rules.sampling_parameters
                if rules.sampling_parameters is not None
                else sampling.parameters
            ),
            disabled_when_reasoning=(
                rules.sampling_disabled_when_reasoning
                if rules.sampling_disabled_when_reasoning is not None
                else sampling.disabled_when_reasoning
            ),
            disabled_reason_when_reasoning=(
                rules.sampling_disabled_reason
                if rules.sampling_disabled_reason is not None
                else sampling.disabled_reason_when_reasoning
            ),
        )
    if (
        rules.max_output_tokens_supported is not None
        or rules.max_output_tokens_min is not None
        or rules.max_output_tokens_max is not None
    ):
        max_output_tokens = LlmMaxOutputTokensCapabilities(
            supported=(
                rules.max_output_tokens_supported
                if rules.max_output_tokens_supported is not None
                else max_output_tokens.supported
            ),
            min=(
                rules.max_output_tokens_min
                if rules.max_output_tokens_min is not None
                else max_output_tokens.min
            ),
            max=(
                rules.max_output_tokens_max
                if rules.max_output_tokens_max is not None
                else max_output_tokens.max
            ),
        )
    if rules.tool_calling_supported is not None:
        tool_calling = LlmToolCallingCapabilities(
            supported=rules.tool_calling_supported,
        )

    return replace(
        capabilities,
        output_formats=(
            rules.output_formats
            if rules.output_formats is not None
            else capabilities.output_formats
        ),
        reasoning=reasoning,
        sampling=sampling,
        max_output_tokens=max_output_tokens,
        tool_calling=tool_calling,
        input_modalities=(
            rules.input_modalities
            if rules.input_modalities is not None
            else capabilities.input_modalities
        ),
    )


def _merge_dataclass(base, override):
    values = {
        field_name: (
            override_value
            if (override_value := getattr(override, field_name)) is not None
            else getattr(base, field_name)
        )
        for field_name in base.__dataclass_fields__
    }
    return type(base)(**values)
