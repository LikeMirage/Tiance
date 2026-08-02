from dataclasses import dataclass

from app.core.errors import BadRequestError
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
from app.infra.llm.provider_profiles.base import (
    SAMPLING_PARAMETER_NAMES,
    parse_openai_usage,
)
from app.infra.llm.provider_profiles.declared_rules import apply_declared_request_rules

_DEFAULT_REASONING_MODES = (
    LlmReasoningMode.DEFAULT,
    LlmReasoningMode.AUTO,
    LlmReasoningMode.ENABLED,
    LlmReasoningMode.OFF,
)


@dataclass(frozen=True, slots=True)
class VolcengineProfile:
    profile_id: str = "volcengine"
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
                modes=_DEFAULT_REASONING_MODES,
            ),
            sampling=LlmSamplingCapabilities(
                supported=True,
                parameters=SAMPLING_PARAMETER_NAMES,
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
        if self.adaptation_rules is None:
            max_tokens = body.pop("max_tokens", None)
            if max_tokens is not None:
                body["max_completion_tokens"] = max_tokens
            if request.output.format == LlmOutputFormat.JSON_OBJECT:
                body["response_format"] = {"type": "json_object"}
            if body.get("stream") is True:
                body["stream_options"] = {"include_usage": True}
        else:
            apply_declared_request_rules(body, request, self.adaptation_rules)

        reasoning = request.generation.reasoning
        if reasoning is None or reasoning.mode == LlmReasoningMode.DEFAULT:
            return body

        if self.adaptation_rules is None:
            _validate_reasoning_mode(request)

        if reasoning.mode == LlmReasoningMode.OFF:
            body["thinking"] = {"type": "disabled"}
            return body

        if reasoning.mode == LlmReasoningMode.AUTO:
            body["thinking"] = {"type": "auto"}
            return body

        if reasoning.mode == LlmReasoningMode.ENABLED:
            body["thinking"] = {"type": "enabled"}
            return body

        return body

    def apply_openai_responses_body(
        self,
        body: dict[str, object],
        request: ChatCompletionRequest,
    ) -> dict[str, object]:
        reasoning = request.generation.reasoning
        if reasoning is None or reasoning.mode == LlmReasoningMode.DEFAULT:
            return body

        if self.adaptation_rules is None:
            _validate_reasoning_mode(request)
        else:
            apply_declared_request_rules(body, request, self.adaptation_rules)

        if reasoning.mode == LlmReasoningMode.OFF:
            body.pop("reasoning", None)
            body["thinking"] = {"type": "disabled"}

        return body

    def parse_usage(self, value: object) -> ChatUsage | None:
        return parse_openai_usage(value, read_top_level_cache_tokens=True)


def _validate_reasoning_mode(request: ChatCompletionRequest) -> None:
    reasoning = request.generation.reasoning
    if reasoning is None:
        return

    if reasoning.mode in _DEFAULT_REASONING_MODES:
        return

    raise BadRequestError(
        f"模型 '{request.model_id}' 不支持思考模式 '{reasoning.mode.value}'。"
    )
