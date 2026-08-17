import asyncio
import json

import pytest
from pydantic import ValidationError

from app.core.errors import AppError, UpstreamProviderError
from app.domain.llm.chat import (
    ChatCompletionRequest,
    ChatMessage,
    ChatMessageRole,
    ChatProtocolContinuation,
    ChatProtocolContinuationKind,
    ChatStreamEventKind,
    ChatToolCall,
)
from app.domain.llm.provider_catalog import (
    AuthScheme,
    ProviderCatalogEntry,
    ProviderEndpointTemplate,
    ProviderProtocolFamily,
    default_model_discovery_strategy,
)
from app.domain.llm.provider_runtime import ProviderRuntimeConfig
from app.domain.project.project_conversation import ProjectConversationMessage
from app.infra.llm.chat_adapters.anthropic import (
    AnthropicMessagesChatAdapter,
    _build_anthropic_body,
)
from app.infra.llm.chat_adapters.gemini import (
    GeminiGenerateContentChatAdapter,
    _build_gemini_body,
)
from app.infra.llm.chat_adapters.openai_compatible import OpenAICompatibleChatAdapter
from app.repositories.project.conversation_serialization import (
    _message_from_payload,
    _message_to_payload,
)
from app.services.project.conversation_request_messages import (
    build_conversation_request_messages,
)
from app.domain.project.project_conversation import ProjectConversationSessionSettings
from app.domain.llm.generation_params import LlmGenerationParams
from app.infra.llm.provider_profiles import resolve_provider_profile
from app.schemas.llm.chat import ChatCompletionRequestBody
from app.services.llm.chat.request_validation import validate_chat_request_capabilities
from app.services.llm.usage.estimation import estimate_message_tokens


def test_protocol_continuation_survives_storage_and_request_rebuild():
    continuation = ChatProtocolContinuation(
        schema_version=1,
        protocol_family=ProviderProtocolFamily.ANTHROPIC_MESSAGES.value,
        provider_id="anthropic",
        model_id="claude-test",
        kind=ChatProtocolContinuationKind.ANTHROPIC_CONTENT,
        items=({"type": "thinking", "thinking": "plan", "signature": "signed"},),
    )
    stored = ProjectConversationMessage(
        message_id="a1",
        session_id="s1",
        role="assistant",
        content="",
        thinking_content="plan",
        usage=None,
        provider_id="anthropic",
        model_id="claude-test",
        status="done",
        created_at="2026-08-15T00:00:00+00:00",
        updated_at="2026-08-15T00:00:00+00:00",
        tool_calls=(ChatToolCall(call_id="call-1", name="read_file", arguments="{}"),),
        protocol_continuation=continuation,
    )

    restored = _message_from_payload(_message_to_payload(stored))
    request_messages = build_conversation_request_messages(
        (
            restored,
            ProjectConversationMessage(
                message_id="t1",
                session_id="s1",
                role="tool",
                content='{"result":"ok"}',
                thinking_content="",
                usage=None,
                provider_id=None,
                model_id=None,
                status="done",
                created_at="2026-08-15T00:00:01+00:00",
                updated_at="2026-08-15T00:00:01+00:00",
                name="read_file",
                tool_call_id="call-1",
            ),
        ),
        None,
        ProjectConversationSessionSettings(),
    )

    assert restored.protocol_continuation == continuation
    assert request_messages[0].protocol_continuation == continuation


def test_full_native_continuation_is_not_double_counted_with_normalized_fields():
    continuation = ChatProtocolContinuation(
        schema_version=1,
        protocol_family=ProviderProtocolFamily.GEMINI_GENERATE_CONTENT.value,
        provider_id="gemini",
        model_id="gemini-test",
        kind=ChatProtocolContinuationKind.GEMINI_PARTS,
        items=({"text": "answer", "thoughtSignature": "signed"},),
    )
    normalized = ChatMessage(
        role=ChatMessageRole.ASSISTANT,
        content="duplicated visible answer " * 100,
        thinking_content="duplicated thinking " * 100,
        tool_calls=(ChatToolCall(call_id="call-1", name="read_file", arguments="{}"),),
        protocol_continuation=continuation,
    )
    native_only = ChatMessage(
        role=ChatMessageRole.ASSISTANT,
        content="",
        protocol_continuation=continuation,
    )

    assert estimate_message_tokens(normalized) == estimate_message_tokens(native_only)


