from app.core.errors import BadRequestError
from app.domain.llm.chat import ChatCompletionRequest
from app.domain.llm.generation_params import LlmOutputFormat, LlmReasoningMode
from app.domain.llm.provider_adaptation import ProviderAdaptationRules


def apply_declared_request_rules(
    body: dict[str, object],
    request: ChatCompletionRequest,
    rules: ProviderAdaptationRules,
) -> dict[str, object]:
    request_rules = rules.request
    capability_rules = rules.capabilities

    for parameter in request_rules.omit_parameters or ():
        body.pop(parameter, None)

    max_tokens_parameter = request_rules.max_output_tokens_parameter
    if max_tokens_parameter and max_tokens_parameter != "max_tokens":
        max_tokens = body.pop("max_tokens", None)
        if max_tokens is not None:
            body[max_tokens_parameter] = max_tokens

    if (
        request_rules.json_object_response_format is True
        and request.output.format == LlmOutputFormat.JSON_OBJECT
    ):
        body["response_format"] = {"type": "json_object"}

    if request_rules.stream_usage is True and body.get("stream") is True:
        body["stream_options"] = {"include_usage": True}

    reasoning = request.generation.reasoning
    if reasoning is None or reasoning.mode == LlmReasoningMode.DEFAULT:
        return body

    allowed_modes = capability_rules.reasoning_modes
    if allowed_modes is not None and reasoning.mode not in allowed_modes:
        raise BadRequestError(
            f"模型 '{request.model_id}' 不支持思考模式 '{reasoning.mode.value}'。"
        )

    if (
        capability_rules.sampling_disabled_when_reasoning is True
        and reasoning.mode != LlmReasoningMode.OFF
    ):
        for parameter in capability_rules.sampling_parameters or ():
            body.pop(parameter, None)

    toggle_parameter = request_rules.reasoning_toggle_parameter
    if reasoning.mode == LlmReasoningMode.OFF:
        if toggle_parameter and request_rules.reasoning_disabled_value is not None:
            body[toggle_parameter] = request_rules.reasoning_disabled_value
        return body

    if toggle_parameter and request_rules.reasoning_enabled_value is not None:
        body[toggle_parameter] = request_rules.reasoning_enabled_value
    if request_rules.reasoning_effort_parameter:
        body[request_rules.reasoning_effort_parameter] = reasoning.mode.value
    return body
