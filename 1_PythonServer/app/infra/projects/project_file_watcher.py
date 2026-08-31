from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import aclosing
from dataclasses import dataclass
from functools import partial
import logging
import os
from pathlib import Path
import queue
import sys
from typing import Literal

import anyio
from watchfiles import Change, awatch

from app.infra.projects.project_file_names import is_internal_write_temp_path

_MAX_DETAILED_CHANGE_PATHS = 256
_WATCH_QUIET_SECONDS = 0.35
_WATCH_MAX_BATCH_SECONDS = 1.5
_WATCH_PROCESS_QUEUE_SIZE = 4
_WATCH_PROCESS_POLL_SECONDS = 0.5
# Terminate, wait, then kill and wait again. Failure to reap is an error; never
# start a replacement while the previous process is still alive.
_WATCH_PROCESS_STOP_SECONDS = 2.0
_WATCH_RETRY_DELAYS = (1.0, 5.0, 30.0)

logger = logging.getLogger(__name__)

ProjectFileWatchKind = Literal["ready", "changed", "overflow", "unavailable"]


@dataclass(frozen=True, slots=True)
class ProjectFileWatchEvent:
    kind: ProjectFileWatchKind
    paths: tuple[str, ...] = ()


async def watch_project_file_changes(
    project_root: str,
    *,
    project_id: str,
) -> AsyncIterator[ProjectFileWatchEvent]:
    root = Path(project_root).resolve()
    if sys.platform == "win32":
        async with aclosing(_watch_windows_process(root, project_id=project_id)) as source:
            async for event in source:
                yield event
        return

    yield ProjectFileWatchEvent("ready")
    try:
        source = awatch(
            root,
            watch_filter=partial(_is_external_project_change, root),
            debounce=500,
            step=100,
            ignore_permission_denied=True,
        )
        async for changes in _coalesce_changes(source):
            paths = project_file_change_paths(root, changes)
            if paths is None:
                yield ProjectFileWatchEvent("overflow")
            elif paths:
                yield ProjectFileWatchEvent("changed", tuple(paths))
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("Project file watcher failed for project %s.", project_id)
        yield ProjectFileWatchEvent("unavailable")


async def _watch_windows_process(
    root: Path,
    *,
    project_id: str,
) -> AsyncIterator[ProjectFileWatchEvent]:
    from multiprocessing import get_context

    from app.infra.projects.windows_directory_watch_process import (
        run_windows_directory_watch_worker,
    )

    retry_index = 0
    while True:
        context = get_context("spawn")
        event_queue = context.Queue(maxsize=_WATCH_PROCESS_QUEUE_SIZE)
        process = context.Process(
            target=run_windows_directory_watch_worker,
            args=(str(root), event_queue),
            name=f"tiance-file-watch-{project_id[:8]}",
            daemon=True,
        )
        process_started_at = asyncio.get_running_loop().time()
        try:
            process.start()
            while True:
                try:
                    kind, raw_paths = await asyncio.to_thread(
                        event_queue.get,
                        True,
                        _WATCH_PROCESS_POLL_SECONDS,
                    )
                except queue.Empty:
                    if process.is_alive():
                        continue
                    raise RuntimeError(f"watch process exited with code {process.exitcode}")

                if kind == "ready":
                    yield ProjectFileWatchEvent("ready")
                    continue
                if kind == "overflow":
                    yield ProjectFileWatchEvent("overflow")
                    continue
                if kind == "failed":
                    reason = raw_paths[0] if raw_paths else "unknown watcher failure"
                    raise RuntimeError(reason)
                if kind != "changed":
                    continue

                raw_path_set = set(raw_paths)
                loop = asyncio.get_running_loop()
                quiet_deadline = loop.time() + _WATCH_QUIET_SECONDS
                batch_deadline = loop.time() + _WATCH_MAX_BATCH_SECONDS
                overflowed = False
                while True:
                    timeout = min(quiet_deadline, batch_deadline) - loop.time()
                    if timeout <= 0:
                        break
                    try:
                        next_kind, next_paths = await asyncio.to_thread(
                            event_queue.get,
                            True,
                            timeout,
                        )
                    except queue.Empty:
                        break
                    if next_kind == "overflow":
                        overflowed = True
                        raw_path_set.clear()
                        break
                    if next_kind == "failed":
                        reason = next_paths[0] if next_paths else "unknown watcher failure"
                        raise RuntimeError(reason)
                    if next_kind == "changed":
                        raw_path_set.update(next_paths)
                        quiet_deadline = loop.time() + _WATCH_QUIET_SECONDS

                if overflowed:
                    yield ProjectFileWatchEvent("overflow")
                    continue
                paths = project_file_change_paths(
                    root,
                    {(Change.modified, path) for path in raw_path_set},
                )
                if paths is None:
                    yield ProjectFileWatchEvent("overflow")
                elif paths:
                    yield ProjectFileWatchEvent("changed", tuple(paths))
        except asyncio.CancelledError:
            raise
        except Exception:
            if asyncio.get_running_loop().time() - process_started_at >= 60:
                retry_index = 0
            logger.exception(
                "Isolated project file watcher failed for project %s; automatic refresh is degraded.",
                project_id,
            )
        finally:
            with anyio.CancelScope(shield=True):
                await anyio.to_thread.run_sync(_stop_watch_process, process, event_queue)

        yield ProjectFileWatchEvent("unavailable")
        delay = _WATCH_RETRY_DELAYS[min(retry_index, len(_WATCH_RETRY_DELAYS) - 1)]
        retry_index += 1
        await asyncio.sleep(delay)


