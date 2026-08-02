from dataclasses import dataclass

from app.domain.llm.generation_params import LlmOutputFormat, LlmReasoningMode


@dataclass(frozen=True, slots=True)
class LlmReasoningCapabilities:
    supported: bool
    modes: tuple[LlmReasoningMode, ...] = ()


@dataclass(frozen=True, slots=True)
class LlmSamplingCapabilities:
    supported: bool
    parameters: tuple[str, ...] = ()
    disabled_when_reasoning: bool = False
    disabled_reason_when_reasoning: str | None = None


@dataclass(frozen=True, slots=True)
class LlmMaxOutputTokensCapabilities:
    supported: bool
    min: int | None = None
    max: int | None = None


@dataclass(frozen=True, slots=True)
class LlmToolCallingCapabilities:
    supported: bool


@dataclass(frozen=True, slots=True)
class LlmRuntimeCapabilities:
    provider_id: str
    model_id: str | None
    protocol_family: str
    provider_profile_id: str
    output_formats: tuple[LlmOutputFormat, ...]
    reasoning: LlmReasoningCapabilities
    sampling: LlmSamplingCapabilities
    max_output_tokens: LlmMaxOutputTokensCapabilities
    tool_calling: LlmToolCallingCapabilities = LlmToolCallingCapabilities(supported=False)
    input_modalities: tuple[str, ...] = ("text",)
