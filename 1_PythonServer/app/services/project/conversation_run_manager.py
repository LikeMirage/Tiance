from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Protocol, cast
from uuid import uuid4

from app.core.errors import AppError, ConflictError, NotFoundError
from app.domain.llm.chat import ChatCompletionRequest
from app.services.project.conversation_stream_checkpoints import (
    PERSISTENCE_CHECKPOINT_KIND,
)
from app.services.project.conversation_run_transport import (
    DEFAULT_SUBSCRIBER_MAX_CONTENT_UNITS,
    DEFAULT_SUBSCRIBER_MAX_EVENTS,
    ConversationRunMailbox,
    ConversationRunMailboxSignal,
    ConversationRunReplayBuffer,
)
from app.services.tools.client_tool_bridge import (
    ClientToolBridgeService,
    get_client_tool_bridge_service,
)
from app.services.tools.tool_permission_bridge import (
    ToolPermissionBridgeService,
    get_tool_permission_bridge_service,
)


logger = logging.getLogger(__name__)

_CHECKPOINT_WAIT_SECONDS = 0.25
_CHECKPOINT_POLL_SECONDS = 0.01
RESUME_RESET_KIND = "conversation_resume_reset"


class ConversationStreamResyncRequiredError(AppError):
    def __init__(self) -> None:
        super().__init__(
            "会话流接收速度不足，需要从已保存进度重新同步。",
            code="conversation_stream_resync_required",
            status_code=409,
        )


class ConversationPayloadStream(Protocol):
    def stream_payloads(
        self,
        request: ChatCompletionRequest,
        *,
        await_background_tasks: bool = False,
        include_persistence_checkpoints: bool = False,
    ) -> AsyncGenerator[dict[str, object | None], None]: ...


@dataclass(frozen=True, slots=True)
class ConversationRunSubscription:
    run_key: str
    subscription_id: str
    mailbox: ConversationRunMailbox


@dataclass(slots=True)
class _ConversationRun:
    key: str
    task: asyncio.Task[None] | None = None
    subscribers: dict[str, ConversationRunMailbox] = field(default_factory=dict)
    replay: ConversationRunReplayBuffer = field(default_factory=ConversationRunReplayBuffer)
    finished: bool = False