def _stop_watch_process(process, event_queue) -> None:
    try:
        if process.pid is not None:
            if process.is_alive():
                process.terminate()
            process.join(timeout=_WATCH_PROCESS_STOP_SECONDS)
            if process.is_alive():
                process.kill()
                process.join(timeout=_WATCH_PROCESS_STOP_SECONDS)
            if process.is_alive():
                raise RuntimeError(f"File watcher process {process.pid} did not exit")
        process.close()
    finally:
        event_queue.close()
        event_queue.join_thread()


async def _coalesce_changes(
    source: AsyncIterator[set[tuple[Change, str]]],
) -> AsyncIterator[set[tuple[Change, str]]]:
    queue_: asyncio.Queue[set[tuple[Change, str]] | BaseException | None] = (
        asyncio.Queue(maxsize=4)
    )

    async def produce() -> None:
        cancelled = False
        try:
            async for changes in source:
                await queue_.put(changes)
        except asyncio.CancelledError:
            cancelled = True
            raise
        except BaseException as error:
            await queue_.put(error)
        finally:
            if not cancelled:
                await queue_.put(None)

    producer = asyncio.create_task(produce())
    try:
        while True:
            item = await queue_.get()
            if item is None:
                return
            if isinstance(item, BaseException):
                raise item

            pending = set(item)
            loop = asyncio.get_running_loop()
            batch_deadline = loop.time() + _WATCH_MAX_BATCH_SECONDS
            quiet_deadline = loop.time() + _WATCH_QUIET_SECONDS
            source_finished = False
            while True:
                timeout = min(batch_deadline, quiet_deadline) - loop.time()
                if timeout <= 0:
                    break
                try:
                    next_item = await asyncio.wait_for(queue_.get(), timeout)
                except TimeoutError:
                    # Give the producer one scheduling turn, then include every
                    # event already delivered at the quiet boundary.  Without
                    # this, an event whose delay elapsed during a busy loop can
                    # be split into a second batch only because the producer
                    # task had not run yet.
                    await asyncio.sleep(0)
                    while True:
                        try:
                            boundary_item = queue_.get_nowait()
                        except asyncio.QueueEmpty:
                            break
                        if boundary_item is None:
                            source_finished = True
                            break
                        if isinstance(boundary_item, BaseException):
                            raise boundary_item
                        pending.update(boundary_item)
                    break
                if next_item is None:
                    source_finished = True
                    break
                if isinstance(next_item, BaseException):
                    raise next_item
                pending.update(next_item)
                quiet_deadline = loop.time() + _WATCH_QUIET_SECONDS

            if pending:
                yield pending
            if source_finished:
                return
    finally:
        producer.cancel()
        await asyncio.gather(producer, return_exceptions=True)


def project_file_change_paths(
    project_root: str | Path,
    changes: set[tuple[Change, str]],
) -> list[str] | None:
    root = Path(project_root).resolve()
    paths: set[str] = set()
    for _change, path in changes:
        relative = _relative_project_path(root, path)
        if relative is None or not relative:
            continue
        if is_internal_write_temp_path(relative) or _is_ignored_project_watch_path(relative):
            continue
        paths.add(relative)
        if len(paths) > _MAX_DETAILED_CHANGE_PATHS:
            return None
    return sorted(paths)


def _is_external_project_change(root: Path, _change: Change, path: str) -> bool:
    return is_external_project_watch_path(root, path)


def is_external_project_watch_path(project_root: str | Path, path: str) -> bool:
    """Return whether a native file notification belongs to user project content."""
    relative = _relative_project_path(Path(project_root).resolve(), path)
    return bool(relative) and not _is_ignored_project_watch_path(relative)


def _relative_project_path(root: Path, path: str) -> str | None:
    absolute_path = os.path.abspath(path)
    try:
        relative = os.path.relpath(absolute_path, root)
    except (OSError, ValueError):
        return None
    if relative == os.curdir or relative == os.pardir:
        return None
    if relative.startswith(os.pardir + os.sep):
        return None
    return relative.replace(os.sep, "/")


def _is_ignored_project_watch_path(relative_path: str) -> bool:
    parts = relative_path.split("/")
    return parts[0] == ".Tiance" or is_internal_write_temp_path(relative_path)
