from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.core.errors import AppError, BadRequestError, NotFoundError
from app.schemas.llm.chat_socket import (
    CHAT_SOCKET_COMMAND_ADAPTER,
    ChatSocketCommand,
    ChatSocketStartCommand,
    ChatSocketSubscribeCommand,
    ChatSocketUnsubscribeCommand,
)
from app.services.project.conversation_run_manager import (
    ConversationRunSubscription,
    get_conversation_run_manager,
)
from app.services.project.conversation_stream import (
    get_project_conversation_stream_service,
)
from app.services.project import get_project_conversation_service


router = APIRouter(prefix="/llm/chat", tags=["llm"])
_SOCKET_SEND_TIMEOUT_SECONDS = 15.0


class _ChatSocketSendTimeoutError(RuntimeError):
    pass


@router.websocket("/completions/socket")
async def chat_completion_socket(websocket: WebSocket) -> None:
    await websocket.accept()
    session = _ChatSocketSession(websocket)
    await session.run()


class _ChatSocketSession:
    def __init__(self, websocket: WebSocket) -> None:
        self._websocket = websocket
        self._channel_tasks: dict[str, asyncio.Task[None]] = {}
        self._send_lock = asyncio.Lock()

    async def run(self) -> None:
        try:
            while True:
                payload = await self._websocket.receive_json()
                await self._handle_payload(payload)
        except WebSocketDisconnect:
            pass
        finally:
            await self._cancel_all_channels()

    async def _handle_payload(self, payload: Any) -> None:
        channel_id = _read_channel_id(payload)
        try:
            command = CHAT_SOCKET_COMMAND_ADAPTER.validate_python(payload)
        except ValidationError:
            await self._send_error(
                channel_id,
                BadRequestError("会话流通道命令参数无效。"),
            )
            return

        if isinstance(command, ChatSocketUnsubscribeCommand):
            await self._cancel_channel(command.channel_id)
            return

        if command.channel_id in self._channel_tasks:
            await self._send_error(
                command.channel_id,
                BadRequestError("会话流通道标识已在使用。"),
            )
            return

        task = asyncio.create_task(
            self._run_channel(command),
            name=f"chat-socket:{command.channel_id}",
        )
        self._channel_tasks[command.channel_id] = task
        task.add_done_callback(
            lambda completed, channel_id=command.channel_id: self._forget_channel(
                channel_id,
                completed,
            )
        )

    async def _run_channel(
        self,
        command: ChatSocketStartCommand | ChatSocketSubscribeCommand,
    ) -> None:
        try:
            if isinstance(command, ChatSocketStartCommand):
                await self._start_and_forward(command)
            else:
                await self._subscribe_and_forward(command)
            await self._send({
                "type": "complete",
                "channel_id": command.channel_id,
            })
        except asyncio.CancelledError:
            raise
        except (_ChatSocketSendTimeoutError, WebSocketDisconnect):
            return
        except AppError as error:
            await self._send_error(command.channel_id, error)
        except Exception:
            await self._send({
                "type": "error",
                "channel_id": command.channel_id,
                "status": 500,
                "code": "chat_socket_error",
                "error": "会话流通道异常终止。",
            })

    async def _start_and_forward(self, command: ChatSocketStartCommand) -> None:
        request = command.request.to_domain()
        if not request.messages:
            raise BadRequestError("发送消息内容不能为空。")
        service = get_project_conversation_stream_service()
        await asyncio.to_thread(service.validate_conversation_target, request)

        if not request.project_id or not request.session_id:
            await self._send_opened(command.channel_id)
            async for event in service.stream_payloads(request):
                await self._send_event(command.channel_id, event)
            return

        subscription = await get_conversation_run_manager().start(request, service)
        await self._send_opened(command.channel_id)
        await self._forward_subscription(command.channel_id, subscription)

    async def _subscribe_and_forward(
        self,
        command: ChatSocketSubscribeCommand,
    ) -> None:
        try:
            subscription = await get_conversation_run_manager().subscribe(
                command.project_id,
                command.session_id,
                command.checkpoint_message_id,
            )
        except NotFoundError:
            await asyncio.to_thread(
                get_project_conversation_service().reconcile_missing_run_runtime_status,
                command.project_id,
                command.session_id,
            )
            raise
        await self._send_opened(command.channel_id)
        await self._forward_subscription(command.channel_id, subscription)

    async def _forward_subscription(
        self,
        channel_id: str,
        subscription: ConversationRunSubscription,
    ) -> None:
        async for event in get_conversation_run_manager().stream(subscription):
            await self._send_event(channel_id, event)

    async def _send_event(self, channel_id: str, event: dict[str, Any]) -> None:
        await self._send({
            "type": "event",
            "channel_id": channel_id,
            "event": event,
        })

    async def _send_opened(self, channel_id: str) -> None:
        await self._send({
            "type": "opened",
            "channel_id": channel_id,
        })

    async def _send_error(self, channel_id: str, error: AppError) -> None:
        await self._send({
            "type": "error",
            "channel_id": channel_id,
            "status": error.status_code,
            "code": error.code,
            "error": error.message,
        })

    async def _send(self, payload: dict[str, Any]) -> None:
        async with self._send_lock:
            try:
                await asyncio.wait_for(
                    self._websocket.send_json(payload),
                    timeout=_SOCKET_SEND_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError as error:
                with suppress(Exception):
                    await asyncio.wait_for(
                        self._websocket.close(code=1011),
                        timeout=1.0,
                    )
                raise _ChatSocketSendTimeoutError from error

    async def _cancel_channel(self, channel_id: str) -> None:
        task = self._channel_tasks.pop(channel_id, None)
        if task is None:
            return
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    async def _cancel_all_channels(self) -> None:
        tasks = tuple(self._channel_tasks.values())
        self._channel_tasks.clear()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def _forget_channel(
        self,
        channel_id: str,
        completed: asyncio.Task[None],
    ) -> None:
        if self._channel_tasks.get(channel_id) is completed:
            self._channel_tasks.pop(channel_id, None)


def _read_channel_id(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    channel_id = payload.get("channel_id")
    return channel_id if isinstance(channel_id, str) else ""
