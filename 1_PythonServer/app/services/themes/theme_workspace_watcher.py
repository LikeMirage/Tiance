from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from functools import lru_cache
from pathlib import Path

from watchfiles import Change, DefaultFilter, awatch

from app.services.application.theme_workspace_reconciliation import (
    ThemeWorkspaceReconciliationService,
)
from app.services.themes.theme_catalog import THEME_MANIFEST_FILE

logger = logging.getLogger(__name__)

_RECONCILED_ROOT_FILES = frozenset(("catalog.json", "theme-settings.json"))


class ThemeWorkspaceEventBroker:
    """把主题工作区文件变化转发给当前在线的前端订阅者。"""

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
def get_theme_workspace_event_broker() -> ThemeWorkspaceEventBroker:
    return ThemeWorkspaceEventBroker()


async def watch_theme_workspace_changes(
    themes_root: str | Path,
    reconciliation_service: ThemeWorkspaceReconciliationService,
    event_broker: ThemeWorkspaceEventBroker | None = None,
) -> None:
    root = Path(themes_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    broker = event_broker or get_theme_workspace_event_broker()
    try:
        async for changes in awatch(
            root,
            watch_filter=DefaultFilter(),
            debounce=700,
            step=100,
            ignore_permission_denied=True,
        ):
            paths = theme_workspace_change_paths(root, changes)
            if not paths:
                continue
            try:
                reconciliation_service.synchronize()
                broker.publish(paths)
            except Exception:
                logger.warning(
                    "Theme workspace synchronization failed after external changes: %s",
                    ", ".join(paths),
                    exc_info=True,
                )
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.warning("Theme workspace watcher stopped unexpectedly.", exc_info=True)


def theme_workspace_change_paths(
    themes_root: str | Path,
    changes: set[tuple[Change, str]],
) -> tuple[str, ...]:
    root = Path(themes_root).resolve()
    paths: set[str] = set()
    for _change, path in changes:
        try:
            relative = Path(path).resolve().relative_to(root)
        except ValueError:
            continue
        parts = relative.parts
        if not parts or parts[0].startswith("."):
            continue
        is_theme_directory_event = len(parts) == 1 and "." not in parts[0]
        is_manifest_event = len(parts) == 2 and parts[1] == THEME_MANIFEST_FILE
        is_root_state_event = len(parts) == 1 and parts[0] in _RECONCILED_ROOT_FILES
        if is_theme_directory_event or is_manifest_event or is_root_state_event:
            paths.add(relative.as_posix())
    return tuple(sorted(paths))
