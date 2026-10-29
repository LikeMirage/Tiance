from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from functools import lru_cache
import logging
from pathlib import Path

from watchfiles import Change, DefaultFilter, awatch

from app.core.shutdown_tasks import finish_thread, shutdown_tasks
from app.infra.projects import PROJECT_IDENTITY_RELATIVE_PATH
from app.services.application.project_workspace_reconciliation import (
    ProjectWorkspaceReconciliationService,
)

logger = logging.getLogger(__name__)


class ProjectWorkspaceEventBroker:
    """Publish ordinary project catalog changes to connected frontends."""

    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[tuple[str, ...]]] = set()

    def publish(self, paths: tuple[str, ...]) -> None:
        if not paths:
            return
        for queue in tuple(self._subscribers):
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            queue.put_nowait(paths)

    async def subscribe(self) -> AsyncIterator[tuple[str, ...]]:
        queue: asyncio.Queue[tuple[str, ...]] = asyncio.Queue(maxsize=1)
        self._subscribers.add(queue)
        try:
            while True:
                yield await queue.get()
        finally:
            self._subscribers.discard(queue)


@lru_cache
def get_project_workspace_event_broker() -> ProjectWorkspaceEventBroker:
    return ProjectWorkspaceEventBroker()


async def watch_project_workspace_changes(
    projects_root: str | Path,
    reconciliation_service: ProjectWorkspaceReconciliationService,
    event_broker: ProjectWorkspaceEventBroker | None = None,
) -> None:
    root = Path(projects_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    broker = event_broker or get_project_workspace_event_broker()
    try:
        async for changes in awatch(
            root,
            watch_filter=DefaultFilter(),
            debounce=700,
            step=100,
            ignore_permission_denied=True,
        ):
            paths = project_workspace_change_paths(root, changes)
            if not paths:
                continue
            try:
                await _synchronize_workspace(reconciliation_service)
                broker.publish(paths)
            except Exception:
                logger.warning(
                    "Project workspace synchronization failed after external changes: %s",
                    ", ".join(paths),
                    exc_info=True,
                )
                # A worker failure must not swallow cancellation of its owner.
                if asyncio.current_task().cancelling():
                    raise asyncio.CancelledError
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.warning("Project workspace watcher stopped unexpectedly.", exc_info=True)


async def _synchronize_workspace(
    reconciliation_service: ProjectWorkspaceReconciliationService,
) -> None:
    async def synchronize_once() -> None:
        # Reconciliation may write identities and catalog entries immediately.
        shutdown_tasks.commit_started()
        await finish_thread(reconciliation_service.synchronize)

    while True:
        # Keep this batch if a failed/cancelled desktop exit resumes the app.
        # Lifespan cancellation still stops the watcher while it is waiting.
        while not shutdown_tasks.accepting:
            await asyncio.sleep(0.1)

        # Track only this finite batch, not the lifetime of the watcher. There
        # is no await between admission and registration on the event loop.
        task = asyncio.create_task(synchronize_once(), name="project-workspace-sync")
        shutdown_tasks.track(task)
        try:
            await task
        except asyncio.CancelledError:
            if asyncio.current_task().cancelling():
                raise
            # Shutdown can cancel an admitted batch before its worker starts.
            # Retain it for resume instead of permanently losing the watcher.
            continue
        return


def project_workspace_change_paths(
    projects_root: str | Path,
    changes: set[tuple[Change, str]],
) -> tuple[str, ...]:
    root = Path(projects_root).resolve()
    paths: set[str] = set()
    identity_parts = PROJECT_IDENTITY_RELATIVE_PATH.parts
    for _change, path in changes:
        try:
            relative = Path(path).resolve().relative_to(root)
        except ValueError:
            continue
        parts = relative.parts
        if not parts or parts[0].startswith("."):
            continue
        is_project_directory_event = len(parts) == 1
        is_catalog_event = len(parts) == 1 and parts[0] == "catalog.json"
        is_identity_event = (
            len(parts) == 1 + len(identity_parts)
            and parts[1:] == identity_parts
        )
        if is_project_directory_event or is_catalog_event or is_identity_event:
            paths.add(relative.as_posix())
    return tuple(sorted(paths))
