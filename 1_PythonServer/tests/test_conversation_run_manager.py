import asyncio

import pytest

from app.core.errors import ConflictError, NotFoundError
from app.domain.llm.chat import (
    ChatCompletionRequest,
    ChatMessage,
    ChatMessageRole,
    ChatToolCall,
)
from app.services.project.conversation_run_manager import (
    ConversationRunManager,
    ConversationStreamResyncRequiredError,
)
from app.services.project.conversation_run_transport import ConversationRunReplayBuffer
from app.services.tools.client_tool_bridge import (
    ClientToolBridgeService,
    ClientToolResultPayload,
)


def test_listener_disconnect_does_not_cancel_generation():
    async def run_test():
        manager = ConversationRunManager()
        stream_service = _ControlledStreamService()
        subscription = await manager.start(_request(), stream_service)
        listener = manager.stream(subscription)

        assert await listener.__anext__() == {
            "kind": "delta",
            "content": "partial",
            "run_sequence": 1,
        }
        await listener.aclose()
        await asyncio.sleep(0)

        assert stream_service.cancelled is False
        stream_service.release.set()
        await asyncio.wait_for(stream_service.finished.wait(), timeout=1)
        assert stream_service.completed is True
        assert stream_service.cancelled is False

    asyncio.run(run_test())


def test_explicit_stop_cancels_generation():
    async def run_test():
        manager = ConversationRunManager()
        stream_service = _SettlingCancellationStreamService(partial_content="partial")
        subscription = await manager.start(_request(), stream_service)
        listener = manager.stream(subscription)

        assert await listener.__anext__() == {
            "kind": "conversation_run_started",
            "user_message_id": "user-message-1",
            "run_sequence": 1,
        }
        assert await listener.__anext__() == {
            "kind": "delta",
            "content": "partial",
            "run_sequence": 2,
        }
        assert await manager.stop("project-1", "session-1") is True
        await asyncio.wait_for(stream_service.finished.wait(), timeout=1)
        assert await listener.__anext__() == {
            "kind": "conversation_run_settled",
            "user_message_id": "user-message-1",
            "assistant_message_id": "assistant-cancelled-1",
            "status": "cancelled",
            "run_sequence": 3,
        }
        with pytest.raises(StopAsyncIteration):
            await listener.__anext__()

        assert stream_service.cancelled is True
        assert stream_service.completed is False

    asyncio.run(run_test())


def test_close_cancels_generation_and_broadcasts_settled_without_partial_content():
    async def run_test():
        manager = ConversationRunManager()
        stream_service = _SettlingCancellationStreamService(partial_content="")
        subscription = await manager.start(_request(), stream_service)
        listener = manager.stream(subscription)

        assert await listener.__anext__() == {
            "kind": "conversation_run_started",
            "user_message_id": "user-message-1",
            "run_sequence": 1,
        }
        await manager.close()
        await asyncio.wait_for(stream_service.finished.wait(), timeout=1)
        assert await listener.__anext__() == {
            "kind": "conversation_run_settled",
            "user_message_id": "user-message-1",
            "assistant_message_id": None,
            "status": "cancelled",
            "run_sequence": 2,
        }
        with pytest.raises(StopAsyncIteration):
            await listener.__anext__()

        assert stream_service.cancelled is True

    asyncio.run(run_test())


def test_second_generation_for_same_session_is_rejected():
    async def run_test():
        manager = ConversationRunManager()
        stream_service = _ControlledStreamService()
        subscription = await manager.start(_request(), stream_service)

        with pytest.raises(ConflictError, match="已有生成任务"):
            await manager.start(_request(), stream_service)

        await manager.stop("project-1", "session-1")
        listener = manager.stream(subscription)
        with pytest.raises(StopAsyncIteration):
            await listener.__anext__()

    asyncio.run(run_test())


def test_settled_stream_failure_does_not_publish_a_second_generic_error():
    async def run_test():
        manager = ConversationRunManager()
        subscription = await manager.start(_request(), _SettledThenFailStreamService())
        listener = manager.stream(subscription)

        assert await listener.__anext__() == {
            "kind": "conversation_run_started",
            "user_message_id": "user-message-1",
            "run_sequence": 1,
        }
        assert await listener.__anext__() == {
            "kind": "conversation_run_settled",
            "user_message_id": "user-message-1",
            "assistant_message_id": "assistant-message-1",
            "status": "done",
            "run_sequence": 2,
        }
        with pytest.raises(StopAsyncIteration):
            await listener.__anext__()

    asyncio.run(run_test())


