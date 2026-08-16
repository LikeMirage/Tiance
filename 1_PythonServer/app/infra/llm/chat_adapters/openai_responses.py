from collections.abc import AsyncGenerator

from app.core.errors import UpstreamProviderError
from app.domain.llm.chat import (
    ChatCompletionRequest,
    ChatCompletionResult,
    ChatMessage,
    ChatMessageRole,
    ChatProtocolContinuationKind,
    ChatStreamEvent,
    ChatStreamEventKind,
    ChatToolCall,
)
from app.domain.llm.provider_catalog import ProviderCatalogEntry
from app.domain.llm.provider_runtime import ProviderRuntimeConfig
from app.infra.llm.chat_adapters.base import PostJson, StreamBody
from app.infra.llm.chat_adapters.common import (
    SSE_DONE,
    _build_headers,
    _build_stream_headers,
    _iter_sse_payloads,
    _optional_int,
    _optional_str,
    _protocol_error_event,
)
from app.infra.llm.chat_adapters.continuation import build_protocol_continuation
from app.infra.llm.chat_adapters.openai_responses_parsing import (
    _extract_responses_continuation_items,
    _extract_responses_reasoning_text,
    _extract_responses_text,
    _extract_responses_tool_calls,
    _output_item_identity,
    _parse_responses_usage,
    _responses_continuation_item,
    _responses_error_message,
    _responses_incomplete_message,
    _responses_stream_tool_call,
)
from app.infra.llm.chat_adapters.openai_responses_payloads import (
    _build_responses_body,
    _message_to_responses_payload,
)
from app.infra.llm.provider_profiles import resolve_provider_profile
from app.infra.llm.provider_profiles.base import ProviderProfile
from app.infra.llm.request_auth import apply_auth_to_url