class ConversationRunManager:
    """Owns generation tasks independently from their SSE listeners."""

    def __init__(
        self,
        client_tool_bridge_service: ClientToolBridgeService | None = None,
        *,
        tool_permission_bridge_service: ToolPermissionBridgeService | None = None,
        subscriber_max_events: int = DEFAULT_SUBSCRIBER_MAX_EVENTS,
        subscriber_max_content_units: int = DEFAULT_SUBSCRIBER_MAX_CONTENT_UNITS,
    ) -> None:
        if subscriber_max_events < 1 or subscriber_max_content_units < 1:
            raise ValueError("Conversation subscriber limits must be positive.")
        self._runs: dict[str, _ConversationRun] = {}
        self._lock = asyncio.Lock()
        self._client_tool_bridge_service = (
            client_tool_bridge_service or get_client_tool_bridge_service()
        )
        self._tool_permission_bridge_service = (
            tool_permission_bridge_service or get_tool_permission_bridge_service()
        )
        self._subscriber_max_events = subscriber_max_events
        self._subscriber_max_content_units = subscriber_max_content_units

    def _create_mailbox(self) -> ConversationRunMailbox:
        return ConversationRunMailbox(
            max_events=self._subscriber_max_events,
            max_content_units=self._subscriber_max_content_units,
        )

    async def start(
        self,
        request: ChatCompletionRequest,
        stream_service: ConversationPayloadStream,
    ) -> ConversationRunSubscription:
        run_key = _request_run_key(request)
        subscription_id = uuid4().hex
        mailbox = self._create_mailbox()

        async with self._lock:
            existing = self._runs.get(run_key)
            if existing is not None and existing.task is not None and not existing.task.done():
                raise ConflictError("当前会话已有生成任务正在运行。")

            run = _ConversationRun(
                key=run_key,
                subscribers={subscription_id: mailbox},
            )
            self._runs[run_key] = run
            run.task = asyncio.create_task(
                self._run_generation(run, request, stream_service),
                name=f"conversation-run:{run_key}",
            )

        return ConversationRunSubscription(
            run_key=run_key,
            subscription_id=subscription_id,
            mailbox=mailbox,
        )

    async def subscribe(
        self,
        project_id: str,
        session_id: str,
        checkpoint_message_id: str | None = None,
    ) -> ConversationRunSubscription:
        run_key = _session_run_key(project_id, session_id)
        subscription_id = uuid4().hex
        mailbox = self._create_mailbox()
        loop = asyncio.get_running_loop()
        checkpoint_deadline = loop.time() + _CHECKPOINT_WAIT_SECONDS

        while True:
            async with self._lock:
                run = self._runs.get(run_key)
                if run is None or run.task is None or run.task.done() or run.finished:
                    raise NotFoundError("当前会话没有正在运行的生成任务。")
                checkpoint_matches = run.replay.matches_checkpoint(checkpoint_message_id)
                should_subscribe = (
                    not checkpoint_message_id
                    or checkpoint_matches
                    or loop.time() >= checkpoint_deadline
                )
                if should_subscribe:
                    replay_events = run.replay.replay_events()
                    requires_reset = run.replay.requires_reset(checkpoint_message_id)
                    buffered_events = (
                        ({"kind": RESUME_RESET_KIND}, *replay_events)
                        if requires_reset
                        else replay_events
                    )
                    should_subscribe = mailbox.can_accept_all(buffered_events)
                    if should_subscribe:
                        for event in buffered_events:
                            if not await self._should_replay_event(event):
                                continue
                            if not mailbox.try_put(event):
                                should_subscribe = False
                                break
                    if not should_subscribe:
                        mailbox.clear()
                    else:
                        run.subscribers[subscription_id] = mailbox
                        return ConversationRunSubscription(
                            run_key=run_key,
                            subscription_id=subscription_id,
                            mailbox=mailbox,
                        )

            await asyncio.sleep(_CHECKPOINT_POLL_SECONDS)

    async def _should_replay_event(self, event: dict[str, object | None]) -> bool:
        kind = event.get("kind")
        if kind == "client_tool_request":
            request = event.get("client_tool_request")
            bridge = self._client_tool_bridge_service
        elif kind == "tool_permission_request":
            request = event.get("tool_permission_request")
            bridge = self._tool_permission_bridge_service
        else:
            return True
        if not isinstance(request, dict):
            return False
        request_id = request.get("request_id")
        if not isinstance(request_id, str):
            return False
        return await bridge.should_replay_request(request_id)

    async def stream(
        self,
        subscription: ConversationRunSubscription,
    ) -> AsyncGenerator[dict[str, object | None], None]:
        try:
            while True:
                item = await subscription.mailbox.get()
                if item is ConversationRunMailboxSignal.END:
                    return
                if item is ConversationRunMailboxSignal.RESYNC_REQUIRED:
                    raise ConversationStreamResyncRequiredError()
                yield cast(dict[str, object | None], item)
        finally:
            await self.unsubscribe(subscription)

    async def unsubscribe(self, subscription: ConversationRunSubscription) -> None:
        async with self._lock:
            run = self._runs.get(subscription.run_key)
            if run is not None:
                run.subscribers.pop(subscription.subscription_id, None)

    async def stop(self, project_id: str, session_id: str) -> bool:
        run_key = _session_run_key(project_id, session_id)
        async with self._lock:
            run = self._runs.get(run_key)
            task = run.task if run is not None else None
            if task is None or task.done():
                return False
            assert run is not None

        pending_client_requests = (
            await self._client_tool_bridge_service.pending_request_ids(
                project_id=project_id,
                session_id=session_id,
            )
        )
        for request_id in pending_client_requests:
            await self._publish(
                run,
                {
                    "kind": "client_tool_request_cancelled",
                    "request_id": request_id,
                },
            )
        pending_permission_requests = (
            await self._tool_permission_bridge_service.pending_request_ids(
                project_id=project_id,
                session_id=session_id,
            )
        )
        for request_id in pending_permission_requests:
            await self._publish(
                run,
                {
                    "kind": "tool_permission_request_cancelled",
                    "request_id": request_id,
                },
            )
        task.cancel()

        await asyncio.gather(task, return_exceptions=True)
        await self._finish_run(run)
        return True

    async def is_running(self, project_id: str, session_id: str) -> bool:
        run_key = _session_run_key(project_id, session_id)
        async with self._lock:
            run = self._runs.get(run_key)
            return bool(
                run is not None
                and run.task is not None
                and not run.task.done()
                and not run.finished
            )

    async def close(self) -> None:
        async with self._lock:
            runs = [
                run
                for run in self._runs.values()
                if run.task is not None and not run.task.done()
            ]
            for run in runs:
                run.task.cancel()
        if runs:
            await asyncio.gather(
                *(run.task for run in runs if run.task is not None),
                return_exceptions=True,
            )
            for run in runs:
                await self._finish_run(run)

    async def _run_generation(
        self,
        run: _ConversationRun,
        request: ChatCompletionRequest,
        stream_service: ConversationPayloadStream,
    ) -> None:
        try:
            async for payload in stream_service.stream_payloads(
                request,
                include_persistence_checkpoints=True,
            ):
                await self._publish(run, payload)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Conversation background generation failed", extra={"run_key": run.key})
            if not run.replay.has_settled_event:
                await self._publish(
                    run,
                    {
                        "kind": "error",
                        "error": "会话生成任务异常终止。",
                        "error_code": "conversation_run_failed",
                    },
                )
        finally:
            await self._finish_run(run)

    async def _publish(
        self,
        run: _ConversationRun,
        item: dict[str, object | None],
    ) -> None:
        async with self._lock:
            sequenced_item = run.replay.append(item)
            subscribers = (
                ()
                if _is_persistence_checkpoint(sequenced_item)
                else tuple(run.subscribers.items())
            )
            for subscription_id, mailbox in subscribers:
                if mailbox.try_put(sequenced_item):
                    continue
                run.subscribers.pop(subscription_id, None)
                mailbox.force_signal(ConversationRunMailboxSignal.RESYNC_REQUIRED)

    async def _finish_run(self, run: _ConversationRun) -> None:
        async with self._lock:
            if run.finished:
                return
            run.finished = True
            mailboxes = tuple(run.subscribers.values())
            run.subscribers.clear()
            if self._runs.get(run.key) is run:
                self._runs.pop(run.key, None)
        for mailbox in mailboxes:
            mailbox.append_signal(ConversationRunMailboxSignal.END)


def _request_run_key(request: ChatCompletionRequest) -> str:
    if not request.project_id or not request.session_id:
        raise ValueError("Conversation background runs require project_id and session_id.")
    return _session_run_key(request.project_id, request.session_id)


def _session_run_key(project_id: str, session_id: str) -> str:
    return f"{project_id}:{session_id}"


def _is_persistence_checkpoint(event: dict[str, object | None]) -> bool:
    return event.get("kind") == PERSISTENCE_CHECKPOINT_KIND


@lru_cache
def get_conversation_run_manager() -> ConversationRunManager:
    return ConversationRunManager()