def test_anthropic_stream_requires_message_stop_and_preserves_signed_blocks():
    payloads = [
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "thinking", "thinking": ""},
        },
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "thinking_delta", "thinking": "plan"},
        },
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "signature_delta", "signature": "signed"},
        },
        {"type": "content_block_stop", "index": 0},
        {"type": "message_delta", "delta": {"stop_reason": "tool_use"}},
        {"type": "message_stop"},
    ]
    request = _request("anthropic", "claude-test")
    events = asyncio.run(
        _collect_anthropic(payloads, request)
    )

    assert [event.kind for event in events] == [
        ChatStreamEventKind.THINKING_DELTA,
        ChatStreamEventKind.PROTOCOL_CONTINUATION,
        ChatStreamEventKind.DONE,
    ]
    assert events[1].protocol_continuation.items == (
        {"type": "thinking", "thinking": "plan", "signature": "signed"},
    )
    assert events[2].finish_reason == "tool_use"

    incomplete = asyncio.run(_collect_anthropic(payloads[:-1], request))
    assert incomplete[-1].kind == ChatStreamEventKind.ERROR
    assert incomplete[-1].error_code == "upstream_stream_incomplete"

    token_limited = asyncio.run(
        _collect_anthropic(
            [
                {"type": "message_delta", "delta": {"stop_reason": "max_tokens"}},
                {"type": "message_stop"},
            ],
            request,
        )
    )
    assert token_limited[-1].kind == ChatStreamEventKind.ERROR
    assert token_limited[-1].error_code == "upstream_response_incomplete"

    malformed_tool = asyncio.run(
        _collect_anthropic(
            [
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {
                        "type": "tool_use",
                        "id": "call-1",
                        "name": "read_file",
                        "input": {},
                    },
                },
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "input_json_delta", "partial_json": "{bad"},
                },
                {"type": "content_block_stop", "index": 0},
            ],
            request,
        )
    )
    assert malformed_tool[-1].kind == ChatStreamEventKind.ERROR
    assert malformed_tool[-1].error_code == "upstream_stream_protocol_error"


def test_anthropic_complete_preserves_signed_content_and_rejects_empty_shape():
    request = _request("anthropic", "claude-test")
    provider = _provider(ProviderProtocolFamily.ANTHROPIC_MESSAGES, request.provider_id)

    async def complete():
        async def post_json(_url, _headers, _body):
            return {
                "type": "message",
                "content": [
                    {"type": "thinking", "thinking": "plan", "signature": "signed"},
                    {"type": "text", "text": "answer"},
                ],
                "stop_reason": "end_turn",
            }

        return await AnthropicMessagesChatAdapter().complete(
            provider_template=provider,
            runtime_config=_runtime(request.provider_id),
            api_key="test",
            request=request,
            post_json=post_json,
        )

    result = asyncio.run(complete())
    assert result.message.content == "answer"
    assert result.message.protocol_continuation.items[0]["signature"] == "signed"

    async def malformed():
        async def post_json(_url, _headers, _body):
            return {"type": "message"}

        return await AnthropicMessagesChatAdapter().complete(
            provider_template=provider,
            runtime_config=_runtime(request.provider_id),
            api_key="test",
            request=request,
            post_json=post_json,
        )

    with pytest.raises(UpstreamProviderError) as caught:
        asyncio.run(malformed())
    assert caught.value.code == "upstream_response_malformed"