def test_empty_response_terminal_is_not_followed_by_a_generic_run_error():
    async def run_test():
        manager = ConversationRunManager()
        subscription = await manager.start(_request(), _EmptyResponseThenFailStreamService())
        listener = manager.stream(subscription)

        assert await listener.__anext__() == {
            "kind": "conversation_run_started",
            "user_message_id": "user-message-1",
            "run_sequence": 1,
        }
        assert await listener.__anext__() == {
            "kind": "conversation_run_settled",
            "user_message_id": "user-message-1",
            "assistant_message_id": "assistant-error-1",
            "status": "error",
            "run_sequence": 2,
        }
        assert await listener.__anext__() == {
            "kind": "error",
            "error": "模型未返回可持久化的回复内容。",
            "error_code": "empty_model_response",
            "run_sequence": 3,
        }
        with pytest.raises(StopAsyncIteration):
            await listener.__anext__()

    asyncio.run(run_test())


def test_reconnect_replays_existing_events_and_continues_streaming():
    async def run_test():
        manager = ConversationRunManager()
        stream_service = _ControlledStreamService()
        original = await manager.start(_request(), stream_service)
        original_listener = manager.stream(original)

        first_event = await original_listener.__anext__()
        assert first_event == {
            "kind": "delta",
            "content": "partial",
            "run_sequence": 1,
        }
        await original_listener.aclose()

        reconnected = await manager.subscribe("project-1", "session-1")
        reconnected_listener = manager.stream(reconnected)
        assert await reconnected_listener.__anext__() == first_event

        stream_service.release.set()
        assert await reconnected_listener.__anext__() == {
            "kind": "done",
            "run_sequence": 2,
        }
        with pytest.raises(StopAsyncIteration):
            await reconnected_listener.__anext__()

    asyncio.run(run_test())


def test_reconnect_replays_client_tool_request_while_result_is_pending():
    async def run_test():
        bridge = ClientToolBridgeService()
        client_request = await bridge.create_request(
            ChatToolCall(call_id="call-1", name="open_editor", arguments="{}"),
            project_id="project-1",
            session_id="session-1",
            timeout_seconds=30,
        )
        manager = ConversationRunManager(bridge)
        stream_service = _ClientToolRunStreamService(client_request.request_id)
        original = await manager.start(_request(), stream_service)
        original_listener = manager.stream(original)

        first_event = await original_listener.__anext__()
        assert first_event == {
            "kind": "client_tool_request",
            "client_tool_request": {
                "request_id": client_request.request_id,
                "name": "open_editor",
            },
            "run_sequence": 1,
        }
        await original_listener.aclose()

        reconnected = await manager.subscribe("project-1", "session-1")
        reconnected_listener = manager.stream(reconnected)
        assert await reconnected_listener.__anext__() == first_event

        lease = await bridge.claim_request(
            client_request.request_id,
            executor_id="frontend-1",
        )
        assert lease.acquired is True
        assert await bridge.submit_result(
            client_request.request_id,
            ClientToolResultPayload(ok=True, content={"opened": True}),
            executor_id="frontend-1",
            claim_id=lease.claim_id or "",
        ) is True
        assert await bridge.wait_for_result(
            client_request.request_id,
            timeout_seconds=1,
        ) == ClientToolResultPayload(ok=True, content={"opened": True})
        stream_service.release.set()
        await _drain_listener(reconnected_listener)

    asyncio.run(run_test())


