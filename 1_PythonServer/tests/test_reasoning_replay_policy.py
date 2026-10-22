import asyncio
import json
from copy import deepcopy
from dataclasses import replace

import pytest

from app.domain.llm.chat import (
    ChatCompletionRequest, ChatMessage, ChatMessageRole, ChatProtocolContinuation,
    ChatProtocolContinuationKind, ChatStreamEventKind, ChatToolCall, ChatToolDefinition,
)
from app.domain.llm.generation_params import LlmGenerationParams, LlmReasoningMode, LlmReasoningOptions
from app.domain.llm.provider_catalog import ProviderProtocolFamily
from app.domain.llm.reasoning_replay import ReasoningReplayMode
from app.infra.llm.chat_adapters.anthropic import _build_anthropic_body
from app.infra.llm.chat_adapters.gemini import _build_gemini_body
from app.infra.llm.chat_adapters.openai_compatible import _build_request_body
from app.infra.llm.chat_adapters.openai_responses import OpenAIResponsesChatAdapter
from app.infra.llm.chat_adapters.openai_responses_payloads import _build_responses_body
from app.infra.llm.provider_profiles.base import GenericOpenAICompatibleProfile
from tests.test_llm_protocol_continuation import _provider, _runtime
from tests.test_openai_responses_adapter import _collect_events


PROTOCOLS = tuple(ProviderProtocolFamily)
CALL = ChatToolCall(call_id="call-1", name="read_file", arguments='{"path":"a.txt"}')
TOOL = ChatToolDefinition(name="read_file", description="Read file", parameters={"type": "object"})
REASONING = {
    "id": "rs-1", "type": "reasoning",
    "summary": [{"type": "summary_text", "text": "private plan"}],
    "encrypted_content": "private encrypted state",
}


def _assistant(protocol, has_tool_call):
    kinds_and_items = {
        ProviderProtocolFamily.OPENAI_RESPONSES: (
            ChatProtocolContinuationKind.OPENAI_RESPONSES_OUTPUT, (REASONING,),
        ),
        ProviderProtocolFamily.ANTHROPIC_MESSAGES: (
            ChatProtocolContinuationKind.ANTHROPIC_CONTENT,
            (
                {"type": "thinking", "thinking": "private plan", "signature": "private signature"},
                {"type": "redacted_thinking", "data": "private encrypted state"},
                {"type": "text", "text": "visible answer"},
                *(({"type": "tool_use", "id": CALL.call_id, "name": CALL.name, "input": {"path": "a.txt"}},) if has_tool_call else ()),
            ),
        ),
        ProviderProtocolFamily.GEMINI_GENERATE_CONTENT: (
            ChatProtocolContinuationKind.GEMINI_PARTS,
            (
                {"thought": True, "text": "private plan", "thoughtSignature": "private signature"},
                {"text": "visible answer", "thoughtSignature": "private text signature"},
                *(({"functionCall": {"id": CALL.call_id, "name": CALL.name, "args": {"path": "a.txt"}}, "thoughtSignature": "private tool signature"},) if has_tool_call else ()),
            ),
        ),
    }
    native = kinds_and_items.get(protocol)
    return ChatMessage(
        role=ChatMessageRole.ASSISTANT, content="visible answer", thinking_content="private plan",
        tool_calls=(CALL,) if has_tool_call else (),
        protocol_continuation=None if native is None else ChatProtocolContinuation(
            schema_version=1, protocol_family=protocol.value, provider_id="test", model_id="model",
            kind=native[0], items=deepcopy(native[1]),
        ),
    )


def _body(protocol, request, stream=False):
    if protocol == ProviderProtocolFamily.OPENAI_COMPATIBLE:
        return _build_request_body(request, stream=stream, provider_profile=GenericOpenAICompatibleProfile())
    if protocol == ProviderProtocolFamily.OPENAI_RESPONSES:
        return _build_responses_body(request, stream=stream)
    if protocol == ProviderProtocolFamily.ANTHROPIC_MESSAGES:
        return _build_anthropic_body(request, stream=stream)
    return _build_gemini_body(request)


@pytest.mark.parametrize("protocol", PROTOCOLS)
@pytest.mark.parametrize("mode", tuple(ReasoningReplayMode))
@pytest.mark.parametrize("has_tool_call", [False, True])
@pytest.mark.parametrize("tools_enabled", [False, True])
@pytest.mark.parametrize("stream", [False, True])
def test_all_protocols_apply_replay_choice_to_history_not_available_tools(protocol, mode, has_tool_call, tools_enabled, stream):
    assistant = _assistant(protocol, has_tool_call)
    saved = deepcopy(assistant)
    messages = [ChatMessage(role=ChatMessageRole.USER, content="question"), assistant]
    if has_tool_call:
        messages.append(ChatMessage(role=ChatMessageRole.TOOL, name=CALL.name, tool_call_id=CALL.call_id, content="file result"))
    messages.append(ChatMessage(role=ChatMessageRole.USER, content="continue"))
    request = ChatCompletionRequest(
        provider_id="test", model_id="model", messages=tuple(messages),
        reasoning_replay_mode=mode, tools=(TOOL,) if tools_enabled else (),
        generation=LlmGenerationParams(reasoning=LlmReasoningOptions(mode=LlmReasoningMode.OFF)),
    )
    body = _body(protocol, request, stream)
    wire = json.dumps(body)
    should_replay = mode == ReasoningReplayMode.ALWAYS or (mode == ReasoningReplayMode.TOOL_CALL_ROUNDS and has_tool_call)
    assert ("private plan" in wire) == should_replay
    assert ("private" in wire) == should_replay
    assert "visible answer" in wire and "continue" in wire
    if has_tool_call:
        assert "file result" in wire and "a.txt" in wire and CALL.name in wire
        assert wire.count(CALL.call_id) == 2
    assert assistant == saved  # Changing replay settings must not erase the saved response.
    all_body = json.dumps(_body(protocol, replace(request, reasoning_replay_mode=ReasoningReplayMode.ALWAYS), stream))
    assert "private plan" in all_body


