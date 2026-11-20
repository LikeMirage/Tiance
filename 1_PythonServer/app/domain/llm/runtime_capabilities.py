from dataclasses import dataclass

from app.domain.llm.generation_params import LlmOutputFormat, LlmReasoningMode

DEFAULT_IMAGE_MAX_LONG_EDGE_PX = 8192


@dataclass(frozen=True, slots=True)
class MultiImageLimit:
    min_images: int
    max_long_edge_px: int

    def apply(self, limit: int, count: int) -> int:
        return min(limit, self.max_long_edge_px) if count >= self.min_images else limit


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
    image_max_long_edge_px: int = DEFAULT_IMAGE_MAX_LONG_EDGE_PX
    multi_image_limit: MultiImageLimit | None = None

    def image_limit_for_count(self, count: int) -> int:
        if self.multi_image_limit:
            return self.multi_image_limit.apply(self.image_max_long_edge_px, count)
        return self.image_max_long_edge_px