def test_reconnect_skips_submitted_client_tool_request_but_receives_later_events():
    async def run_test():
        bridge = ClientToolBridgeService()
        client_request = await bridge.create_request(
            ChatToolCall(call_id="call-1", name="open_editor", arguments="{}"),
            project_id="project-1",
            session_id="session-1",
            timeout_seconds=30,
        )
        manager = ConversationRunManager(bridge)
        stream_service = _ClientToolRunStreamService(client_request.request_id)
        original = await manager.start(_request(), stream_service)
        original_listener = manager.stream(original)
        assert (await original_listener.__anext__())["kind"] == "client_tool_request"
        await original_listener.aclose()

        submitted_result = ClientToolResultPayload(ok=True, content={"opened": True})
        lease = await bridge.claim_request(
            client_request.request_id,
            executor_id="frontend-1",
        )
        assert await bridge.submit_result(
            client_request.request_id,
            submitted_result,
            executor_id="frontend-1",
            claim_id=lease.claim_id or "",
        ) is True
        reconnected = await manager.subscribe("project-1", "session-1")
        reconnected_listener = manager.stream(reconnected)
        assert await bridge.wait_for_result(
            client_request.request_id,
            timeout_seconds=1,
        ) == submitted_result

        stream_service.release.set()
        assert await reconnected_listener.__anext__() == {
            "kind": "tool_result",
            "tool_result": {"request_id": client_request.request_id},
            "run_sequence": 2,
        }
        assert await reconnected_listener.__anext__() == {
            "kind": "conversation_run_settled",
            "user_message_id": "user-message-1",
            "assistant_message_id": "assistant-message-1",
            "status": "done",
            "run_sequence": 3,
        }
        assert await reconnected_listener.__anext__() == {
            "kind": "done",
            "run_sequence": 4,
        }
        with pytest.raises(StopAsyncIteration):
            await reconnected_listener.__anext__()

    asyncio.run(run_test())


def test_concurrent_client_tool_result_submissions_accept_exactly_once():
    async def run_test():
        bridge = ClientToolBridgeService()
        client_request = await bridge.create_request(
            ChatToolCall(call_id="call-1", name="open_editor", arguments="{}"),
            project_id="project-1",
            session_id="session-1",
            timeout_seconds=30,
        )
        submitted_result = ClientToolResultPayload(ok=True, content={"opened": True})
        lease = await bridge.claim_request(
            client_request.request_id,
            executor_id="frontend-1",
        )

        accepted = await asyncio.gather(
            *(
                bridge.submit_result(
                    client_request.request_id,
                    submitted_result,
                    executor_id="frontend-1",
                    claim_id=lease.claim_id or "",
                )
                for _ in range(20)
            )
        )

        assert accepted.count(True) == 1
        assert accepted.count(False) == 19
        assert await bridge.should_replay_request(client_request.request_id) is False
        assert await bridge.wait_for_result(
            client_request.request_id,
            timeout_seconds=1,
        ) == submitted_result

    asyncio.run(run_test())


def test_explicit_stop_notifies_frontend_to_release_pending_client_tool_wait():
    async def run_test():
        bridge = ClientToolBridgeService()
        client_request = await bridge.create_request(
            ChatToolCall(call_id="call-1", name="open_editor", arguments="{}"),
            project_id="project-1",
            session_id="session-1",
            timeout_seconds=30,
        )
        manager = ConversationRunManager(bridge)
        stream_service = _ClientToolRunStreamService(client_request.request_id)
        subscription = await manager.start(_request(), stream_service)
        listener = manager.stream(subscription)

        assert (await listener.__anext__())["kind"] == "client_tool_request"
        assert await manager.stop("project-1", "session-1") is True
        assert await listener.__anext__() == {
            "kind": "client_tool_request_cancelled",
            "request_id": client_request.request_id,
            "run_sequence": 2,
        }
        with pytest.raises(StopAsyncIteration):
            await listener.__anext__()

    asyncio.run(run_test())


def test_concurrent_client_tool_claims_acquire_exactly_once():
    async def run_test():
        bridge = ClientToolBridgeService()
        client_request = await bridge.create_request(
            ChatToolCall(call_id="call-1", name="open_editor", arguments="{}"),
            project_id="project-1",
            session_id="session-1",
            timeout_seconds=30,
        )

        leases = await asyncio.gather(
            *(
                bridge.claim_request(
                    client_request.request_id,
                    executor_id=f"frontend-{index}",
                )
                for index in range(20)
            )
        )

        assert sum(lease.acquired for lease in leases) == 1
        owner_index = next(index for index, lease in enumerate(leases) if lease.acquired)
        resumed = await bridge.claim_request(
            client_request.request_id,
            executor_id=f"frontend-{owner_index}",
        )
        assert resumed.acquired is True
        assert resumed.resumed is True
        assert resumed.claim_id == leases[owner_index].claim_id

    asyncio.run(run_test())


