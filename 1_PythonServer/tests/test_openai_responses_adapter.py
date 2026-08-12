import asyncio
import json
from dataclasses import replace

import pytest

from app.core.errors import UpstreamProviderError
from app.domain.llm.chat import (
    ChatCompletionRequest,
    ChatMessage,
    ChatMessageRole,
    ChatStreamEventKind,
    ChatToolCall,
    ChatToolDefinition,
)
from app.domain.llm.generation_params import (
    LlmGenerationParams,
    LlmReasoningMode,
    LlmReasoningOptions,
)
from app.domain.llm.provider_catalog import (
    AuthScheme,
    ProviderCatalogEntry,
    ProviderEndpointTemplate,
    ProviderProtocolFamily,
    default_model_discovery_strategy,
)
from app.domain.llm.provider_runtime import ProviderRuntimeConfig
from app.infra.llm.chat_adapters.openai_responses import (
    OpenAIResponsesChatAdapter,
    _build_responses_body,
    _message_to_responses_payload,
)
from app.infra.llm.provider_profiles.registry import resolve_provider_profile


def test_responses_stream_emits_tool_argument_deltas_and_detailed_usage():
    payloads = [
        {
            "type": "response.output_item.added",
            "output_index": 0,
            "item": {
                "type": "function_call",
                "call_id": "call-1",
                "name": "write_text_file",
                "arguments": "",
            },
        },
        {
            "type": "response.function_call_arguments.delta",
            "output_index": 0,
            "delta": '{"path":',
        },
        {
            "type": "response.function_call_arguments.delta",
            "output_index": 0,
            "delta": '"test.md"}',
        },
        {
            "type": "response.output_item.done",
            "output_index": 0,
            "item": {
                "type": "function_call",
                "call_id": "call-1",
                "name": "write_text_file",
                "arguments": '{"path":"test.md"}',
            },
        },
        {
            "type": "response.completed",
            "response": {
                "status": "completed",
                "usage": {
                    "input_tokens": 305,
                    "input_tokens_details": {"cached_tokens": 128},
                    "output_tokens": 17,
                    "output_tokens_details": {"reasoning_tokens": 10},
                    "total_tokens": 322,
                },
            },
        },
    ]

    events = asyncio.run(_collect_events(payloads))

    assert [event.kind for event in events] == [
        ChatStreamEventKind.TOOL_CALL_DELTA,
        ChatStreamEventKind.TOOL_CALL_DELTA,
        ChatStreamEventKind.TOOL_CALL_DELTA,
        ChatStreamEventKind.TOOL_CALL,
        ChatStreamEventKind.USAGE,
        ChatStreamEventKind.DONE,
    ]
    assert [events[index].tool_call.arguments for index in range(3)] == [
        "",
        '{"path":',
        '"test.md"}',
    ]
    assert events[3].tool_call.arguments == '{"path":"test.md"}'
    assert events[4].usage.prompt_tokens == 305
    assert events[4].usage.completion_tokens == 17
    assert events[4].usage.total_tokens == 322
    assert events[4].usage.prompt_cache_hit_tokens == 128
    assert events[4].usage.prompt_cache_miss_tokens == 177
    assert events[4].usage.reasoning_tokens == 10


def test_responses_stream_keeps_interleaved_tool_deltas_separate():
    payloads = [
        _tool_added(0, "call-1", "first_tool"),
        _tool_added(1, "call-2", "second_tool"),
        _tool_delta(1, '{"second":true}'),
        _tool_delta(0, '{"first":true}'),
        _tool_done(1, "call-2", "second_tool", '{"second":true}'),
        _tool_done(0, "call-1", "first_tool", '{"first":true}'),
        {
            "type": "response.completed",
            "response": {"status": "completed"},
        },
    ]

    events = asyncio.run(_collect_events(payloads))
    delta_events = [event for event in events if event.kind == ChatStreamEventKind.TOOL_CALL_DELTA]
    complete_events = [event for event in events if event.kind == ChatStreamEventKind.TOOL_CALL]

    assert [event.tool_call.name for event in delta_events] == [
        "first_tool",
        "second_tool",
        "second_tool",
        "first_tool",
    ]
    assert [event.tool_call.arguments for event in delta_events] == [
        "",
        "",
        '{"second":true}',
        '{"first":true}',
    ]
    assert [(event.tool_call.call_id, event.tool_call.arguments) for event in complete_events] == [
        ("call-2", '{"second":true}'),
        ("call-1", '{"first":true}'),
    ]


