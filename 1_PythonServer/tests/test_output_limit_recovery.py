import asyncio
from dataclasses import replace

import pytest

from app.domain.llm.chat import (
    ChatCompletionResult, ChatMessage, ChatMessageRole, ChatStreamEvent,
    ChatStreamEventKind as Kind, ChatToolCall, ChatToolDefinition, ChatUsage,
)
from app.domain.llm.generation_params import LlmGenerationParams
from app.domain.llm.output_limit import OUTPUT_LIMIT_MESSAGE_PREFIX
from app.domain.llm.output_limit_error import OutputLimitError
from app.domain.project.project_conversation import ProjectConversationSessionSettings
from app.repositories.llm.usage_repository import LlmUsageRepository
from app.services.project.conversation_stream import ProjectConversationStreamService
from app.services.llm.provider import config_runtime
from tests.test_chat_usage_recording import (
    _build_service, _SequencedRemoteClient, _FakeUsageService, _FakeExchangeRecorder,
)
from tests.test_chat_stream_cancellation import (
    _StatefulFakeConversationService, _FakeNamingService, _FakeMemoryService,
    _FakeProjectService, _FakeToolExecutionService, _request_with_client_message_id,
)


@pytest.fixture(autouse=True)
def decrypt_key(monkeypatch):
    monkeypatch.setattr(config_runtime, "resolve_api_key_secret", lambda _key: "sk-test")


def truncated(*, text="partial", thought="thinking", reason="length", tokens=100, tool=False):
    events = [ChatStreamEvent(kind=Kind.THINKING_DELTA, content=thought),
              ChatStreamEvent(kind=Kind.DELTA, content=text)]
    if tool:
        events.extend([
            ChatStreamEvent(kind=Kind.TOOL_CALL_DELTA, tool_call=ChatToolCall("broken", "write_text_file", '{"path":')),
            ChatStreamEvent(kind=Kind.TOOL_CALL, tool_call=ChatToolCall("broken", "write_text_file", '{"path":')),
        ])
    return (*events, ChatStreamEvent(kind=Kind.USAGE, usage=ChatUsage(prompt_tokens=10, completion_tokens=tokens, total_tokens=10+tokens)),
            ChatStreamEvent(kind=Kind.ERROR, error="cut off", error_code="upstream_stream_incomplete", finish_reason=reason))


def completed(text="final", tokens=2):
    return (ChatStreamEvent(kind=Kind.DELTA, content=text),
            ChatStreamEvent(kind=Kind.USAGE, usage=ChatUsage(prompt_tokens=10, completion_tokens=tokens, total_tokens=10+tokens)),
            ChatStreamEvent(kind=Kind.DONE, finish_reason="stop"))


def setup_run(attempts, *, action="retry", save=False, maximum=1, tools=False):
    remote = _SequencedRemoteClient(stream_attempts=attempts)
    usage = _FakeUsageService()
    recorder = _FakeExchangeRecorder()
    chat = _build_service(remote_client=remote, usage_service=usage, http_exchange_recorder=recorder)
    conversations = _StatefulFakeConversationService()
    conversations.session = replace(conversations.session, settings=ProjectConversationSessionSettings(
        output_limit_action=action, output_limit_save_partial=save,
        output_limit_message="请继续原任务", output_limit_max_recoveries=maximum,
        max_output_tokens=100,
    ))
    class RejectExecution(_FakeToolExecutionService):
        def __init__(self):
            self.calls = []
        def execute(self, tool_call, *, context):
            self.calls.append(tool_call)
            return super().execute(tool_call, context=context)
    executor = RejectExecution() if tools else None
    stream = ProjectConversationStreamService(chat, conversations, usage, _FakeNamingService(), _FakeMemoryService(),
        tool_execution_service=executor, project_service=_FakeProjectService())
    request = replace(_request_with_client_message_id("root-user"), generation=LlmGenerationParams(max_output_tokens=100))
    if tools:
        request = replace(request, tools=(ChatToolDefinition(name="write_text_file", description="write", parameters={"type": "object"}),))
    return stream, request, conversations, remote, usage, recorder, executor


async def collect(stream, request):
    return [event async for event in stream.stream_payloads(request, await_background_tasks=True)]


