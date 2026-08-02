from app.domain.llm.chat import ChatUsage


def usage_to_payload(usage: ChatUsage) -> dict[str, object]:
    payload: dict[str, object] = {
        "prompt_tokens": usage.prompt_tokens,
        "completion_tokens": usage.completion_tokens,
        "total_tokens": usage.total_tokens,
        "prompt_cache_hit_tokens": usage.prompt_cache_hit_tokens,
        "prompt_cache_miss_tokens": usage.prompt_cache_miss_tokens,
        "reasoning_tokens": usage.reasoning_tokens,
    }
    if usage.estimated_fields:
        payload["estimated_fields"] = list(usage.estimated_fields)
    return payload


def merge_usage(current: ChatUsage | None, incoming: ChatUsage) -> ChatUsage:
    if current is None:
        return incoming
    prompt_tokens = _sum_usage_field(current.prompt_tokens, incoming.prompt_tokens)
    completion_tokens = _sum_usage_field(current.completion_tokens, incoming.completion_tokens)
    total_tokens = _sum_usage_field(current.total_tokens, incoming.total_tokens)
    if total_tokens is None and (prompt_tokens is not None or completion_tokens is not None):
        total_tokens = (prompt_tokens or 0) + (completion_tokens or 0)
    return ChatUsage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        prompt_cache_hit_tokens=_sum_usage_field(
            current.prompt_cache_hit_tokens,
            incoming.prompt_cache_hit_tokens,
        ),
        prompt_cache_miss_tokens=_sum_usage_field(
            current.prompt_cache_miss_tokens,
            incoming.prompt_cache_miss_tokens,
        ),
        reasoning_tokens=_sum_usage_field(current.reasoning_tokens, incoming.reasoning_tokens),
        estimated_fields=tuple(sorted({
            *current.estimated_fields,
            *incoming.estimated_fields,
        })),
    )


def _sum_usage_field(left: int | None, right: int | None) -> int | None:
    if left is None and right is None:
        return None
    return (left or 0) + (right or 0)