def test_responses_body_disables_storage_and_sends_reasoning_configuration():
    request = ChatCompletionRequest(
        provider_id="openai",
        model_id="gpt-test",
        messages=(ChatMessage(role=ChatMessageRole.USER, content="test"),),
        tools=(
            ChatToolDefinition(
                name="read_file",
                description="Read a file",
                parameters={"type": "object"},
            ),
        ),
        generation=LlmGenerationParams(
            presence_penalty=0.4,
            frequency_penalty=0.3,
            reasoning=LlmReasoningOptions(mode=LlmReasoningMode.HIGH),
        ),
        return_thinking_content=False,
    )

    body = _build_responses_body(request, stream=True)

    assert body["store"] is False
    assert body["reasoning"] == {"effort": "high", "summary": "auto"}
    assert body["include"] == ["reasoning.encrypted_content"]
    assert "presence_penalty" not in body
    assert "frequency_penalty" not in body


def test_responses_body_uses_stable_conversation_model_cache_affinity():
    request = ChatCompletionRequest(
        provider_id="provider-a",
        model_id="gpt-test",
        session_id="session-1",
        messages=(ChatMessage(role=ChatMessageRole.USER, content="test"),),
    )

    original_key = _build_responses_body(request, stream=True)["prompt_cache_key"]
    repeated_key = _build_responses_body(request, stream=False)["prompt_cache_key"]
    other_provider_key = _build_responses_body(
        replace(request, provider_id="provider-b"),
        stream=True,
    )["prompt_cache_key"]
    switched_model_key = _build_responses_body(
        replace(request, model_id="gpt-other"),
        stream=True,
    )["prompt_cache_key"]
    inherited_branch_key = _build_responses_body(
        replace(
            request,
            session_id="session-branch",
            cache_affinity_id="session-1",
        ),
        stream=True,
    )["prompt_cache_key"]
    switched_back_key = _build_responses_body(request, stream=True)["prompt_cache_key"]

    assert repeated_key == original_key
    assert other_provider_key == original_key
    assert switched_model_key != original_key
    assert inherited_branch_key == original_key
    assert switched_back_key == original_key
    assert len(original_key) == 64


def test_responses_body_omits_cache_affinity_without_session():
    request = ChatCompletionRequest(
        provider_id="provider-a",
        model_id="gpt-test",
        messages=(ChatMessage(role=ChatMessageRole.USER, content="test"),),
    )

    body = _build_responses_body(request, stream=True)

    assert "prompt_cache_key" not in body


def test_responses_replays_reasoning_item_before_assistant_tool_call():
    reasoning_item = {
        "id": "rs_1",
        "type": "reasoning",
        "summary": [],
        "encrypted_content": "encrypted",
    }
    payload = _message_to_responses_payload(
        ChatMessage(
            role=ChatMessageRole.ASSISTANT,
            content="I will inspect the file.",
            tool_calls=(
                ChatToolCall(
                    call_id="call-1",
                    name="read_file",
                    arguments='{"path":"test.md"}',
                ),
            ),
            provider_output_items=(reasoning_item,),
        ),
        include_message_phase=True,
    )

    assert payload[0] == reasoning_item
    assert payload[1]["phase"] == "commentary"
    assert payload[2]["type"] == "function_call"


def test_responses_message_phase_is_only_added_when_profile_enables_it():
    message = ChatMessage(
        role=ChatMessageRole.ASSISTANT,
        content="Final answer.",
    )

    generic_payload = _message_to_responses_payload(message)
    openai_payload = _message_to_responses_payload(
        message,
        include_message_phase=True,
    )

    assert "phase" not in generic_payload[0]
    assert openai_payload[0]["phase"] == "final_answer"


def test_responses_adapter_applies_provider_phase_whitelist():
    request = ChatCompletionRequest(
        provider_id="provider-test",
        model_id="model-test",
        messages=(
            ChatMessage(role=ChatMessageRole.ASSISTANT, content="Earlier answer."),
            ChatMessage(role=ChatMessageRole.USER, content="Continue."),
        ),
    )

    async def capture_body(profile_id: str):
        captured: dict[str, object] = {}

        async def post_json(_url, _headers, body):
            captured.update(body)
            return {"status": "completed", "output": []}

        provider = _provider_entry(profile_id=profile_id)
        await OpenAIResponsesChatAdapter().complete(
            provider_template=provider,
            runtime_config=ProviderRuntimeConfig(
                provider_id=provider.provider_id,
                display_name=provider.display_name,
                api_base_url="https://example.test/v1",
            ),
            api_key="sk-test",
            request=request,
            post_json=post_json,
        )
        return captured

    openai_body = asyncio.run(capture_body("openai"))
    volcengine_body = asyncio.run(capture_body("volcengine"))

    assert openai_body["input"][0]["phase"] == "final_answer"
    assert "phase" not in volcengine_body["input"][0]