def test_abandoned_client_tool_claim_settles_as_explicit_failure():
    async def run_test():
        bridge = ClientToolBridgeService(lease_duration_seconds=0.02)
        client_request = await bridge.create_request(
            ChatToolCall(call_id="call-1", name="open_editor", arguments="{}"),
            project_id="project-1",
            session_id="session-1",
            timeout_seconds=30,
        )
        lease = await bridge.claim_request(
            client_request.request_id,
            executor_id="frontend-1",
        )
        assert lease.acquired is True

        result = await bridge.wait_for_result(
            client_request.request_id,
            timeout_seconds=1,
        )

        assert result.ok is False
        assert result.content["error_code"] == "CLIENT_TOOL_EXECUTOR_LOST"
        assert "执行租约" in (result.error or "")

    asyncio.run(run_test())


def test_unclaimed_client_tool_request_settles_without_waiting_for_tool_timeout():
    async def run_test():
        bridge = ClientToolBridgeService(lease_duration_seconds=0.02)
        client_request = await bridge.create_request(
            ChatToolCall(call_id="call-1", name="open_editor", arguments="{}"),
            project_id="project-1",
            session_id="session-1",
            timeout_seconds=30,
        )

        result = await bridge.wait_for_result(
            client_request.request_id,
            timeout_seconds=1,
        )

        assert result.ok is False
        assert result.content["error_code"] == "CLIENT_TOOL_EXECUTOR_LOST"
        assert "执行租约" in (result.error or "")

    asyncio.run(run_test())


def test_client_tool_lease_renewal_keeps_request_active_for_its_owner():
    async def run_test():
        bridge = ClientToolBridgeService(lease_duration_seconds=0.04)
        client_request = await bridge.create_request(
            ChatToolCall(call_id="call-1", name="open_editor", arguments="{}"),
            project_id="project-1",
            session_id="session-1",
            timeout_seconds=30,
        )
        lease = await bridge.claim_request(
            client_request.request_id,
            executor_id="frontend-1",
        )
        await asyncio.sleep(0.025)
        assert await bridge.renew_claim(
            client_request.request_id,
            executor_id="frontend-1",
            claim_id=lease.claim_id or "",
        ) is True
        await asyncio.sleep(0.025)
        assert await bridge.submit_result(
            client_request.request_id,
            ClientToolResultPayload(ok=True, content={"opened": True}),
            executor_id="frontend-1",
            claim_id=lease.claim_id or "",
        ) is True

        result = await bridge.wait_for_result(
            client_request.request_id,
            timeout_seconds=1,
        )
        assert result.ok is True

    asyncio.run(run_test())


def test_client_tool_result_rejects_non_owner_credentials():
    async def run_test():
        bridge = ClientToolBridgeService()
        client_request = await bridge.create_request(
            ChatToolCall(call_id="call-1", name="open_editor", arguments="{}"),
            project_id="project-1",
            session_id="session-1",
            timeout_seconds=30,
        )
        lease = await bridge.claim_request(
            client_request.request_id,
            executor_id="frontend-1",
        )

        assert await bridge.submit_result(
            client_request.request_id,
            ClientToolResultPayload(ok=True),
            executor_id="frontend-2",
            claim_id=lease.claim_id or "",
        ) is False
        assert await bridge.submit_result(
            client_request.request_id,
            ClientToolResultPayload(ok=True),
            executor_id="frontend-1",
            claim_id="wrong-claim",
        ) is False

    asyncio.run(run_test())


def test_reconnect_replays_only_events_after_persisted_message_checkpoint():
    async def run_test():
        manager = ConversationRunManager()
        stream_service = _CheckpointStreamService()
        original = await manager.start(_request(), stream_service)
        original_listener = manager.stream(original)

        assert await original_listener.__anext__() == {
            "kind": "delta",
            "content": "persisted answer",
            "run_sequence": 1,
        }
        assert await original_listener.__anext__() == {
            "kind": "tool_call",
            "run_sequence": 3,
        }
        await original_listener.aclose()

        reconnected = await manager.subscribe(
            "project-1",
            "session-1",
            "assistant-message-1",
        )
        reconnected_listener = manager.stream(reconnected)
        assert await reconnected_listener.__anext__() == {
            "kind": "tool_call",
            "run_sequence": 3,
        }

        stream_service.release.set()
        assert await reconnected_listener.__anext__() == {
            "kind": "done",
            "run_sequence": 4,
        }
        with pytest.raises(StopAsyncIteration):
            await reconnected_listener.__anext__()

    asyncio.run(run_test())