def test_anthropic_replays_private_state_only_for_same_provider_and_model():
    continuation = ChatProtocolContinuation(
        schema_version=1,
        protocol_family=ProviderProtocolFamily.ANTHROPIC_MESSAGES.value,
        provider_id="anthropic",
        model_id="claude-test",
        kind=ChatProtocolContinuationKind.ANTHROPIC_CONTENT,
        items=({"type": "thinking", "thinking": "plan", "signature": "signed"},),
    )
    assistant = ChatMessage(
        role=ChatMessageRole.ASSISTANT,
        content="",
        protocol_continuation=continuation,
    )
    matching = _request("anthropic", "claude-test", messages=(assistant,))
    switched = _request("anthropic", "claude-other", messages=(assistant,))

    assert _build_anthropic_body(matching, stream=False)["messages"][0]["content"] == list(
        continuation.items
    )
    assert _build_anthropic_body(switched, stream=False)["messages"][0]["content"] != list(
        continuation.items
    )


def test_gemini_stream_preserves_thought_signature_and_function_call_id():
    payloads = [
        {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"thought": True, "text": "plan", "thoughtSignature": "signed"},
                            {"functionCall": {"id": "call-7", "name": "read_file", "args": {}}},
                        ]
                    },
                    "finishReason": "STOP",
                }
            ]
        }
    ]
    request = _request("gemini", "gemini-test")
    events = asyncio.run(_collect_gemini(payloads, request))

    assert [event.kind for event in events] == [
        ChatStreamEventKind.THINKING_DELTA,
        ChatStreamEventKind.TOOL_CALL,
        ChatStreamEventKind.PROTOCOL_CONTINUATION,
        ChatStreamEventKind.DONE,
    ]
    assert events[1].tool_call.call_id == "call-7"
    assert events[2].protocol_continuation.items[0]["thoughtSignature"] == "signed"

    limited_payloads = json.loads(json.dumps(payloads))
    limited_payloads[0]["candidates"][0]["finishReason"] = "MAX_TOKENS"
    limited = asyncio.run(_collect_gemini(limited_payloads, request))
    assert limited[-1].kind == ChatStreamEventKind.ERROR
    assert limited[-1].error_code == "upstream_response_incomplete"

    assistant = ChatMessage(
        role=ChatMessageRole.ASSISTANT,
        content="",
        tool_calls=(events[1].tool_call,),
        protocol_continuation=events[2].protocol_continuation,
    )
    replay = _build_gemini_body(
        _request("gemini", "gemini-test", messages=(assistant,))
    )
    assert replay["contents"][0]["parts"] == list(events[2].protocol_continuation.items)


def test_openai_compatible_eof_without_completion_evidence_is_an_error():
    request = _request("custom", "model")

    async def collect(include_done_marker: bool, finish_reason=None):
        async def stream_body(_url, _headers, _body):
            payload = {"choices": [{"delta": {"content": "partial"}}]}
            if finish_reason is not None:
                payload["choices"][0]["finish_reason"] = finish_reason
            yield f"data: {json.dumps(payload)}\n\n".encode()
            if include_done_marker:
                yield b"data: [DONE]\n\n"

        provider = _provider(ProviderProtocolFamily.OPENAI_COMPATIBLE, request.provider_id)
        return [
            event
            async for event in OpenAICompatibleChatAdapter().stream(
                provider_template=provider,
                runtime_config=_runtime(request.provider_id),
                api_key="test",
                request=request,
                stream_body=stream_body,
            )
        ]

    incomplete = asyncio.run(collect(False))
    assert [event.kind for event in incomplete] == [
        ChatStreamEventKind.DELTA,
        ChatStreamEventKind.ERROR,
    ]
    assert incomplete[-1].error_code == "upstream_stream_incomplete"

    complete = asyncio.run(collect(True))
    assert [event.kind for event in complete] == [
        ChatStreamEventKind.DELTA,
        ChatStreamEventKind.DONE,
    ]

    limited = asyncio.run(collect(True, "length"))
    assert limited[-1].kind == ChatStreamEventKind.ERROR
    assert limited[-1].error_code == "upstream_response_incomplete"