@pytest.mark.parametrize("save", [False, True])
def test_retry_replays_exact_request_counts_usage_and_excludes_saved_fragment(save):
    stream, request, store, remote, usage, recorder, _ = setup_run([truncated(), completed()], save=save)
    events = asyncio.run(collect(stream, request))
    assert remote.requests[0].messages == remote.requests[1].messages
    assert [m.role for m in store.persisted_messages].count("user") == 1
    partials = [m for m in store.persisted_messages if m.finish_reason == "output_limit"]
    assert len(partials) == int(save)
    if save:
        assert partials[0].thinking_content == "thinking"
        assert partials[0].include_in_context is False
    assert events[-1]["kind"] == "done"
    assert sum(record["usage"].completion_tokens for record in usage.records) == 102
    assert len({record["request_id"] for record in usage.records}) == 2
    assert [a["status"] for a in recorder.attempts] == ["failed", "completed"]


@pytest.mark.parametrize("save", [False, True])
def test_send_message_uses_visible_user_turn_and_replays_final_chain(save):
    stream, request, store, remote, usage, _, _ = setup_run([truncated(), completed()], action="send_message", save=save)
    events = asyncio.run(collect(stream, request))
    users = [m for m in store.persisted_messages if m.role == "user"]
    assert len(users) == 2
    assert users[1].message_source == "output_limit"
    assert users[1].continuation_of == "root-user"
    assert users[1].content == OUTPUT_LIMIT_MESSAGE_PREFIX + "请继续原任务"
    second = remote.requests[1].messages
    assert second[-1].role == ChatMessageRole.USER and second[-1].content == users[1].content
    assert any(m.content == "partial" for m in second) == save
    if save:
        partial = next(m for m in store.persisted_messages if m.finish_reason == "output_limit")
        assert partial.content == "partial"
        assert partial.thinking_content == "thinking"
        assert partial.include_in_context is True
    assert events[-2]["user_message_id"] == users[1].message_id
    assert events[-2]["status"] == "done"
    assert len(usage.records) == 2
    assert "error" not in [status for _, _, status in store.runtime_statuses]
    # An idempotent submit after a reconnect replays the final continuation, without calling the provider.
    replay = asyncio.run(collect(stream, request))
    assert len(remote.requests) == 2
    assert replay[-2]["status"] == "done" and replay[-2]["user_message_id"] == users[1].message_id


@pytest.mark.parametrize("save", [False, True])
def test_stop_preserves_thinking_only_if_requested_and_does_not_execute_half_tool(save):
    stream, request, store, remote, usage, _, executor = setup_run(
        [truncated(text="", tool=True)], action="stop", save=save, tools=True)
    events = asyncio.run(collect(stream, request))
    assert len(remote.requests) == 1
    assert not executor.calls
    assistants = [m for m in store.persisted_messages if m.role == "assistant"]
    assert len(assistants) == int(save)
    if save:
        assert assistants[0].content == "" and assistants[0].thinking_content == "thinking"
        assert not assistants[0].tool_calls
        assert assistants[0].include_in_context is False
    assert len(usage.records) == 1
    assert events[-1]["error_code"] == "upstream_output_limit"


def test_recovery_budget_is_shared_across_automatic_user_turns():
    stream, request, store, remote, _, _, _ = setup_run(
        [truncated(), truncated(), truncated()], action="send_message", save=True, maximum=2)
    events = asyncio.run(collect(stream, request))
    assert len(remote.requests) == 3
    assert len([m for m in store.persisted_messages if m.role == "user"]) == 3
    assert [e["will_recover"] for e in events if e["kind"] == "output_limit"] == [True, True, False]
    assert events[-1]["kind"] == "error"


@pytest.mark.parametrize("tokens,reason,expected", [(95,None,True), (94,None,False), (100,"content_filter",False)])
def test_numeric_fallback_requires_abnormal_end_and_real_usage(tokens, reason, expected):
    stream, request, _, remote, _, _, _ = setup_run(
        [truncated(reason=reason, tokens=tokens), completed()], action="stop")
    events = asyncio.run(collect(stream, request))
    assert any(e["kind"] == "output_limit" for e in events) == expected
    assert len(remote.requests) == (1 if expected else 2)


def test_normal_completion_near_cap_is_not_recovered():
    stream, request, _, remote, _, _, _ = setup_run([completed(tokens=100)], action="send_message")
    events = asyncio.run(collect(stream, request))
    assert not any(e["kind"] == "output_limit" for e in events)
    assert len(remote.requests) == 1


def test_thinking_only_recovery_saves_thought_without_sending_empty_assistant():
    stream, request, store, remote, _, _, _ = setup_run(
        [truncated(text=""), completed()], action="send_message", save=True)
    asyncio.run(collect(stream, request))
    partial = next(m for m in store.persisted_messages if m.finish_reason == "output_limit")
    assert partial.thinking_content == "thinking" and partial.include_in_context is False
    assert all(m.role != ChatMessageRole.ASSISTANT for m in remote.requests[1].messages)


