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
from app.infra.llm.provider_profiles.base import parse_openai_usage
from app.infra.llm.provider_profiles.declared_rules import apply_declared_request_rules

_DEFAULT_SAMPLING_PARAMETERS = ("temperature", "top_p")


@dataclass(frozen=True, slots=True)
class DeepSeekProfile:
    profile_id: str = "deepseek"
    include_reasoning_content_in_messages: bool = True
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
            output_formats=(LlmOutputFormat.TEXT, LlmOutputFormat.JSON_OBJECT),
            reasoning=LlmReasoningCapabilities(
                supported=True,
                modes=(LlmReasoningMode.OFF, LlmReasoningMode.HIGH, LlmReasoningMode.MAX),
            ),
            sampling=LlmSamplingCapabilities(
                supported=True,
                parameters=_DEFAULT_SAMPLING_PARAMETERS,
                disabled_when_reasoning=True,
                disabled_reason_when_reasoning=(
                    "DeepSeek 思考模式下 temperature、top_p 不生效。"
                ),
            ),
            max_output_tokens=LlmMaxOutputTokensCapabilities(
                supported=True,
                min=32,
                max=384000,
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
        if self.adaptation_rules is None:
            _remove_parameters(body, ("presence_penalty", "frequency_penalty"))
            if request.output.format == LlmOutputFormat.JSON_OBJECT:
                body["response_format"] = {"type": "json_object"}
            if body.get("stream") is True:
                body["stream_options"] = {"include_usage": True}
        else:
            apply_declared_request_rules(body, request, self.adaptation_rules)

        reasoning = request.generation.reasoning
        if reasoning is None or reasoning.mode == LlmReasoningMode.DEFAULT:
            return body

        if reasoning.mode == LlmReasoningMode.OFF:
            body["thinking"] = {"type": "disabled"}
            return body

        if reasoning.mode in (LlmReasoningMode.HIGH, LlmReasoningMode.MAX):
            if self.adaptation_rules is None:
                _remove_parameters(body, _DEFAULT_SAMPLING_PARAMETERS)
            body["thinking"] = {"type": "enabled"}
            body["reasoning_effort"] = reasoning.mode.value
            return body

        return body

    def apply_openai_responses_body(
        self,
        body: dict[str, object],
        request: ChatCompletionRequest,
    ) -> dict[str, object]:
        return body

    def parse_usage(self, value: object) -> ChatUsage | None:
        return parse_openai_usage(value, read_top_level_cache_tokens=True)


def _remove_parameters(body: dict[str, object], parameter_names: tuple[str, ...]) -> None:
    for key in parameter_names:
        body.pop(key, None)