def test_reconnect_waits_for_checkpoint_that_was_persisted_just_before_subscribe():
    async def run_test():
        manager = ConversationRunManager()
        stream_service = _DelayedCheckpointStreamService()
        original = await manager.start(_request(), stream_service)
        original_listener = manager.stream(original)

        assert await original_listener.__anext__() == {
            "kind": "delta",
            "content": "persisting",
            "run_sequence": 1,
        }
        reconnect_task = asyncio.create_task(manager.subscribe(
            "project-1",
            "session-1",
            "assistant-message-delayed",
        ))
        await asyncio.sleep(0.02)
        assert reconnect_task.done() is False

        stream_service.release_checkpoint.set()
        reconnected = await asyncio.wait_for(reconnect_task, timeout=1)
        reconnected_listener = manager.stream(reconnected)
        assert await reconnected_listener.__anext__() == {
            "kind": "tool_call",
            "run_sequence": 3,
        }

        stream_service.finish.set()
        with pytest.raises(StopAsyncIteration):
            await reconnected_listener.__anext__()

    asyncio.run(run_test())


def test_reconnect_explicitly_resets_when_requested_checkpoint_is_not_in_current_run():
    async def run_test():
        manager = ConversationRunManager()
        stream_service = _ControlledStreamService()
        original = await manager.start(_request(), stream_service)
        original_listener = manager.stream(original)
        assert await original_listener.__anext__() == {
            "kind": "delta",
            "content": "partial",
            "run_sequence": 1,
        }
        await original_listener.aclose()

        reconnected = await manager.subscribe(
            "project-1",
            "session-1",
            "checkpoint-from-an-older-run",
        )
        reconnected_listener = manager.stream(reconnected)
        assert await reconnected_listener.__anext__() == {
            "kind": "conversation_resume_reset",
        }
        assert await reconnected_listener.__anext__() == {
            "kind": "delta",
            "content": "partial",
            "run_sequence": 1,
        }

        await manager.stop("project-1", "session-1")

    asyncio.run(run_test())


def test_reconnect_rejects_finished_or_missing_run():
    async def run_test():
        manager = ConversationRunManager()
        with pytest.raises(NotFoundError, match="没有正在运行"):
            await manager.subscribe("project-1", "session-1")

    asyncio.run(run_test())


def test_replay_buffer_compacts_text_without_mutating_live_events_and_prunes_at_checkpoint():
    replay = ConversationRunReplayBuffer()

    first = replay.append({"kind": "delta", "content": "first"})
    second = replay.append({"kind": "delta", "content": " second"})

    assert first == {"kind": "delta", "content": "first", "run_sequence": 1}
    assert second == {"kind": "delta", "content": " second", "run_sequence": 2}
    assert replay.replay_events() == (
        {"kind": "delta", "content": "first second", "run_sequence": 2},
    )

    replay.append({
        "kind": "_conversation_persistence_checkpoint",
        "checkpoint_message_id": "assistant-message-1",
    })

    assert replay.replay_events() == ()
    assert replay.matches_checkpoint("assistant-message-1") is True
    assert replay.append({"kind": "done"})["run_sequence"] == 4


def test_replay_buffer_keeps_run_identity_after_durable_checkpoint():
    replay = ConversationRunReplayBuffer()
    started = replay.append({
        "kind": "conversation_run_started",
        "user_message_id": "user-message-1",
    })
    replay.append({"kind": "delta", "content": "persisted"})
    replay.append({
        "kind": "_conversation_persistence_checkpoint",
        "checkpoint_message_id": "assistant-message-1",
    })

    assert replay.replay_events() == (started,)