def test_automatic_user_publishes_durable_resume_checkpoint():
    stream, request, _, _, _, _, _ = setup_run([truncated(), completed()], action="send_message", save=True)
    async def collect_with_checkpoints():
        return [event async for event in stream.stream_payloads(request, include_persistence_checkpoints=True)]
    events = asyncio.run(collect_with_checkpoints())
    index = next(i for i, event in enumerate(events) if event["kind"] == "output_limit")
    assert events[index+1]["kind"] == "_conversation_persistence_checkpoint"
    assert events[index+1]["checkpoint_message_id"] == events[index]["next_user_message"]["message_id"]


def test_estimated_tokens_do_not_trigger_numeric_fallback():
    from app.services.llm.chat.output_limit import is_output_limit
    request = replace(_request_with_client_message_id("root"), generation=LlmGenerationParams(max_output_tokens=100))
    error = ChatStreamEvent(kind=Kind.ERROR, error_code="upstream_stream_incomplete")
    assert not is_output_limit(request, error, ChatUsage(completion_tokens=100, estimated_fields=("completion_tokens",)))
    assert not is_output_limit(request, replace(error, error_code="upstream_connection_error"), ChatUsage(completion_tokens=100))


def test_anthropic_truncated_tool_json_waits_for_max_tokens_reason():
    from tests.test_llm_protocol_continuation import _collect_anthropic, _request
    events = asyncio.run(_collect_anthropic([
        {"type":"content_block_start","index":0,"content_block":{"type":"tool_use","id":"call","name":"write_file","input":{}}},
        {"type":"content_block_delta","index":0,"delta":{"type":"input_json_delta","partial_json":'{"path":'}},
        {"type":"content_block_stop","index":0},
        {"type":"message_delta","delta":{"stop_reason":"max_tokens"},"usage":{"output_tokens":100}},
        {"type":"message_stop"},
    ], _request("anthropic", "claude-test")))
    assert events[-1].finish_reason == "max_tokens" and events[-1].kind == Kind.ERROR
    assert not any(e.kind == Kind.TOOL_CALL for e in events)


def test_responses_incomplete_preserves_output_limit_reason():
    from tests.test_openai_responses_adapter import _collect_events
    events = asyncio.run(_collect_events([{
        "type":"response.incomplete", "response":{"status":"incomplete", "incomplete_details":{"reason":"max_output_tokens"},
        "usage":{"input_tokens":10,"output_tokens":100}, "output":[]},
    }]))
    assert events[-1].kind == Kind.ERROR and events[-1].finish_reason == "max_output_tokens"