def test_legacy_top_level_generation_fields_are_rejected():
    with pytest.raises(ValidationError):
        ChatCompletionRequestBody.model_validate(
            {
                "provider_id": "openai",
                "model_id": "gpt-test",
                "messages": [],
                "temperature": 0.5,
                "max_tokens": 100,
            }
        )


def test_backend_rejects_parameters_outside_resolved_capabilities():
    provider = _provider(ProviderProtocolFamily.OPENAI_COMPATIBLE, "custom")
    capabilities = resolve_provider_profile(provider, "model").resolve_capabilities(
        provider,
        "model",
    )
    request = ChatCompletionRequest(
        provider_id="custom",
        model_id="model",
        messages=(ChatMessage(role=ChatMessageRole.USER, content="test"),),
        generation=LlmGenerationParams(max_output_tokens=0),
    )

    with pytest.raises(AppError) as caught:
        validate_chat_request_capabilities(request, capabilities)

    assert caught.value.code == "llm_parameter_out_of_range"


def test_unknown_profile_fails_instead_of_silently_using_generic_behavior():
    provider = _provider(ProviderProtocolFamily.OPENAI_COMPATIBLE, "custom")
    provider = ProviderCatalogEntry(
        provider_id=provider.provider_id,
        display_name=provider.display_name,
        profile_id="typo-profile",
        protocol_family=provider.protocol_family,
        generation_auth_schemes=provider.generation_auth_schemes,
        model_discovery_strategy=provider.model_discovery_strategy,
        model_discovery_auth_scheme=provider.model_discovery_auth_scheme,
        endpoints=provider.endpoints,
    )

    with pytest.raises(AppError) as caught:
        resolve_provider_profile(provider)

    assert caught.value.code == "provider_profile_not_registered"


async def _collect_anthropic(payloads, request):
    async def stream_body(_url, _headers, _body):
        for payload in payloads:
            yield f"data: {json.dumps(payload)}\n\n".encode()

    provider = _provider(ProviderProtocolFamily.ANTHROPIC_MESSAGES, request.provider_id)
    return [
        event
        async for event in AnthropicMessagesChatAdapter().stream(
            provider_template=provider,
            runtime_config=_runtime(request.provider_id),
            api_key="test",
            request=request,
            stream_body=stream_body,
        )
    ]


async def _collect_gemini(payloads, request):
    async def stream_body(_url, _headers, _body):
        for payload in payloads:
            yield f"data: {json.dumps(payload)}\n\n".encode()

    provider = _provider(ProviderProtocolFamily.GEMINI_GENERATE_CONTENT, request.provider_id)
    return [
        event
        async for event in GeminiGenerateContentChatAdapter().stream(
            provider_template=provider,
            runtime_config=_runtime(request.provider_id),
            api_key="test",
            request=request,
            stream_body=stream_body,
        )
    ]


def _request(provider_id, model_id, *, messages=None):
    return ChatCompletionRequest(
        provider_id=provider_id,
        model_id=model_id,
        messages=messages or (ChatMessage(role=ChatMessageRole.USER, content="test"),),
    )


def _runtime(provider_id):
    return ProviderRuntimeConfig(
        provider_id=provider_id,
        display_name=provider_id,
        api_base_url="https://example.test/v1/models/{model}:{action}",
    )


def _provider(protocol_family, provider_id):
    return ProviderCatalogEntry(
        provider_id=provider_id,
        display_name=provider_id,
        profile_id="generic",
        protocol_family=protocol_family,
        generation_auth_schemes={protocol_family: AuthScheme.BEARER_TOKEN},
        model_discovery_strategy=default_model_discovery_strategy(protocol_family),
        model_discovery_auth_scheme=AuthScheme.BEARER_TOKEN,
        endpoints=ProviderEndpointTemplate(
            api_base_url="https://example.test",
            text_generation_url_template="v1/models/{model}:{action}",
            model_discovery_url=None,
        ),
    )