def test_slow_subscriber_is_detached_without_cancelling_generation():
    async def run_test():
        manager = ConversationRunManager(subscriber_max_events=1)
        stream_service = _TwoEventThenWaitStreamService()
        subscription = await manager.start(_request(), stream_service)

        await asyncio.wait_for(stream_service.published.wait(), timeout=1)
        listener = manager.stream(subscription)
        with pytest.raises(ConversationStreamResyncRequiredError):
            await listener.__anext__()

        assert await manager.is_running("project-1", "session-1") is True
        assert stream_service.cancelled is False
        stream_service.release.set()
        await asyncio.wait_for(stream_service.finished.wait(), timeout=1)

    asyncio.run(run_test())


def test_reconnect_waits_until_oversized_replay_is_covered_by_checkpoint():
    async def run_test():
        manager = ConversationRunManager(subscriber_max_events=2)
        stream_service = _OversizedReplayThenCheckpointStreamService()
        original = await manager.start(_request(), stream_service)
        await asyncio.wait_for(stream_service.replay_ready.wait(), timeout=1)

        reconnect_task = asyncio.create_task(
            manager.subscribe("project-1", "session-1"),
        )
        await asyncio.sleep(0.03)
        assert reconnect_task.done() is False

        stream_service.release_checkpoint.set()
        reconnected = await asyncio.wait_for(reconnect_task, timeout=1)
        listener = manager.stream(reconnected)
        assert await listener.__anext__() == {
            "kind": "conversation_resume_reset",
        }
        assert await listener.__anext__() == {
            "kind": "done",
            "run_sequence": 5,
        }

        stream_service.finish.set()
        with pytest.raises(StopAsyncIteration):
            await listener.__anext__()
        await manager.unsubscribe(original)

    asyncio.run(run_test())


async def _drain_listener(listener) -> list[dict[str, object | None]]:
    return [event async for event in listener]


def _request() -> ChatCompletionRequest:
    return ChatCompletionRequest(
        provider_id="deepseek",
        model_id="deepseek-v4",
        project_id="project-1",
        session_id="session-1",
        messages=(ChatMessage(role=ChatMessageRole.USER, content="hi"),),
    )


class _ControlledStreamService:
    def __init__(self) -> None:
        self.release = asyncio.Event()
        self.finished = asyncio.Event()
        self.cancelled = False
        self.completed = False

    async def stream_payloads(
        self,
        _request,
        *,
        await_background_tasks=False,
        include_persistence_checkpoints=False,
    ):
        del await_background_tasks
        del include_persistence_checkpoints
        try:
            yield {"kind": "delta", "content": "partial"}
            await self.release.wait()
            self.completed = True
            yield {"kind": "done"}
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        finally:
            self.finished.set()


class _SettlingCancellationStreamService:
    def __init__(self, *, partial_content: str) -> None:
        self.partial_content = partial_content
        self.finished = asyncio.Event()
        self.cancelled = False
        self.completed = False

    async def stream_payloads(
        self,
        _request,
        *,
        await_background_tasks=False,
        include_persistence_checkpoints=False,
    ):
        del await_background_tasks
        del include_persistence_checkpoints
        try:
            yield {
                "kind": "conversation_run_started",
                "user_message_id": "user-message-1",
            }
            if self.partial_content:
                yield {"kind": "delta", "content": self.partial_content}
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            yield {
                "kind": "conversation_run_settled",
                "user_message_id": "user-message-1",
                "assistant_message_id": (
                    "assistant-cancelled-1" if self.partial_content else None
                ),
                "status": "cancelled",
            }
            raise
        finally:
            self.finished.set()


class _ClientToolRunStreamService:
    def __init__(self, request_id: str) -> None:
        self.request_id = request_id
        self.release = asyncio.Event()

    async def stream_payloads(
        self,
        _request,
        *,
        await_background_tasks=False,
        include_persistence_checkpoints=False,
    ):
        del await_background_tasks
        del include_persistence_checkpoints
        yield {
            "kind": "client_tool_request",
            "client_tool_request": {
                "request_id": self.request_id,
                "name": "open_editor",
            },
        }
        await self.release.wait()
        yield {
            "kind": "tool_result",
            "tool_result": {"request_id": self.request_id},
        }
        yield {
            "kind": "conversation_run_settled",
            "user_message_id": "user-message-1",
            "assistant_message_id": "assistant-message-1",
            "status": "done",
        }
        yield {"kind": "done"}


