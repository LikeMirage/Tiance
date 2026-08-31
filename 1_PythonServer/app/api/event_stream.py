from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator

import anyio
from starlette.responses import StreamingResponse
from starlette.types import Send


class EventStreamResponse(StreamingResponse):
    """Own the event iterator until disconnect cleanup has finished.

    Heartbeats are SSE comments, not application events. Waiting for a heartbeat
    must never cancel the pending read or restart the underlying subscription.
    """

    def __init__(self, content: AsyncGenerator[str, None], *, heartbeat_seconds: float):
        if heartbeat_seconds <= 0:
            raise ValueError("heartbeat_seconds must be positive")
        super().__init__(
            content,
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
        self._events = content
        self._heartbeat_seconds = heartbeat_seconds

    async def stream_response(self, send: Send) -> None:
        pending: asyncio.Task[str] | None = None
        try:
            await send({
                "type": "http.response.start",
                "status": self.status_code,
                "headers": self.raw_headers,
            })
            while True:
                if pending is None:
                    pending = asyncio.create_task(anext(self._events))
                done, _ = await asyncio.wait((pending,), timeout=self._heartbeat_seconds)
                if done:
                    try:
                        chunk = pending.result().encode(self.charset)
                    except StopAsyncIteration:
                        break
                    pending = None
                else:
                    chunk = b": keep-alive\n\n"
                await send({"type": "http.response.body", "body": chunk, "more_body": True})
            await send({"type": "http.response.body", "body": b"", "more_body": False})
        finally:
            # Starlette cancels the sender on disconnect. Cleanup must survive
            # both that AnyIO cancel scope and subsequent asyncio cancellation.
            with anyio.CancelScope(shield=True):
                cleanup = asyncio.create_task(self._close_events(pending))
                cancelled: asyncio.CancelledError | None = None
                while not cleanup.done():
                    try:
                        await asyncio.shield(cleanup)
                    except asyncio.CancelledError as error:
                        cancelled = error
                cleanup.result()
                if cancelled is not None:
                    raise cancelled

    async def _close_events(self, pending: asyncio.Task[str] | None) -> None:
        try:
            if pending is not None:
                pending.cancel()
                result, = await asyncio.gather(pending, return_exceptions=True)
                if isinstance(result, BaseException) and not isinstance(
                    result, (asyncio.CancelledError, StopAsyncIteration)
                ):
                    raise result
        finally:
            await self._events.aclose()
