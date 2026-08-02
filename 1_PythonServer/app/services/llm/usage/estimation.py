from __future__ import annotations

import json
import math
import unicodedata
from typing import Any

from app.domain.llm.chat import (
    ChatCompletionRequest,
    ChatMessage,
    ChatMessageContentPartType,
    ChatUsage,
)
from app.domain.llm.token_estimation_settings import (
    DEFAULT_TOKEN_ESTIMATION_SETTINGS,
    TokenEstimationSettings,
)
from app.domain.llm.message_timestamp import model_visible_message_content


def estimate_token_count(
    text: str,
    settings: TokenEstimationSettings = DEFAULT_TOKEN_ESTIMATION_SETTINGS,
) -> int:
    if not text:
        return 0
    tokens = 0
    ascii_run = 0
    other_run = 0
    for char in text:
        if char.isspace():
            tokens += _run_tokens(ascii_run, settings.ascii_chars_per_token)
            tokens += _run_tokens(other_run, settings.other_chars_per_token)
            ascii_run = 0
            other_run = 0
            continue
        if char.isascii() and char.isalnum():
            tokens += _run_tokens(other_run, settings.other_chars_per_token)
            other_run = 0
            ascii_run += 1
            continue

        tokens += _run_tokens(ascii_run, settings.ascii_chars_per_token)
        ascii_run = 0
        if _is_combining_or_variation(char):
            continue
        other_run += 1

    return (
        tokens
        + _run_tokens(ascii_run, settings.ascii_chars_per_token)
        + _run_tokens(other_run, settings.other_chars_per_token)
    )


def estimate_json_token_count(
    value: Any,
    settings: TokenEstimationSettings = DEFAULT_TOKEN_ESTIMATION_SETTINGS,
) -> int:
    return estimate_token_count(
        json.dumps(value, ensure_ascii=False, separators=(",", ":")),
        settings,
    )


def estimate_request_context_tokens(
    request: ChatCompletionRequest,
    settings: TokenEstimationSettings = DEFAULT_TOKEN_ESTIMATION_SETTINGS,
) -> int:
    total = sum(
        _estimate_message_tokens(message, settings)
        for message in request.messages
    )
    total += estimate_json_token_count(
        [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            }
            for tool in request.tools
        ],
        settings,
    )
    return max(total, 1)


def estimate_message_tokens(
    message: ChatMessage,
    settings: TokenEstimationSettings = DEFAULT_TOKEN_ESTIMATION_SETTINGS,
) -> int:
    return max(_estimate_message_tokens(message, settings), 1)


def estimate_completion_tokens(
    message: ChatMessage,
    *,
    thinking_content: str = "",
    settings: TokenEstimationSettings = DEFAULT_TOKEN_ESTIMATION_SETTINGS,
) -> int:
    total = estimate_token_count(message.content, settings)
    total += estimate_token_count(
        thinking_content or message.thinking_content,
        settings,
    )
    for tool_call in message.tool_calls:
        total += estimate_token_count(tool_call.call_id, settings)
        total += estimate_token_count(tool_call.name, settings)
        total += estimate_token_count(tool_call.arguments, settings)
    for part in message.content_parts:
        if part.type == ChatMessageContentPartType.TEXT:
            total += estimate_token_count(part.text or "", settings)
        else:
            total += settings.image_placeholder_tokens
    if message.provider_output_items:
        total += estimate_json_token_count(message.provider_output_items, settings)
    return max(total, 1)


def complete_usage_with_estimates(
    *,
    request: ChatCompletionRequest,
    provider_usage: ChatUsage | None,
    response_message: ChatMessage,
    thinking_content: str = "",
    settings: TokenEstimationSettings = DEFAULT_TOKEN_ESTIMATION_SETTINGS,
) -> ChatUsage:
    usage = provider_usage or ChatUsage()
    estimated_fields = set(usage.estimated_fields)

    prompt_tokens = usage.prompt_tokens
    if prompt_tokens is None:
        prompt_tokens = estimate_request_context_tokens(request, settings)
        estimated_fields.add("prompt_tokens")

    completion_tokens = usage.completion_tokens
    if completion_tokens is None:
        completion_tokens = estimate_completion_tokens(
            response_message,
            thinking_content=thinking_content,
            settings=settings,
        )
        estimated_fields.add("completion_tokens")

    total_tokens = usage.total_tokens
    if total_tokens is None:
        total_tokens = prompt_tokens + completion_tokens
        estimated_fields.add("total_tokens")

    return ChatUsage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        prompt_cache_hit_tokens=usage.prompt_cache_hit_tokens,
        prompt_cache_miss_tokens=usage.prompt_cache_miss_tokens,
        reasoning_tokens=usage.reasoning_tokens,
        estimated_fields=tuple(sorted(estimated_fields)),
    )


def _estimate_message_tokens(
    message: ChatMessage,
    settings: TokenEstimationSettings,
) -> int:
    total = settings.message_overhead_tokens
    total += estimate_token_count(message.role.value, settings)
    total += estimate_token_count(model_visible_message_content(message), settings)
    total += estimate_token_count(message.thinking_content, settings)
    total += estimate_token_count(message.name or "", settings)
    total += estimate_token_count(message.tool_call_id or "", settings)
    for tool_call in message.tool_calls:
        total += estimate_token_count(tool_call.call_id, settings)
        total += estimate_token_count(tool_call.name, settings)
        total += estimate_token_count(tool_call.arguments, settings)
    for part in message.content_parts:
        if part.type == ChatMessageContentPartType.TEXT:
            total += estimate_token_count(part.text or "", settings)
        else:
            total += settings.image_placeholder_tokens
    if message.provider_output_items:
        total += estimate_json_token_count(message.provider_output_items, settings)
    return total


def _run_tokens(length: int, chars_per_token: float) -> int:
    if length <= 0:
        return 0
    return max(1, math.ceil(length / chars_per_token))


def _is_combining_or_variation(char: str) -> bool:
    if "\ufe00" <= char <= "\ufe0f":
        return True
    return unicodedata.category(char).startswith("M")
