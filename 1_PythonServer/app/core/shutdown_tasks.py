"""Opt-in work that must settle before a managed desktop shutdown.

Owners choose the commit boundary. Before it, shutdown cancels work; after it,
shutdown waits for completion/rollback. This registry stores lifecycle only, not
installation results. All access is on the application's event loop.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from functools import wraps

from app.core.errors import AppError


class ShutdownTasks:
    def __init__(self) -> None:
        self._tasks: dict[asyncio.Task, bool] = {}
        self._closing = False

    def require_accepting(self) -> None:
        if self._closing:
            raise AppError(
                "软件正在退出，已停止接受新的后台操作。",
                code="application_exiting", status_code=503,
            )

    @property
    def accepting(self) -> bool:
        return not self._closing

    def track(self, task: asyncio.Task) -> None:
        self.require_accepting()
        self._tasks[task] = False
        task.add_done_callback(self._forget)

    def _forget(self, task: asyncio.Task) -> None:
        self._tasks.pop(task, None)

    def commit_started(self) -> None:
        task = asyncio.current_task()
        if task in self._tasks:
            self._tasks[task] = True

    def request(self, function: Callable) -> Callable:
        @wraps(function)
        async def run(*args, **kwargs):
            task = asyncio.current_task()
            nested = task in self._tasks
            if not nested:
                self.track(task)
            try:
                return await function(*args, **kwargs)
            except asyncio.CancelledError:
                if self._closing:
                    raise AppError(
                        "软件正在退出，本次操作已停止。",
                        code="operation_stopped", status_code=503,
                    ) from None
                raise
            finally:
                if not nested:
                    # Requests can keep their ASGI task alive after the service
                    # returns. Only the opted-in work belongs to this registry.
                    task.remove_done_callback(self._forget)
                    self._tasks.pop(task, None)
        return run

    def begin_close(self) -> int:
        if not self._closing:
            self._closing = True
            for task, committing in tuple(self._tasks.items()):
                if not committing:
                    task.cancel()
        return sum(not task.done() for task in self._tasks)

    def resume(self) -> None:
        """A failed desktop close can be retried; cancelled work stays cancelled."""
        self._closing = False

    async def close(self) -> None:
        self.begin_close()
        await asyncio.gather(*tuple(self._tasks), return_exceptions=True)


async def finish_thread(function: Callable, /, *args, **kwargs):
    """Cancellation cannot stop a Python worker thread: join it before unwinding.

In particular, a caller's finally block must not remove staging/rollback files
while this thread is still using them. Repeated cancellation also waits.
"""
    worker = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
    cancelled = False
    while not worker.done():
        try:
            await asyncio.shield(worker)
        except asyncio.CancelledError:
            cancelled = True
        except Exception:
            break
    result = worker.result()
    if cancelled:
        raise asyncio.CancelledError
    return result


shutdown_tasks = ShutdownTasks()