def test_responses_adapter_applies_volcengine_reasoning_parameters():
    async def capture_body(profile_id: str, mode: LlmReasoningMode):
        captured: dict[str, object] = {}

        async def post_json(_url, _headers, body):
            captured.update(body)
            return {"status": "completed", "output": []}

        provider = _provider_entry(profile_id=profile_id)
        await OpenAIResponsesChatAdapter().complete(
            provider_template=provider,
            runtime_config=ProviderRuntimeConfig(
                provider_id=provider.provider_id,
                display_name=provider.display_name,
                api_base_url="https://example.test/v1",
            ),
            api_key="sk-test",
            request=ChatCompletionRequest(
                provider_id="provider-test",
                model_id="model-test",
                messages=(ChatMessage(role=ChatMessageRole.USER, content="test"),),
                generation=LlmGenerationParams(
                    reasoning=LlmReasoningOptions(mode=mode),
                ),
                return_thinking_content=True,
            ),
            post_json=post_json,
        )
        return captured

    volcengine_off_body = asyncio.run(
        capture_body("volcengine", LlmReasoningMode.OFF)
    )
    volcengine_enabled_body = asyncio.run(
        capture_body("volcengine", LlmReasoningMode.ENABLED)
    )
    openai_off_body = asyncio.run(capture_body("openai", LlmReasoningMode.OFF))

    assert volcengine_off_body["thinking"] == {"type": "disabled"}
    assert "reasoning" not in volcengine_off_body
    assert "thinking" not in volcengine_enabled_body
    assert volcengine_enabled_body["reasoning"] == {
        "effort": "medium",
        "summary": "auto",
    }
    assert openai_off_body["reasoning"] == {"effort": "none"}
    assert "thinking" not in openai_off_body


def test_responses_stream_emits_reasoning_summary_and_internal_reasoning_item():
    reasoning_item = {
        "id": "rs_1",
        "type": "reasoning",
        "summary": [{"type": "summary_text", "text": "Inspecting"}],
        "encrypted_content": "encrypted",
    }
    request = _request_with_tool()
    payloads = [
        {
            "type": "response.reasoning_summary_text.delta",
            "delta": "Inspecting",
        },
        {
            "type": "response.output_item.done",
            "output_index": 0,
            "item": reasoning_item,
        },
        {"type": "response.completed", "response": {"status": "completed"}},
    ]

    events = asyncio.run(_collect_events(payloads, request=request))

    assert [event.kind for event in events] == [
        ChatStreamEventKind.THINKING_DELTA,
        ChatStreamEventKind.PROVIDER_OUTPUT_ITEM,
        ChatStreamEventKind.DONE,
    ]
    assert events[0].content == "Inspecting"
    assert events[1].provider_output_item == reasoning_item


def test_responses_stream_emits_reasoning_text_without_provider_special_case():
    payloads = [
        {
            "type": "response.reasoning_text.delta",
            "delta": "Checking the calculation.",
        },
        {
            "type": "response.completed",
            "response": {"status": "completed"},
        },
    ]

    events = asyncio.run(_collect_events(payloads))

    assert [event.kind for event in events] == [
        ChatStreamEventKind.THINKING_DELTA,
        ChatStreamEventKind.DONE,
    ]
    assert events[0].content == "Checking the calculation."


def test_responses_stream_does_not_mix_two_reasoning_delta_formats():
    payloads = [
        {
            "type": "response.reasoning_text.delta",
            "delta": "Full reasoning.",
        },
        {
            "type": "response.reasoning_summary_text.delta",
            "delta": "Summary duplicate.",
        },
        {
            "type": "response.completed",
            "response": {"status": "completed"},
        },
    ]

    events = asyncio.run(_collect_events(payloads))

    assert [event.kind for event in events] == [
        ChatStreamEventKind.THINKING_DELTA,
        ChatStreamEventKind.DONE,
    ]
    assert events[0].content == "Full reasoning."


