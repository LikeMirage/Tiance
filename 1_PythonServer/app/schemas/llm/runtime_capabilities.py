from pydantic import BaseModel

from app.domain.llm.generation_params import LlmOutputFormat, LlmReasoningMode
from app.domain.llm.runtime_capabilities import LlmRuntimeCapabilities


class LlmReasoningCapabilitiesResponse(BaseModel):
    supported: bool
    modes: list[LlmReasoningMode]


class LlmSamplingCapabilitiesResponse(BaseModel):
    supported: bool
    parameters: list[str]
    disabled_when_reasoning: bool
    disabled_reason_when_reasoning: str | None = None


class LlmMaxOutputTokensCapabilitiesResponse(BaseModel):
    supported: bool
    min: int | None = None
    max: int | None = None


class LlmToolCallingCapabilitiesResponse(BaseModel):
    supported: bool


class LlmRuntimeCapabilitiesResponse(BaseModel):
    provider_id: str
    model_id: str | None = None
    protocol_family: str
    provider_profile_id: str
    input_modalities: list[str]
    output_formats: list[LlmOutputFormat]
    reasoning: LlmReasoningCapabilitiesResponse
    sampling: LlmSamplingCapabilitiesResponse
    max_output_tokens: LlmMaxOutputTokensCapabilitiesResponse
    tool_calling: LlmToolCallingCapabilitiesResponse

    @classmethod
    def from_domain(cls, capabilities: LlmRuntimeCapabilities) -> "LlmRuntimeCapabilitiesResponse":
        return cls(
            provider_id=capabilities.provider_id,
            model_id=capabilities.model_id,
            protocol_family=capabilities.protocol_family,
            provider_profile_id=capabilities.provider_profile_id,
            input_modalities=list(capabilities.input_modalities),
            output_formats=list(capabilities.output_formats),
            reasoning=LlmReasoningCapabilitiesResponse(
                supported=capabilities.reasoning.supported,
                modes=list(capabilities.reasoning.modes),
            ),
            sampling=LlmSamplingCapabilitiesResponse(
                supported=capabilities.sampling.supported,
                parameters=list(capabilities.sampling.parameters),
                disabled_when_reasoning=capabilities.sampling.disabled_when_reasoning,
                disabled_reason_when_reasoning=capabilities.sampling.disabled_reason_when_reasoning,
            ),
            max_output_tokens=LlmMaxOutputTokensCapabilitiesResponse(
                supported=capabilities.max_output_tokens.supported,
                min=capabilities.max_output_tokens.min,
                max=capabilities.max_output_tokens.max,
            ),
            tool_calling=LlmToolCallingCapabilitiesResponse(
                supported=capabilities.tool_calling.supported,
            ),
        )
