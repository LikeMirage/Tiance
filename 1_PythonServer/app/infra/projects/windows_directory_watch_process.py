from __future__ import annotations

from pathlib import Path
import queue

from app.infra.projects.windows_directory_watcher import WindowsDirectoryChangeReader


def run_windows_directory_watch_worker(root: str, event_queue) -> None:
    reader: WindowsDirectoryChangeReader | None = None
    try:
        reader = WindowsDirectoryChangeReader(Path(root))
        _offer_event(event_queue, ("ready", ()))
        while True:
            changes = reader.read()
            if changes:
                _offer_event(
                    event_queue,
                    ("changed", tuple(path for _change, path in changes)),
                )
    except BaseException as error:
        _replace_queue(event_queue, ("failed", (f"{type(error).__name__}: {error}",)))
    finally:
        if reader is not None:
            reader.close()


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