class _SettledThenFailStreamService:
    async def stream_payloads(
        self,
        _request,
        *,
        await_background_tasks=False,
        include_persistence_checkpoints=False,
    ):
        del await_background_tasks
        del include_persistence_checkpoints
        yield {
            "kind": "conversation_run_started",
            "user_message_id": "user-message-1",
        }
        yield {
            "kind": "conversation_run_settled",
            "user_message_id": "user-message-1",
            "assistant_message_id": "assistant-message-1",
            "status": "done",
        }
        raise RuntimeError("usage persistence failed after assistant commit")


class _EmptyResponseThenFailStreamService:
    async def stream_payloads(
        self,
        _request,
        *,
        await_background_tasks=False,
        include_persistence_checkpoints=False,
    ):
        del await_background_tasks
        del include_persistence_checkpoints
        yield {
            "kind": "conversation_run_started",
            "user_message_id": "user-message-1",
        }
        yield {
            "kind": "conversation_run_settled",
            "user_message_id": "user-message-1",
            "assistant_message_id": "assistant-error-1",
            "status": "error",
        }
        yield {
            "kind": "error",
            "error": "模型未返回可持久化的回复内容。",
            "error_code": "empty_model_response",
        }
        raise RuntimeError("stream failed after publishing the empty-response terminal")


class _CheckpointStreamService:
    def __init__(self) -> None:
        self.release = asyncio.Event()

    async def stream_payloads(
        self,
        _request,
        *,
        await_background_tasks=False,
        include_persistence_checkpoints=False,
    ):
        del await_background_tasks
        assert include_persistence_checkpoints is True
        yield {"kind": "delta", "content": "persisted answer"}
        yield {
            "kind": "_conversation_persistence_checkpoint",
            "checkpoint_message_id": "assistant-message-1",
        }
        yield {"kind": "tool_call"}
        await self.release.wait()
        yield {"kind": "done"}


class _DelayedCheckpointStreamService:
    def __init__(self) -> None:
        self.finish = asyncio.Event()
        self.release_checkpoint = asyncio.Event()

    async def stream_payloads(
        self,
        _request,
        *,
        await_background_tasks=False,
        include_persistence_checkpoints=False,
    ):
        del await_background_tasks
        assert include_persistence_checkpoints is True
        yield {"kind": "delta", "content": "persisting"}
        await self.release_checkpoint.wait()
        yield {
            "kind": "_conversation_persistence_checkpoint",
            "checkpoint_message_id": "assistant-message-delayed",
        }
        yield {"kind": "tool_call"}
        await self.finish.wait()


class _TwoEventThenWaitStreamService:
    def __init__(self) -> None:
        self.cancelled = False
        self.finished = asyncio.Event()
        self.published = asyncio.Event()
        self.release = asyncio.Event()

    async def stream_payloads(
        self,
        _request,
        *,
        await_background_tasks=False,
        include_persistence_checkpoints=False,
    ):
        del await_background_tasks, include_persistence_checkpoints
        try:
            yield {"kind": "tool_call", "tool_call": {"call_id": "call-1"}}
            yield {"kind": "tool_call", "tool_call": {"call_id": "call-2"}}
            self.published.set()
            await self.release.wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        finally:
            self.finished.set()


class _OversizedReplayThenCheckpointStreamService:
    def __init__(self) -> None:
        self.finish = asyncio.Event()
        self.release_checkpoint = asyncio.Event()
        self.replay_ready = asyncio.Event()

    async def stream_payloads(
        self,
        _request,
        *,
        await_background_tasks=False,
        include_persistence_checkpoints=False,
    ):
        del await_background_tasks
        assert include_persistence_checkpoints is True
        yield {"kind": "tool_call", "tool_call": {"call_id": "call-1"}}
        yield {"kind": "tool_call", "tool_call": {"call_id": "call-2"}}
        yield {"kind": "tool_call", "tool_call": {"call_id": "call-3"}}
        self.replay_ready.set()
        await self.release_checkpoint.wait()
        yield {
            "kind": "_conversation_persistence_checkpoint",
            "checkpoint_message_id": "assistant-message-1",
        }
        yield {"kind": "done"}
        await self.finish.wait()