def test_legacy_role_hash_survives_new_default_policy_fields(tmp_path):
    from hashlib import sha256
    from json import dumps
    from tests.test_role_configuration_application import _build_services
    from app.repositories.project.conversation_serialization import _session_from_payload, _session_to_payload
    projects, conversations, roles, _ = _build_services(tmp_path)
    role = roles.ensure_default_role()
    project = projects.create_project(name="旧角色")
    session = conversations.create_session(project.project_id, role_project_id=role.project_id)
    payload = _session_to_payload(session)
    for key in list(payload["settings"]):
        if key.startswith("output_limit_"):
            del payload["settings"][key]
    payload["role_configuration_hash"] = sha256(dumps({
        "provider_id":session.provider_id,"model_id":session.model_id,"reasoning_mode":session.reasoning_mode,
        "settings":payload["settings"],
    }, ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    restored = _session_from_payload(payload)
    assert restored.role_configuration_hash == session.role_configuration_hash


def test_closing_stream_between_turns_cancels_durable_automatic_user():
    stream, request, store, remote, _, _, _ = setup_run([truncated()], action="send_message")
    async def close_after_notice():
        generator = stream.stream_payloads(request)
        async for event in generator:
            if event["kind"] == "output_limit":
                await generator.aclose()
                break
    asyncio.run(close_after_notice())
    automatic = store.persisted_messages[-1]
    assert automatic.message_source == "output_limit"
    assert store.runs[f"run_{automatic.message_id}"].status == "cancelled"
    assert len(remote.requests) == 1


def test_stop_during_automatic_message_write_does_not_leave_unstarted_turn_running():
    import threading
    stream, request, store, remote, _, _, _ = setup_run([truncated()], action="send_message")
    write_started, release_write = threading.Event(), threading.Event()
    original_append = store.append_message
    def blocking_append(*args, **kwargs):
        if kwargs.get("message_source") == "output_limit":
            write_started.set()
            assert release_write.wait(2)
        return original_append(*args, **kwargs)
    store.append_message = blocking_append
    async def stop_while_writing():
        task = asyncio.create_task(collect(stream, request))
        while not write_started.is_set():
            await asyncio.sleep(0.001)
        task.cancel()
        release_write.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(stop_while_writing())
    automatic = next(m for m in store.persisted_messages if m.message_source == "output_limit")
    assert store.runs[f"run_{automatic.message_id}"].status == "cancelled"
    assert len(remote.requests) == 1


def test_request_usage_identity_counts_attempts_and_deduplicates_repeated_write(tmp_path):
    repository = LlmUsageRepository(tmp_path / "usage")
    kwargs = dict(project_id="p", session_id="s", message_id="same-message", provider_id="deepseek", model_id="v4",
        usage=ChatUsage(prompt_tokens=1,completion_tokens=100,total_tokens=101), usage_feature_key="main_chat", is_estimated=False)
    repository.record_usage(**kwargs, request_id="attempt-1")
    repository.record_usage(**kwargs, request_id="attempt-2")
    repository.record_usage(**kwargs, request_id="attempt-1")
    summary = repository.get_session_summary(project_id="p", session_id="s").total
    assert summary.record_count == 2 and summary.completion_tokens == 200


def test_non_streaming_truncation_uses_same_policy_and_records_all_attempts():
    partial = ChatCompletionResult(provider_id="deepseek", model_id="deepseek-v4",
        message=ChatMessage(role=ChatMessageRole.ASSISTANT, content="half"), finish_reason="length",
        usage=ChatUsage(prompt_tokens=10,completion_tokens=100,total_tokens=110))
    final = replace(partial, message=replace(partial.message, content="final"), finish_reason="stop",
        usage=ChatUsage(prompt_tokens=10,completion_tokens=2,total_tokens=12))
    remote = _SequencedRemoteClient(complete_attempts=[OutputLimitError(partial), final])
    usage = _FakeUsageService()
    chat = _build_service(remote_client=remote,usage_service=usage)
    request = replace(_request_with_client_message_id("root"), output_limit_action="send_message", output_limit_save_partial=True)
    result = asyncio.run(chat.complete(request))
    assert result.message.content == "final"
    assert remote.requests[1].messages[-2].content == "half"
    assert remote.requests[1].messages[-1].content.startswith(OUTPUT_LIMIT_MESSAGE_PREFIX)
    assert sum(r["usage"].completion_tokens for r in usage.records) == 102


def test_retry_after_completed_tool_round_uses_tool_result_without_inventing_user():
    tool_round = (
        ChatStreamEvent(kind=Kind.TOOL_CALL, tool_call=ChatToolCall("complete", "write_text_file", '{}')),
        ChatStreamEvent(kind=Kind.USAGE, usage=ChatUsage(prompt_tokens=10, completion_tokens=3, total_tokens=13)),
        ChatStreamEvent(kind=Kind.DONE, finish_reason="tool_calls"),
    )
    stream, request, store, remote, usage, _, executor = setup_run([tool_round, truncated(), completed()], tools=True)
    events = asyncio.run(collect(stream, request))
    assert len(executor.calls) == 1
    assert remote.requests[1].messages[-1].role == ChatMessageRole.TOOL
    assert remote.requests[2].messages == remote.requests[1].messages
    assert sum(m.role == "user" for m in store.persisted_messages) == 1
    assert sum(r["usage"].completion_tokens for r in usage.records) == 105
    assert events[-1]["kind"] == "done"


def test_role_policy_roundtrip_and_context_filtering(tmp_path):
    from tests.test_role_configuration_application import _build_services
    from app.repositories.project.conversation_serialization import _message_from_payload, _message_to_payload
    from app.services.project.conversation_request_messages import build_conversation_request_messages
    projects, conversations, roles, _ = _build_services(tmp_path)
    project = projects.create_project(name="输出策略")
    policy = dict(output_limit_action="send_message", output_limit_save_partial=True,
                  output_limit_message="自定义续接", output_limit_max_recoveries=3)
    source = conversations.create_session(project.project_id, settings=policy)
    role, _ = roles.save_session_as_role(project.project_id, source.session_id, name="续接角色", category_id=None)
    target = conversations.create_session(project.project_id)
    applied = roles.apply_role(project.project_id, target.session_id, role.project_id)
    for key, value in policy.items():
        assert getattr(applied.settings, key) == value
    partial = conversations.append_message(project.project_id, target.session_id, role="assistant",
        content="不进入上下文的片段", thinking_content="思考", finish_reason="output_limit", include_in_context=False)
    restored = _message_from_payload(_message_to_payload(partial))
    assert restored.finish_reason == "output_limit" and restored.include_in_context is False
    assembled = build_conversation_request_messages((restored,), "新消息", applied.settings)
    assert all(m.content != restored.content for m in assembled)