@pytest.mark.parametrize("protocol", PROTOCOLS)
def test_tool_round_mode_only_replays_reasoning_for_the_message_with_calls(protocol):
    tool_message = _assistant(protocol, True)
    final_message = _assistant(protocol, False)
    request = ChatCompletionRequest(
        provider_id="test", model_id="model", reasoning_replay_mode=ReasoningReplayMode.TOOL_CALL_ROUNDS,
        messages=(tool_message, ChatMessage(role=ChatMessageRole.TOOL, name=CALL.name, tool_call_id=CALL.call_id, content="file result"), final_message),
    )
    assert json.dumps(_body(protocol, request)).count("private plan") == 1


@pytest.mark.parametrize("protocol", [p for p in PROTOCOLS if p != ProviderProtocolFamily.OPENAI_COMPATIBLE])
@pytest.mark.parametrize("mismatch", ["provider", "model", "protocol"])
def test_always_does_not_replay_native_thought_state_from_another_route(protocol, mismatch):
    assistant = _assistant(protocol, True)
    if mismatch == "protocol":
        assistant = replace(assistant, protocol_continuation=replace(
            assistant.protocol_continuation, protocol_family=ProviderProtocolFamily.OPENAI_COMPATIBLE.value,
        ))
    request = ChatCompletionRequest(
        provider_id="other" if mismatch == "provider" else "test",
        model_id="other" if mismatch == "model" else "model",
        messages=(assistant,), reasoning_replay_mode=ReasoningReplayMode.ALWAYS,
    )
    wire = json.dumps(_body(protocol, request))
    assert "private" not in wire
    assert "visible answer" in wire and CALL.name in wire and "a.txt" in wire


@pytest.mark.parametrize("protocol", [p for p in PROTOCOLS if p != ProviderProtocolFamily.OPENAI_COMPATIBLE])
def test_filtering_reasoning_only_reply_does_not_send_an_empty_native_turn(protocol):
    assistant = _assistant(protocol, False)
    continuation = assistant.protocol_continuation
    if protocol == ProviderProtocolFamily.GEMINI_GENERATE_CONTENT:
        items = (continuation.items[0], {"thoughtSignature": "private signature"})
    elif protocol == ProviderProtocolFamily.ANTHROPIC_MESSAGES:
        items = continuation.items[:2]
    else:
        items = continuation.items
    assistant = replace(assistant, content="", protocol_continuation=replace(continuation, items=items))
    request = ChatCompletionRequest(
        provider_id="test", model_id="model", messages=(assistant, ChatMessage(role=ChatMessageRole.USER, content="continue")),
        reasoning_replay_mode=ReasoningReplayMode.NEVER,
    )
    body = _body(protocol, request)
    history = body.get("messages", body.get("contents", body.get("input")))
    assert len(history) == 1
    assert history[0]["role"] == "user"


@pytest.mark.parametrize("mode", tuple(ReasoningReplayMode))
@pytest.mark.parametrize("event_source", ["item", "completed", "both"])
def test_responses_stream_keeps_native_reasoning_without_tools_for_later_replay(mode, event_source):
    request = ChatCompletionRequest(
        provider_id="openai", model_id="gpt-test", messages=(ChatMessage(role=ChatMessageRole.USER, content="question"),),
        reasoning_replay_mode=mode,
    )
    payloads = []
    if event_source in {"item", "both"}:
        payloads.append({"type": "response.output_item.done", "output_index": 0, "item": REASONING})
    output = [REASONING] if event_source in {"completed", "both"} else []
    payloads.append({"type": "response.completed", "response": {"status": "completed", "output": output}})
    events = asyncio.run(_collect_events(payloads, request=request))
    continuations = [event.protocol_continuation for event in events if event.kind == ChatStreamEventKind.PROTOCOL_CONTINUATION]
    assert len(continuations) == 1 and continuations[0].items == (REASONING,)
    assistant = ChatMessage(role=ChatMessageRole.ASSISTANT, content="visible answer", protocol_continuation=continuations[0])
    replay = replace(request, messages=(assistant,), reasoning_replay_mode=ReasoningReplayMode.ALWAYS)
    assert _build_responses_body(replay, stream=True)["input"][0] == REASONING
    assert _build_responses_body(replay, stream=True)["include"] == ["reasoning.encrypted_content"]


def test_responses_non_streaming_capture_obeys_policy_only_on_next_request():
    request = ChatCompletionRequest(provider_id="test", model_id="model", messages=(), reasoning_replay_mode=ReasoningReplayMode.NEVER)

    async def complete():
        async def post_json(_url, _headers, _body):
            return {"status": "completed", "output": [REASONING, {"type": "message", "content": [{"type": "output_text", "text": "answer"}]}]}
        return await OpenAIResponsesChatAdapter().complete(
            provider_template=_provider(ProviderProtocolFamily.OPENAI_RESPONSES, "test"),
            runtime_config=_runtime("test"), api_key="test", request=request, post_json=post_json,
        )

    result = asyncio.run(complete())
    assert result.message.thinking_content == "private plan"
    assert result.message.protocol_continuation.items == (REASONING,)
    replay = replace(request, messages=(result.message,))
    assert "private" not in json.dumps(_build_responses_body(replay, stream=False))
    assert _build_responses_body(replace(replay, reasoning_replay_mode=ReasoningReplayMode.ALWAYS), stream=False)["input"][0] == REASONING
