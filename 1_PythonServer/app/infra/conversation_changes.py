"""Bounded, process-local invalidations emitted only after a database commit.

The database remains authoritative. Subscribers register before reading a snapshot
and reconcile on reconnect; this channel never retains message bodies.
"""
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from threading import Lock


class ConversationChanges:
    def __init__(self) -> None:
        self._lock = Lock()
        self._subscribers: dict[Path, set[tuple[asyncio.AbstractEventLoop, asyncio.Queue]]] = {}

    @asynccontextmanager
    async def subscribe(self, database_path: Path):
        key = database_path.resolve()
        queue: asyncio.Queue[None] = asyncio.Queue(maxsize=1)
        subscriber = (asyncio.get_running_loop(), queue)
        with self._lock:
            self._subscribers.setdefault(key, set()).add(subscriber)
        try:
            yield queue
        finally:
            with self._lock:
                subscribers = self._subscribers.get(key)
                if subscribers is not None:
                    subscribers.discard(subscriber)
                    if not subscribers:
                        self._subscribers.pop(key, None)

    def publish(self, database_path: Path) -> None:
        with self._lock:
            subscribers = tuple(self._subscribers.get(database_path.resolve(), ()))
        for loop, queue in subscribers:
            try:
                loop.call_soon_threadsafe(self._offer, queue)
            except RuntimeError:
                pass  # A subscriber's event loop has already shut down.

    @staticmethod
    def _offer(queue: asyncio.Queue) -> None:
        if queue.empty():
            queue.put_nowait(None)


conversation_changes = ConversationChanges()