def test_responses_stream_treats_incomplete_as_error_and_keeps_usage():
    payloads = [
        {
            "type": "response.incomplete",
            "response": {
                "status": "incomplete",
                "incomplete_details": {"reason": "max_output_tokens"},
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 20,
                    "total_tokens": 30,
                },
            },
        },
    ]

    events = asyncio.run(_collect_events(payloads))

    assert [event.kind for event in events] == [
        ChatStreamEventKind.USAGE,
        ChatStreamEventKind.ERROR,
    ]
    assert "最大输出 Token 上限" in events[1].error


def test_responses_stream_treats_missing_terminal_event_as_error():
    events = asyncio.run(
        _collect_events(
            [
                {
                    "type": "response.output_text.delta",
                    "delta": "partial answer",
                },
            ]
        )
    )

    assert [event.kind for event in events] == [
        ChatStreamEventKind.DELTA,
        ChatStreamEventKind.ERROR,
    ]
    assert "可能不完整" in events[1].error


def test_responses_stream_reads_nested_failure_message():
    events = asyncio.run(
        _collect_events(
            [
                {
                    "type": "response.failed",
                    "response": {
                        "status": "failed",
                        "error": {"message": "Model execution failed."},
                    },
                },
            ]
        )
    )

    assert [event.kind for event in events] == [ChatStreamEventKind.ERROR]
    assert events[0].error == "Model execution failed."


def test_responses_non_streaming_incomplete_raises_upstream_error():
    async def post_json(_url, _headers, _body):
        return {
            "status": "incomplete",
            "incomplete_details": {"reason": "content_filter"},
        }

    adapter = OpenAIResponsesChatAdapter()
    with pytest.raises(UpstreamProviderError) as caught:
        asyncio.run(
            adapter.complete(
                provider_template=_provider_entry(),
                runtime_config=ProviderRuntimeConfig(
                    provider_id="openai",
                    display_name="OpenAI",
                    api_base_url="https://example.test/v1",
                ),
                api_key="sk-test",
                request=_request(),
                post_json=post_json,
            )
        )

    assert caught.value.code == "upstream_response_incomplete"
    assert "内容过滤器" in caught.value.message


def test_responses_protocol_has_its_own_runtime_capabilities():
    capabilities = resolve_provider_profile(_provider_entry()).resolve_capabilities(
        _provider_entry(),
        "gpt-test",
    )

    assert capabilities.provider_profile_id == "openai_responses"
    assert capabilities.reasoning.modes == (
        LlmReasoningMode.LOW,
        LlmReasoningMode.MEDIUM,
        LlmReasoningMode.HIGH,
        LlmReasoningMode.MAX,
    )
    assert capabilities.sampling.parameters == ("temperature", "top_p")


def test_responses_completed_backfills_items_when_proxy_omits_item_done_events():
    reasoning_item = {
        "id": "rs_1",
        "type": "reasoning",
        "summary": [],
        "encrypted_content": "encrypted",
    }
    payloads = [
        {
            "type": "response.completed",
            "response": {
                "status": "completed",
                "output": [
                    reasoning_item,
                    {
                        "type": "function_call",
                        "call_id": "call-1",
                        "name": "read_file",
                        "arguments": '{"path":"test.md"}',
                    },
                ],
            },
        },
    ]

    events = asyncio.run(_collect_events(payloads, request=_request_with_tool()))

    assert [event.kind for event in events] == [
        ChatStreamEventKind.PROVIDER_OUTPUT_ITEM,
        ChatStreamEventKind.TOOL_CALL,
        ChatStreamEventKind.DONE,
    ]
    assert events[0].provider_output_item == reasoning_item
    assert events[1].tool_call.name == "read_file"


def test_responses_completed_backfills_text_and_reasoning_when_proxy_omits_deltas():
    payloads = [
        {
            "type": "response.completed",
            "response": {
                "status": "completed",
                "output": [
                    {
                        "id": "rs_1",
                        "type": "reasoning",
                        "summary": [
                            {"type": "summary_text", "text": "Checked the inputs."},
                        ],
                    },
                    {
                        "type": "message",
                        "content": [
                            {"type": "output_text", "text": "Final answer."},
                        ],
                    },
                ],
            },
        },
    ]

    events = asyncio.run(_collect_events(payloads))

    assert [event.kind for event in events] == [
        ChatStreamEventKind.DELTA,
        ChatStreamEventKind.THINKING_DELTA,
        ChatStreamEventKind.DONE,
    ]
    assert events[0].content == "Final answer."
    assert events[1].content == "Checked the inputs."


