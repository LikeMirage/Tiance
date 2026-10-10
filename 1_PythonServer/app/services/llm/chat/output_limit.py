from app.domain.llm.chat import ChatCompletionRequest, ChatStreamEvent, ChatUsage
from app.domain.llm.output_limit import OUTPUT_LIMIT_TOLERANCE


def is_output_limit(
    request: ChatCompletionRequest,
    event: ChatStreamEvent,
    usage: ChatUsage | None,
) -> bool:
    if event.finish_reason in {"length", "max_tokens", "MAX_TOKENS", "max_output_tokens"}:
        return True
    if event.error_code == "upstream_output_limit":
        return True
    # A normally completed response never enters this function. Explicit other
    # termination reasons must not be mistaken for an output limit.
    if event.finish_reason or event.error_code not in {
        "upstream_stream_incomplete", "upstream_response_incomplete",
    }:
        return False
    maximum = request.generation.max_output_tokens
    if usage is None or maximum is None or usage.completion_tokens is None:
        return False
    if "completion_tokens" in usage.estimated_fields:
        return False
    return usage.completion_tokens >= maximum * (1 - OUTPUT_LIMIT_TOLERANCE)
