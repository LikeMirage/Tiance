"""Shared read jobs, isolated capacity, and cancellation tied to their readers."""
import asyncio
from dataclasses import dataclass, field
from threading import Event
from typing import Callable

import anyio
from fastapi import Request
from fastapi.responses import JSONResponse

from app.core.errors import AppError
from app.core.shutdown_tasks import finish_commit, shutdown_tasks
from app.infra.file_workspace.content_scan import content_snapshot


@dataclass
class _Scan:
    task: asyncio.Task | None = None
    cancelled: Event = field(default_factory=Event)
    readers: int = 0


class FileScanJobs:
    def __init__(self):
        self._jobs: dict[tuple, _Scan] = {}
        # Infrastructure concurrency only; no file count or document size limit.
        self._capacity = anyio.CapacityLimiter(2)

    async def read(self, key: tuple, operation: Callable[[Event], object]):
        job = self._jobs.get(key)
        if job is not None and job.cancelled.is_set():
            # Never overlap a retiring scan with its replacement.
            await asyncio.gather(asyncio.shield(job.task), return_exceptions=True)
            return await self.read(key, operation)
        if job is None:
            job = _Scan()
            async def run():
                try:
                    def work():
                        if job.cancelled.is_set():
                            return None
                        return operation(job.cancelled)
                    return await anyio.to_thread.run_sync(work, limiter=self._capacity)
                finally:
                    if self._jobs.get(key) is job:
                        self._jobs.pop(key, None)
            job.task = asyncio.create_task(run())
            self._jobs[key] = job
        job.readers += 1
        try:
            return await asyncio.shield(job.task)
        finally:
            job.readers -= 1
            if not job.readers and not job.task.done():
                job.cancelled.set()
                # Keep capacity owned until the actual worker has stopped.
                await finish_commit(asyncio.gather(job.task, return_exceptions=True))


scan_jobs = FileScanJobs()


@shutdown_tasks.request
async def read_content_snapshot(request: Request, project_id: str, root: str,
                                paths: tuple[str, ...] | None = None) -> JSONResponse:
    def work(cancelled):
        snapshot = content_snapshot(root, paths=paths, cancelled=cancelled)
        # Encode large results off the event loop as part of the owned scan job.
        return JSONResponse({'project_id': project_id,
            'items': [{'name': item.name, 'path': item.path, 'mtime_ms': item.mtime_ms}
                      for item in snapshot.items],
            'unreadable_paths': list(snapshot.unreadable_paths)})

    async def disconnected():
        while not await request.is_disconnected():
            await asyncio.sleep(.1)

    worker = asyncio.create_task(scan_jobs.read((root, project_id, paths), work))
    monitor = asyncio.create_task(disconnected())
    try:
        done, _ = await asyncio.wait((worker, monitor), return_when=asyncio.FIRST_COMPLETED)
        if worker in done:
            return worker.result()
        raise AppError('文件扫描请求已取消。', code='file_scan_cancelled', status_code=499)
    finally:
        monitor.cancel()
        worker.cancel()
        await finish_commit(asyncio.gather(worker, monitor, return_exceptions=True))