class OpenAIResponsesChatAdapter:
    async def complete(
        self,
        *,
        provider_template: ProviderCatalogEntry,
        runtime_config: ProviderRuntimeConfig,
        api_key: str,
        request: ChatCompletionRequest,
        post_json: PostJson,
    ) -> ChatCompletionResult:
        provider_profile = resolve_provider_profile(provider_template, request.model_id)
        payload = await post_json(
            apply_auth_to_url(
                runtime_config.api_base_url,
                provider_template.auth_scheme,
                api_key,
            ),
            _build_headers(provider_template.auth_scheme, api_key),
            _build_profiled_responses_body(
                provider_profile,
                request,
                stream=False,
            ),
        )
        status = str(payload.get("status") or "")
        if status == "incomplete":
            raise UpstreamProviderError(
                _responses_incomplete_message(payload),
                code="upstream_response_incomplete",
            )
        if status == "failed":
            raise UpstreamProviderError(
                _responses_error_message(payload),
                code="upstream_response_failed",
            )
        if status != "completed" or not isinstance(payload.get("output"), list):
            raise UpstreamProviderError(
                "上游 Responses 返回缺少完整结果结构。",
                code="upstream_response_malformed",
            )
        text = _extract_responses_text(payload)
        reasoning_text = _extract_responses_reasoning_text(payload)
        continuation = build_protocol_continuation(
            request,
            provider_template.protocol_family,
            ChatProtocolContinuationKind.OPENAI_RESPONSES_OUTPUT,
            _extract_responses_continuation_items(payload),
        )
        return ChatCompletionResult(
            provider_id=request.provider_id,
            model_id=request.model_id,
            message=ChatMessage(
                role=ChatMessageRole.ASSISTANT,
                content=text,
                tool_calls=_extract_responses_tool_calls(payload),
                thinking_content=reasoning_text,
                protocol_continuation=continuation,
            ),
            thinking_content=reasoning_text,
            finish_reason=_optional_str(payload.get("status")),
            usage=_parse_responses_usage(payload.get("usage")),
            raw_response=payload,
        )

    async def stream(
        self,
        *,
        provider_template: ProviderCatalogEntry,
        runtime_config: ProviderRuntimeConfig,
        api_key: str,
        request: ChatCompletionRequest,
        stream_body: StreamBody,
    ) -> AsyncGenerator[ChatStreamEvent, None]:
        provider_profile = resolve_provider_profile(provider_template, request.model_id)
        tool_call_parts: dict[int, ChatToolCall] = {}
        emitted_tool_call_ids: set[str] = set()
        emitted_continuation_item_ids: set[str] = set()
        continuation_items: list[dict[str, object]] = []
        did_emit_text_delta = False
        did_emit_reasoning_delta = False
        reasoning_delta_event_type: str | None = None
        async for payload in _iter_sse_payloads(
            stream_body(
                apply_auth_to_url(
                    runtime_config.api_base_url,
                    provider_template.auth_scheme,
                    api_key,
                ),
                _build_stream_headers(provider_template.auth_scheme, api_key),
                _build_profiled_responses_body(
                    provider_profile,
                    request,
                    stream=True,
                ),
            )
        ):
            if payload is SSE_DONE:
                continue
            if payload is None:
                yield _protocol_error_event()
                return
            event_type = str(payload.get("type") or "")
            if event_type == "response.output_text.delta" and payload.get("delta"):
                did_emit_text_delta = True
                yield ChatStreamEvent(
                    kind=ChatStreamEventKind.DELTA,
                    content=str(payload["delta"]),
                )
            elif event_type == "response.refusal.delta" and payload.get("delta"):
                did_emit_text_delta = True
                yield ChatStreamEvent(
                    kind=ChatStreamEventKind.DELTA,
                    content=str(payload["delta"]),
                )
            elif event_type in {
                "response.reasoning_text.delta",
                "response.reasoning_summary_text.delta",
            } and payload.get("delta"):
                if reasoning_delta_event_type is None:
                    reasoning_delta_event_type = event_type
                if reasoning_delta_event_type != event_type:
                    continue
                did_emit_reasoning_delta = True
                yield ChatStreamEvent(
                    kind=ChatStreamEventKind.THINKING_DELTA,
                    content=str(payload["delta"]),
                )
            elif event_type == "response.output_item.added":
                tool_call = _responses_stream_tool_call(payload.get("item"))
                output_index = _optional_int(payload.get("output_index"))
                if tool_call is not None and output_index is not None:
                    tool_call_parts[output_index] = tool_call
                    yield ChatStreamEvent(
                        kind=ChatStreamEventKind.TOOL_CALL_DELTA,
                        tool_call=tool_call,
                    )
            elif event_type == "response.function_call_arguments.delta":
                output_index = _optional_int(payload.get("output_index"))
                arguments_delta = str(payload.get("delta") or "")
                tool_call = (
                    tool_call_parts.get(output_index)
                    if output_index is not None
                    else None
                )
                if tool_call is None:
                    yield ChatStreamEvent(kind=ChatStreamEventKind.TOOL_CALL_DELTA)
                    continue
                tool_call_parts[output_index] = ChatToolCall(
                    call_id=tool_call.call_id,
                    name=tool_call.name,
                    arguments=tool_call.arguments + arguments_delta,
                )
                yield ChatStreamEvent(
                    kind=ChatStreamEventKind.TOOL_CALL_DELTA,
                    tool_call=ChatToolCall(
                        call_id=tool_call.call_id,
                        name=tool_call.name,
                        arguments=arguments_delta,
                    ),
                )
            elif event_type == "response.output_item.done":
                item = payload.get("item")
                continuation_item = _responses_continuation_item(item)
                if request.tools and continuation_item is not None:
                    emitted_continuation_item_ids.add(
                        _output_item_identity(continuation_item)
                    )
                    continuation_items.append(continuation_item)
                tool_call = _responses_stream_tool_call(item)
                if tool_call is not None:
                    emitted_tool_call_ids.add(tool_call.call_id)
                    output_index = _optional_int(payload.get("output_index"))
                    if output_index is not None:
                        tool_call_parts.pop(output_index, None)
                    yield ChatStreamEvent(
                        kind=ChatStreamEventKind.TOOL_CALL,
                        tool_call=tool_call,
                    )
            elif event_type == "response.completed":
                response = payload.get("response")
                if isinstance(response, dict):
                    if not did_emit_text_delta:
                        completed_text = _extract_responses_text(response)
                        if completed_text:
                            yield ChatStreamEvent(
                                kind=ChatStreamEventKind.DELTA,
                                content=completed_text,
                            )
                            did_emit_text_delta = True
                    if not did_emit_reasoning_delta:
                        reasoning_text = _extract_responses_reasoning_text(response)
                        if reasoning_text:
                            yield ChatStreamEvent(
                                kind=ChatStreamEventKind.THINKING_DELTA,
                                content=reasoning_text,
                            )
                            did_emit_reasoning_delta = True
                    if request.tools:
                        for continuation_item in _extract_responses_continuation_items(response):
                            identity = _output_item_identity(continuation_item)
                            if identity in emitted_continuation_item_ids:
                                continue
                            emitted_continuation_item_ids.add(identity)
                            continuation_items.append(continuation_item)
                    for tool_call in _extract_responses_tool_calls(response):
                        if tool_call.call_id in emitted_tool_call_ids:
                            continue
                        emitted_tool_call_ids.add(tool_call.call_id)
                        yield ChatStreamEvent(
                            kind=ChatStreamEventKind.TOOL_CALL,
                            tool_call=tool_call,
                        )
                    usage = _parse_responses_usage(response.get("usage"))
                    if usage is not None:
                        yield ChatStreamEvent(
                            kind=ChatStreamEventKind.USAGE,
                            usage=usage,
                        )
                    status = str(response.get("status") or "")
                    if status == "incomplete":
                        yield ChatStreamEvent(
                            kind=ChatStreamEventKind.ERROR,
                            error=_responses_incomplete_message(response),
                            error_code="upstream_response_incomplete",
                        )
                        return
                    if status == "failed":
                        yield ChatStreamEvent(
                            kind=ChatStreamEventKind.ERROR,
                            error=_responses_error_message(response),
                            error_code="upstream_response_failed",
                        )
                        return
                    if status != "completed":
                        yield ChatStreamEvent(
                            kind=ChatStreamEventKind.ERROR,
                            error="上游 Responses 完成事件缺少 completed 状态。",
                            error_code="upstream_response_malformed",
                        )
                        return
                    continuation = build_protocol_continuation(
                        request,
                        provider_template.protocol_family,
                        ChatProtocolContinuationKind.OPENAI_RESPONSES_OUTPUT,
                        tuple(continuation_items),
                    )
                    if continuation is not None:
                        yield ChatStreamEvent(
                            kind=ChatStreamEventKind.PROTOCOL_CONTINUATION,
                            protocol_continuation=continuation,
                        )
                    yield ChatStreamEvent(
                        kind=ChatStreamEventKind.DONE,
                        finish_reason=_optional_str(response.get("status")),
                    )
                    return
            elif event_type == "response.incomplete":
                response = payload.get("response")
                if isinstance(response, dict):
                    usage = _parse_responses_usage(response.get("usage"))
                    if usage is not None:
                        yield ChatStreamEvent(
                            kind=ChatStreamEventKind.USAGE,
                            usage=usage,
                        )
                yield ChatStreamEvent(
                    kind=ChatStreamEventKind.ERROR,
                    error=_responses_incomplete_message(response),
                    error_code="upstream_response_incomplete",
                )
                return
            elif event_type == "response.failed":
                yield ChatStreamEvent(
                    kind=ChatStreamEventKind.ERROR,
                    error=_responses_error_message(payload),
                    error_code="upstream_response_failed",
                )
                return
        yield ChatStreamEvent(
            kind=ChatStreamEventKind.ERROR,
            error="上游 Responses 流在完成事件前意外结束，当前回答可能不完整。",
            error_code="upstream_stream_incomplete",
        )


def _build_profiled_responses_body(
    provider_profile: ProviderProfile,
    request: ChatCompletionRequest,
    *,
    stream: bool,
) -> dict[str, object]:
    body = _build_responses_body(
        request,
        stream=stream,
        include_message_phase=provider_profile.include_responses_message_phase,
    )
    return provider_profile.apply_openai_responses_body(body, request)
