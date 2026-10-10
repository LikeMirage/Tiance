"""Persist runtime notices at model-response boundaries, independently of tool runs.

All access runs on the backend event loop. Writers may use to_thread for storage.
Only active conversation runs retain a buffer; no conversation data is rewritten.
"""
import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field

from app.domain.project.project_conversation import ProjectConversationMessage

NoticeWriter = Callable[[], Awaitable[ProjectConversationMessage | None]]
logger = logging.getLogger(__name__)


@dataclass
class _NoticeBuffer:
    streaming: bool = False
    pending: list[NoticeWriter] = field(default_factory=list)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    ready: asyncio.Queue[ProjectConversationMessage] = field(default_factory=asyncio.Queue)


class ConversationNotificationBuffer:
    def __init__(self) -> None:
        self._sessions: dict[tuple[str, str], _NoticeBuffer] = {}

    def open(self, project_id: str | None, session_id: str | None) -> None:
        if project_id and session_id:
            self._sessions.setdefault((project_id, session_id), _NoticeBuffer())

    async def start_response(self, project_id: str | None, session_id: str | None) -> None:
        self.open(project_id, session_id)
        state = self._sessions.get((project_id, session_id))
        if state is not None:
            async with state.lock:
                state.streaming = True

    async def submit(self, project_id: str, session_id: str, writer: NoticeWriter) -> ProjectConversationMessage | None:
        state = self._sessions.get((project_id, session_id))
        if state is None:
            return await writer()
        async with state.lock:
            if state.streaming:
                state.pending.append(writer)
                return None
            message = await writer()
            if message is not None:
                state.ready.put_nowait(message)
            return message

    async def finish_response(self, project_id: str | None, session_id: str | None) -> list[ProjectConversationMessage]:
        state = self._sessions.get((project_id, session_id))
        if state is None:
            return []
        async with state.lock:
            state.streaming = False
            pending, state.pending = state.pending, []
            messages = []
            for writer in pending:
                try:
                    message = await writer()
                except Exception:
                    logger.exception("Failed to persist a queued conversation notice.")
                    continue
                if message is not None:
                    messages.append(message)
            return messages

    async def close(self, project_id: str | None, session_id: str | None) -> None:
        await self.finish_response(project_id, session_id)
        self._sessions.pop((project_id, session_id), None)

    async def with_notifications(self, project_id: str | None, session_id: str | None, events: AsyncIterator):
        """Forward independent tool-phase notices without polling the whole history."""
        state = self._sessions.get((project_id, session_id))
        if state is None:
            async for event in events:
                yield event
            return
        iterator = events.__aiter__()
        next_event = None
        next_notice = None
        try:
            while True:
                if next_event is None:
                    next_event = asyncio.create_task(anext(iterator))
                if next_notice is None:
                    next_notice = asyncio.create_task(state.ready.get())
                ready, _ = await asyncio.wait((next_event, next_notice), return_when=asyncio.FIRST_COMPLETED)
                if next_notice in ready:
                    notice = next_notice.result()
                    next_notice = None
                    yield notice
                if next_event in ready:
                    event_task, next_event = next_event, None
                    try:
                        event = event_task.result()
                    except StopAsyncIteration:
                        while not state.ready.empty():
                            yield state.ready.get_nowait()
                        return
                    yield event
        finally:
            tasks = [task for task in (next_event, next_notice) if task is not None]
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await iterator.aclose()


conversation_notifications = ConversationNotificationBuffer()
