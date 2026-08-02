from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from functools import lru_cache
from typing import Any


_ConversationTaskKey = tuple[str, str]


class ConversationBackgroundTaskRegistry:
    """Tracks post-response tasks so conversation deletion can stop them first."""

    def __init__(self) -> None:
        self._tasks: dict[_ConversationTaskKey, set[asyncio.Task[Any]]] = {}

    def create_task(
        self,
        project_id: str,
        session_id: str,
        coroutine: Coroutine[Any, Any, Any],
        *,
        name: str,
    ) -> asyncio.Task[Any]:
        task = asyncio.create_task(coroutine, name=name)
        key = (project_id, session_id)
        self._tasks.setdefault(key, set()).add(task)
        task.add_done_callback(lambda completed: self._discard(key, completed))
        return task

    async def cancel_session(self, project_id: str, session_id: str) -> None:
        await self._cancel_tasks(tuple(self._tasks.get((project_id, session_id), ())))

    async def close(self) -> None:
        tasks = tuple(
            task
            for session_tasks in self._tasks.values()
            for task in session_tasks
        )
        await self._cancel_tasks(tasks)

    def _discard(
        self,
        key: _ConversationTaskKey,
        task: asyncio.Task[Any],
    ) -> None:
        session_tasks = self._tasks.get(key)
        if session_tasks is None:
            return
        session_tasks.discard(task)
        if not session_tasks:
            self._tasks.pop(key, None)

    async def _cancel_tasks(self, tasks: tuple[asyncio.Task[Any], ...]) -> None:
        active_tasks = tuple(task for task in tasks if not task.done())
        for task in active_tasks:
            task.cancel()
        if active_tasks:
            await asyncio.gather(*active_tasks, return_exceptions=True)


@lru_cache
def get_conversation_background_task_registry() -> ConversationBackgroundTaskRegistry:
    return ConversationBackgroundTaskRegistry()