def test_responses_completed_prefers_reasoning_text_over_summary():
    payloads = [
        {
            "type": "response.completed",
            "response": {
                "status": "completed",
                "output": [
                    {
                        "id": "rs_1",
                        "type": "reasoning",
                        "content": [
                            {"type": "reasoning_text", "text": "Full reasoning."},
                        ],
                        "summary": [
                            {"type": "summary_text", "text": "Summary duplicate."},
                        ],
                    },
                ],
            },
        },
    ]

    events = asyncio.run(_collect_events(payloads))

    assert [event.kind for event in events] == [
        ChatStreamEventKind.THINKING_DELTA,
        ChatStreamEventKind.DONE,
    ]
    assert events[0].content == "Full reasoning."


def test_responses_stream_does_not_duplicate_completed_text_after_deltas():
    payloads = [
        {"type": "response.output_text.delta", "delta": "Final "},
        {"type": "response.output_text.delta", "delta": "answer."},
        {
            "type": "response.completed",
            "response": {
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {"type": "output_text", "text": "Final answer."},
                        ],
                    },
                ],
            },
        },
    ]

    events = asyncio.run(_collect_events(payloads))

    assert [event.kind for event in events] == [
        ChatStreamEventKind.DELTA,
        ChatStreamEventKind.DELTA,
        ChatStreamEventKind.DONE,
    ]
    assert "".join(event.content or "" for event in events) == "Final answer."


async def _collect_events(
    payloads: list[dict[str, object]],
    *,
    request: ChatCompletionRequest | None = None,
):
    async def stream_body(_url, _headers, _body):
        for payload in payloads:
            yield f"data: {json.dumps(payload)}\n\n".encode()

    adapter = OpenAIResponsesChatAdapter()
    return [
        event
        async for event in adapter.stream(
            provider_template=_provider_entry(),
            runtime_config=ProviderRuntimeConfig(
                provider_id="openai",
                display_name="OpenAI",
                api_base_url="https://example.test/v1",
            ),
            api_key="sk-test",
            request=request or _request(),
            stream_body=stream_body,
        )
    ]


def _request() -> ChatCompletionRequest:
    return ChatCompletionRequest(
        provider_id="openai",
        model_id="gpt-test",
        messages=(ChatMessage(role=ChatMessageRole.USER, content="test"),),
    )


def _request_with_tool() -> ChatCompletionRequest:
    return ChatCompletionRequest(
        provider_id="openai",
        model_id="gpt-test",
        messages=(ChatMessage(role=ChatMessageRole.USER, content="test"),),
        tools=(
            ChatToolDefinition(
                name="read_file",
                description="Read a file",
                parameters={"type": "object"},
            ),
        ),
    )


def _provider_entry(*, profile_id: str = "generic") -> ProviderCatalogEntry:
    return ProviderCatalogEntry(
        provider_id="openai",
        display_name="OpenAI",
        profile_id=profile_id,
        protocol_family=ProviderProtocolFamily.OPENAI_RESPONSES,
        generation_auth_schemes={
            ProviderProtocolFamily.OPENAI_RESPONSES: AuthScheme.BEARER_TOKEN
        },
        model_discovery_strategy=default_model_discovery_strategy(
            ProviderProtocolFamily.OPENAI_RESPONSES
        ),
        model_discovery_auth_scheme=AuthScheme.BEARER_TOKEN,
        endpoints=ProviderEndpointTemplate(
            api_base_url="https://example.test",
            text_generation_url_template="responses",
            model_discovery_url=None,
        ),
    )


def _tool_added(output_index: int, call_id: str, name: str) -> dict[str, object]:
    return {
        "type": "response.output_item.added",
        "output_index": output_index,
        "item": {
            "type": "function_call",
            "call_id": call_id,
            "name": name,
            "arguments": "",
        },
    }


def _tool_delta(output_index: int, delta: str) -> dict[str, object]:
    return {
        "type": "response.function_call_arguments.delta",
        "output_index": output_index,
        "delta": delta,
    }


def _tool_done(
    output_index: int,
    call_id: str,
    name: str,
    arguments: str,
) -> dict[str, object]:
    return {
        "type": "response.output_item.done",
        "output_index": output_index,
        "item": {
            "type": "function_call",
            "call_id": call_id,
            "name": name,
            "arguments": arguments,
        },
    }
