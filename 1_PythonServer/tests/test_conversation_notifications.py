import asyncio
import threading
import pytest

from app.services.llm.provider import config_runtime

from app.domain.llm.chat import ChatStreamEvent, ChatStreamEventKind as Kind, ChatToolCall
from app.services.project.conversation_notifications import (
    ConversationNotificationBuffer, conversation_notifications,
)
from tests.test_output_limit_recovery import setup_run, collect, completed, truncated


@pytest.fixture(autouse=True)
def isolated_notice_buffer(monkeypatch):
    monkeypatch.setattr(config_runtime, "resolve_api_key_secret", lambda _key: "sk-test")
    conversation_notifications._sessions.clear()
    yield
    conversation_notifications._sessions.clear()


def test_notices_wait_for_one_response_and_are_immediate_during_tools():
    async def run():
        buffer = ConversationNotificationBuffer()
        writes = []

        def writer(value):
            async def persist():
                writes.append(value)
                return value
            return persist

        buffer.open("p", "s")
        await buffer.start_response("p", "s")
        await buffer.submit("p", "s", writer("start"))
        await buffer.submit("p", "s", writer("done"))
        assert writes == []
        assert await buffer.finish_response("p", "s") == ["start", "done"]
        assert writes == ["start", "done"]
        await buffer.submit("p", "s", writer("while_tool_waits"))
        assert writes[-1] == "while_tool_waits"
        await buffer.start_response("p", "s")
        await buffer.submit("p", "s", writer("next_response"))
        assert writes[-1] == "while_tool_waits"
        await buffer.close("p", "s")
        assert writes[-1] == "next_response"
        assert not buffer._sessions
    asyncio.run(run())


def test_notice_writers_are_serialized_before_next_response_and_failures_are_isolated():
    async def run():
        buffer = ConversationNotificationBuffer()
        writes = []
        entered, release = asyncio.Event(), asyncio.Event()

        async def slow():
            entered.set()
            await release.wait()
            writes.append("persisted")
            return "persisted"

        async def broken():
            raise ValueError("notice storage failed")

        await buffer.start_response("p", "s")
        await buffer.submit("p", "s", broken)
        await buffer.submit("p", "s", slow)
        finishing = asyncio.create_task(buffer.finish_response("p", "s"))
        await entered.wait()
        starting = asyncio.create_task(buffer.start_response("p", "s"))
        await asyncio.sleep(0)
        assert not starting.done()
        release.set()
        assert await finishing == ["persisted"]
        await starting
        assert buffer._sessions[("p", "s")].streaming
        await buffer.close("p", "s")
    asyncio.run(run())


def test_final_response_persists_before_queued_notice_and_stream_boundary():
    stream, request, store, remote, *_ = setup_run([completed("final body")])
    original = remote.stream

    async def with_notice(**kwargs):
        async for event in original(**kwargs):
            if event.kind == Kind.DELTA:
                async def persist():
                    return store.append_message(request.project_id, request.session_id,
                        role="system", content="compression completed", name="memory_compaction", status="done")
                await conversation_notifications.submit(request.project_id, request.session_id, persist)
                assert not any(m.role == "system" for m in store.persisted_messages)
            yield event
    remote.stream = with_notice
    events = asyncio.run(collect(stream, request))
    assert [m.role for m in store.persisted_messages] == ["user", "assistant", "system"]
    end = next(event for event in events if event["kind"] == "model_response_finished")
    assert end["notifications"][0]["name"] == "memory_compaction"
    assert end["has_tool_calls"] is False
    assert events.index(end) < next(i for i, event in enumerate(events) if event["kind"] == "conversation_run_settled")
    assert not conversation_notifications._sessions


def test_tool_response_boundary_flushes_notices_before_tools_execute():
    tool_events = (ChatStreamEvent(kind=Kind.DELTA, content="inspect first"),
        ChatStreamEvent(kind=Kind.TOOL_CALL, tool_call=ChatToolCall("call", "write_text_file", "{}")),
        ChatStreamEvent(kind=Kind.DONE, finish_reason="tool_calls"))
    stream, request, store, remote, *_ = setup_run([tool_events, completed()], tools=True)
    original = remote.stream
    inserted = False

    async def with_notice(**kwargs):
        nonlocal inserted
        async for event in original(**kwargs):
            if event.kind == Kind.DELTA and not inserted:
                inserted = True
                async def persist():
                    return store.append_message(request.project_id, request.session_id,
                        role="system", content="compression completed", name="memory_compaction", status="done")
                await conversation_notifications.submit(request.project_id, request.session_id, persist)
            yield event
    remote.stream = with_notice
    events = asyncio.run(collect(stream, request))
    kinds = [event["kind"] for event in events]
    first_end = kinds.index("model_response_finished")
    assert first_end < kinds.index("tool_call") < kinds.index("tool_result")
    assert events[first_end]["has_tool_calls"] is True
    assert events[first_end]["notifications"][0]["content"] == "compression completed"
    assert [m.role for m in store.persisted_messages][:4] == ["user", "assistant", "system", "tool"]
    assert all(message.content != "compression completed" for message in remote.requests[-1].messages)
    assert kinds.count("model_response_started") == 2
    assert kinds.count("model_response_finished") == 2


