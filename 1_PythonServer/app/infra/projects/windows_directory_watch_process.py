from __future__ import annotations

from pathlib import Path
import queue

from app.infra.projects.windows_directory_watcher import WindowsDirectoryChangeReader
from app.infra.projects.project_file_watcher import is_external_project_watch_path


def run_windows_directory_watch_worker(root: str, event_queue) -> None:
    reader: WindowsDirectoryChangeReader | None = None
    root_path = Path(root)
    try:
        reader = WindowsDirectoryChangeReader(root_path)
        _offer_event(event_queue, ("ready", ()))
        while True:
            changes = reader.read()
            external_paths = _external_change_paths(root_path, changes)
            if external_paths:
                _offer_event(
                    event_queue,
                    ("changed", external_paths),
                )
    except BaseException as error:
        _replace_queue(event_queue, ("failed", (f"{type(error).__name__}: {error}",)))
    finally:
        if reader is not None:
            reader.close()


def _external_change_paths(root: Path, changes) -> tuple[str, ...]:
    return tuple(
        path
        for _change, path in changes
        if is_external_project_watch_path(root, path)
    )


def _offer_event(event_queue, event: tuple[str, tuple[str, ...]]) -> None:
    try:
        event_queue.put_nowait(event)
    except queue.Full:
        _replace_queue(event_queue, ("overflow", ()))


def _replace_queue(event_queue, event: tuple[str, tuple[str, ...]]) -> None:
    while True:
        try:
            event_queue.get_nowait()
        except queue.Empty:
            break
    try:
        event_queue.put_nowait(event)
    except queue.Full:
        pass
