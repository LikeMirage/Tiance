from dataclasses import dataclass

from app.domain.llm.chat import ChatCompletionRequest, ChatUsage
from app.domain.llm.generation_params import LlmOutputFormat, LlmReasoningMode
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
    LlmToolCallingCapabilities,
)


@dataclass(frozen=True, slots=True)
class OpenAIResponsesProfile:
    profile_id: str = "openai_responses"
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
            reasoning=LlmReasoningCapabilities(
                supported=True,
                modes=(
                    LlmReasoningMode.LOW,
                    LlmReasoningMode.MEDIUM,
                    LlmReasoningMode.HIGH,
                    LlmReasoningMode.MAX,
                ),
            ),
            sampling=LlmSamplingCapabilities(
                supported=True,
                parameters=("temperature", "top_p"),
            ),
            max_output_tokens=LlmMaxOutputTokensCapabilities(
                supported=True,
                min=1,
                max=None,
            ),
            tool_calling=LlmToolCallingCapabilities(supported=True),
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
        return None


@dataclass(frozen=True, slots=True)
class OpenAIProfile(OpenAIResponsesProfile):
    profile_id: str = "openai"
    include_responses_message_phase: bool = True
    include_responses_web_search_sources: bool = True
