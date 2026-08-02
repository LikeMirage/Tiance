from dataclasses import dataclass
from typing import Protocol

from app.domain.llm.chat import ChatCompletionRequest, ChatUsage
from app.domain.llm.generation_params import LlmOutputFormat
from app.domain.llm.provider_adaptation import (
    ProviderAdaptationRules,
    apply_capability_rules,
)
from app.domain.llm.provider_catalog import ProviderCatalogEntry
from app.domain.llm.runtime_capabilities import (
    LlmMaxOutputTokensCapabilities,
    LlmReasoningCapabilities,
    LlmRuntimeCapabilities,
    LlmSamplingCapabilities,
)

SAMPLING_PARAMETER_NAMES = (
    "temperature",
    "top_p",
    "presence_penalty",
    "frequency_penalty",
)


class ProviderProfile(Protocol):
    profile_id: str
    include_reasoning_content_in_messages: bool
    include_responses_message_phase: bool
    include_responses_web_search_sources: bool

    def resolve_capabilities(
        self,
        provider_template: ProviderCatalogEntry,
        model_id: str | None,
    ) -> LlmRuntimeCapabilities: ...

    def apply_openai_compatible_body(
        self,
        body: dict[str, object],
        request: ChatCompletionRequest,
    ) -> dict[str, object]: ...

    def apply_openai_responses_body(
        self,
        body: dict[str, object],
        request: ChatCompletionRequest,
    ) -> dict[str, object]: ...

    def parse_usage(self, value: object) -> ChatUsage | None: ...


@dataclass(frozen=True, slots=True)
class GenericOpenAICompatibleProfile:
    profile_id: str = "openai_compatible"
    include_reasoning_content_in_messages: bool = False
    include_responses_message_phase: bool = False
    include_responses_web_search_sources: bool = False
    adaptation_rules: ProviderAdaptationRules | None = None

    def resolve_capabilities(
        self,
        provider_template: ProviderCatalogEntry,
        model_id: str | None,
    ) -> LlmRuntimeCapabilities:
        capabilities = LlmRuntimeCapabilities(
            provider_id=provider_template.provider_id,
            model_id=model_id,
            protocol_family=provider_template.protocol_family.value,
            provider_profile_id=self.profile_id,
            output_formats=(LlmOutputFormat.TEXT,),
            reasoning=LlmReasoningCapabilities(supported=False, modes=()),
            sampling=LlmSamplingCapabilities(
                supported=True,
                parameters=SAMPLING_PARAMETER_NAMES,
            ),
            max_output_tokens=LlmMaxOutputTokensCapabilities(
                supported=True,
                min=1,
                max=None,
            ),
        )
        if self.adaptation_rules is None:
            return capabilities
        return apply_capability_rules(
            capabilities,
            self.adaptation_rules.capabilities,
        )

    def apply_openai_compatible_body(
        self,
        body: dict[str, object],
        request: ChatCompletionRequest,
    ) -> dict[str, object]:
        return body

    def apply_openai_responses_body(
        self,
        body: dict[str, object],
        request: ChatCompletionRequest,
    ) -> dict[str, object]:
        return body

    def parse_usage(self, value: object) -> ChatUsage | None:
        return parse_openai_usage(value)


def parse_openai_usage(
    value: object,
    *,
    read_top_level_cache_tokens: bool = False,
    read_prompt_details_cache_tokens: bool = True,
) -> ChatUsage | None:
    if not isinstance(value, dict):
        return None

    prompt_tokens = _optional_int(value.get("prompt_tokens"))
    completion_tokens = _optional_int(value.get("completion_tokens"))
    total_tokens = _optional_int(value.get("total_tokens"))

    prompt_tokens_details = _optional_dict(value.get("prompt_tokens_details"))
    completion_tokens_details = _optional_dict(value.get("completion_tokens_details"))

    prompt_cache_hit_tokens: int | None = None
    if read_top_level_cache_tokens:
        prompt_cache_hit_tokens = _optional_int(value.get("prompt_cache_hit_tokens"))
    if prompt_cache_hit_tokens is None and read_prompt_details_cache_tokens:
        prompt_cache_hit_tokens = _optional_int(prompt_tokens_details.get("cached_tokens"))

    prompt_cache_miss_tokens: int | None = None
    if read_top_level_cache_tokens:
        prompt_cache_miss_tokens = _optional_int(value.get("prompt_cache_miss_tokens"))
    if (
        prompt_cache_miss_tokens is None
        and prompt_tokens is not None
        and prompt_cache_hit_tokens is not None
    ):
        prompt_cache_miss_tokens = max(prompt_tokens - prompt_cache_hit_tokens, 0)

    return ChatUsage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        prompt_cache_hit_tokens=prompt_cache_hit_tokens,
        prompt_cache_miss_tokens=prompt_cache_miss_tokens,
        reasoning_tokens=_optional_int(completion_tokens_details.get("reasoning_tokens")),
    )


def _optional_dict(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) else None