def test_retry_and_output_limit_have_separate_response_boundaries():
    for attempts in [[truncated(), completed()],
        [(ChatStreamEvent(kind=Kind.ERROR, error="disconnected", error_code="connect_failed"),), completed()]]:
        stream, request, *_ = setup_run(attempts)
        events = asyncio.run(collect(stream, request))
        boundaries = [event["kind"] for event in events if event["kind"].startswith("model_response_")]
        assert boundaries == ["model_response_started", "model_response_finished"] * 2
        assert not conversation_notifications._sessions


def test_output_limit_keeps_partial_then_notice_then_continuation():
    stream, request, store, remote, *_ = setup_run([truncated(), completed()], action="send_message", save=True)
    original = remote.stream
    inserted = False

    async def with_notice(**kwargs):
        nonlocal inserted
        async for event in original(**kwargs):
            if event.kind == Kind.DELTA and not inserted:
                inserted = True
                async def persist():
                    return store.append_message(request.project_id, request.session_id,
                        role="system", content="compression completed", name="memory_compaction", status="done")
                await conversation_notifications.submit(request.project_id, request.session_id, persist)
            yield event
    remote.stream = with_notice
    events = asyncio.run(collect(stream, request))
    assert [m.role for m in store.persisted_messages] == ["user", "assistant", "system", "user", "assistant"]
    assert store.persisted_messages[1].finish_reason == "output_limit"
    first_end = next(event for event in events if event["kind"] == "model_response_finished")
    assert first_end["notifications"][0]["content"] == "compression completed"
    assert events.index(first_end) < next(i for i, event in enumerate(events) if event["kind"] == "output_limit")


def test_cancel_releases_queued_notice_after_partial_reply_is_saved():
    stream, request, store, remote, *_ = setup_run([completed()])
    queued = asyncio.Event()
    waiting = asyncio.Event()

    async def blocked(**_kwargs):
        yield ChatStreamEvent(kind=Kind.DELTA, content="partial body")
        async def persist():
            return store.append_message(request.project_id, request.session_id,
                role="system", content="compression completed", name="memory_compaction", status="done")
        await conversation_notifications.submit(request.project_id, request.session_id, persist)
        queued.set()
        await waiting.wait()
    remote.stream = blocked

    async def run():
        task = asyncio.create_task(collect(stream, request))
        await queued.wait()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    asyncio.run(run())
    assert [m.role for m in store.persisted_messages] == ["user", "assistant", "system"]
    assert store.persisted_messages[1].content == "partial body"
    assert store.persisted_messages[1].status == "cancelled"
    assert not conversation_notifications._sessions


def test_notice_is_pushed_while_a_tool_is_still_waiting():
    tool_events = (ChatStreamEvent(kind=Kind.TOOL_CALL, tool_call=ChatToolCall("call", "write_text_file", "{}")),
        ChatStreamEvent(kind=Kind.DONE, finish_reason="tool_calls"))
    stream, request, store, remote, _usage, _recorder, executor = setup_run([tool_events, completed()], tools=True)
    entered, release = threading.Event(), threading.Event()
    original = executor.execute

    def wait_tool(call, *, context):
        entered.set()
        assert release.wait(timeout=5)
        return original(call, context=context)
    executor.execute = wait_tool

    async def run():
        events = []
        shown = asyncio.Event()

        async def consume():
            async for event in stream.stream_payloads(request, await_background_tasks=True):
                events.append(event)
                if event["kind"] == "conversation_notice":
                    shown.set()
        task = asyncio.create_task(consume())
        try:
            assert await asyncio.to_thread(entered.wait, 3)
            async def persist():
                return store.append_message(request.project_id, request.session_id,
                    role="system", content="compression completed during tool", name="memory_compaction", status="done")
            await conversation_notifications.submit(request.project_id, request.session_id, persist)
            await asyncio.wait_for(shown.wait(), 3)
            assert not any(event["kind"] == "tool_result" for event in events)
        finally:
            release.set()
            await task
        kinds = [event["kind"] for event in events]
        assert kinds.index("conversation_notice") < kinds.index("tool_result")
    asyncio.run(run())
