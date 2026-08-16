from app.core.errors import AppError
from app.domain.llm.chat import ChatCompletionRequest
from app.domain.llm.generation_params import LlmReasoningMode
from app.domain.llm.runtime_capabilities import LlmRuntimeCapabilities


def validate_chat_request_capabilities(
    request: ChatCompletionRequest,
    capabilities: LlmRuntimeCapabilities,
) -> None:
    if request.output.format not in capabilities.output_formats:
        _unsupported(f"当前模型不支持输出格式 '{request.output.format.value}'。")

    reasoning = request.generation.reasoning
    reasoning_enabled = bool(
        reasoning is not None
        and reasoning.mode not in {LlmReasoningMode.DEFAULT, LlmReasoningMode.OFF}
    )
    if reasoning_enabled:
        if not capabilities.reasoning.supported:
            _unsupported("当前模型不支持思考模式。")
        if (
            capabilities.reasoning.modes
            and reasoning is not None
            and reasoning.mode not in capabilities.reasoning.modes
        ):
            _unsupported(f"当前模型不支持思考档位 '{reasoning.mode.value}'。")

    sampling_values = {
        "temperature": request.generation.temperature,
        "top_p": request.generation.top_p,
        "presence_penalty": request.generation.presence_penalty,
        "frequency_penalty": request.generation.frequency_penalty,
    }
    configured_sampling = tuple(
        name for name, value in sampling_values.items() if value is not None
    )
    if configured_sampling and not capabilities.sampling.supported:
        _unsupported("当前模型不支持采样参数。")
    unsupported_sampling = tuple(
        name
        for name in configured_sampling
        if name not in capabilities.sampling.parameters
    )
    if unsupported_sampling:
        _unsupported(
            f"当前模型不支持采样参数：{', '.join(unsupported_sampling)}。"
        )
    if (
        configured_sampling
        and reasoning_enabled
        and capabilities.sampling.disabled_when_reasoning
    ):
        _unsupported(
            capabilities.sampling.disabled_reason_when_reasoning
            or "当前模型开启思考模式时不支持采样参数。"
        )

    max_output_tokens = request.generation.max_output_tokens
    if max_output_tokens is not None:
        limits = capabilities.max_output_tokens
        if not limits.supported:
            _unsupported("当前模型不支持设置最大输出 Token。")
        if limits.min is not None and max_output_tokens < limits.min:
            _out_of_range(f"最大输出 Token 不能小于 {limits.min}。")
        if limits.max is not None and max_output_tokens > limits.max:
            _out_of_range(f"最大输出 Token 不能大于 {limits.max}。")

    if request.tools and not capabilities.tool_calling.supported:
        _unsupported("当前模型不支持工具调用。")


def _unsupported(message: str) -> None:
    raise AppError(message, code="llm_capability_not_supported")


def _out_of_range(message: str) -> None:
    raise AppError(message, code="llm_parameter_out_of_range")
