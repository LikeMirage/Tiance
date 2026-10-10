"""Read-only change notifications over WebSocket, outside the HTTP/1 pool."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
import logging

import anyio
from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

# Transport keepalive only; it does not expire or restart a subscription.
EVENT_SOCKET_HEARTBEAT_SECONDS = 15.0


async def serve_event_socket(
    websocket: WebSocket,
    events: AsyncGenerator[dict, None],
    *,
    heartbeat_seconds: float = EVENT_SOCKET_HEARTBEAT_SECONDS,
) -> None:
    if heartbeat_seconds <= 0:
        raise ValueError("heartbeat_seconds must be positive")
    pending: asyncio.Task | None = None
    tasks: list[asyncio.Task] = []

    async def send_events() -> None:
        nonlocal pending
        while True:
            if pending is None:
                pending = asyncio.create_task(anext(events))
            done, _ = await asyncio.wait((pending,), timeout=heartbeat_seconds)
            if not done:
                await websocket.send_json({"kind": "heartbeat"})
                continue
            try:
                payload = pending.result()
            except StopAsyncIteration:
                return
            pending = None
            await websocket.send_json(payload)

    async def receive_disconnect() -> None:
        while (await websocket.receive())["type"] != "websocket.disconnect":
            pass

    async def cleanup() -> None:
        for task in [*tasks, *([pending] if pending is not None else [])]:
            task.cancel()
        results = await asyncio.gather(
            *tasks, *([pending] if pending is not None else []), return_exceptions=True,
        )
        await events.aclose()
        for result in results:
            if isinstance(result, BaseException) and not isinstance(
                result, (asyncio.CancelledError, StopAsyncIteration, WebSocketDisconnect, OSError),
            ):
                raise result

    try:
        await websocket.accept()
        tasks = [asyncio.create_task(send_events()), asyncio.create_task(receive_disconnect())]
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
        if tasks[0] in done and tasks[1] not in done:
            await websocket.close()
    except (WebSocketDisconnect, OSError):
        pass
    except Exception:
        logger.exception("Change notification socket failed.")
        await websocket.close(code=1011)
    finally:
        # Do not leave a Windows watcher running after a tab closes, including
        # disconnects during a send and repeated cancellation during cleanup.
        with anyio.CancelScope(shield=True):
            closing = asyncio.create_task(cleanup())
            cancelled: asyncio.CancelledError | None = None
            while not closing.done():
                try:
                    await asyncio.shield(closing)
                except asyncio.CancelledError as error:
                    cancelled = error
            closing.result()
            if cancelled is not None:
                raise cancelled
