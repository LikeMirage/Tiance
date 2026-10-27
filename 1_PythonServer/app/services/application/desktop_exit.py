"""Quiesce producers, then drain persistence before the shell may disappear."""
from __future__ import annotations

import asyncio
from functools import lru_cache

from app.core.shutdown_tasks import shutdown_tasks
from app.services.project.conversation_run_manager import get_conversation_run_manager
from app.services.project.conversation_background_tasks import get_conversation_background_task_registry
from app.services.project.conversation_audit import get_conversation_audit_service


class DesktopExitCoordinator:
    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None

    def begin(self) -> int:
        pending = shutdown_tasks.begin_close()
        if self._task is None:
            self._task = asyncio.create_task(self._settle(), name="desktop-exit-settlement")
        if self._task.done():
            self._task.result()  # Failed persistence must never become ready=True.
            return 0
        return pending + 1

    async def _settle(self) -> None:
        # No new producers can start after begin(). Cancel each owner once; its
        # cancellation handlers may still register the final audit writes.
        errors = []
        for owner in (get_conversation_run_manager(), get_conversation_background_task_registry(),
                      shutdown_tasks, get_conversation_audit_service()):
            try:
                await owner.close()
            except Exception as error:
                errors.append(error)
        if errors:
            raise RuntimeError("会话收尾或记录保存失败，窗口已保留，请检查后重试退出。") from errors[0]

    async def close(self) -> None:
        self.begin()
        await asyncio.shield(self._task)

    async def abandon(self) -> None:
        # A disconnected shell request must not cancel settlement or reopen
        # admission while old producers are still unwinding.
        if self._task is not None:
            try:
                await asyncio.shield(self._task)
            except Exception:
                pass
        self._task = None
        shutdown_tasks.resume()

    def start_lifecycle(self) -> None:
        self._task = None
        shutdown_tasks.resume()


@lru_cache
def get_desktop_exit_coordinator() -> DesktopExitCoordinator:
    return DesktopExitCoordinator()
