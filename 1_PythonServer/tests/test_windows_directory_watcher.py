from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import queue
import sys
import time

import pytest
from watchfiles import Change

from app.infra.projects.windows_directory_watcher import WindowsDirectoryChangeReader
from app.infra.projects.windows_directory_watch_process import _offer_event


def test_windows_directory_change_reader_parses_multiple_records(tmp_path):
    first = _record(1, "node_modules\\package\\index.js")
    second = _record(5, "src\\renamed.py")
    first = len(first).to_bytes(4, "little") + first[4:]
    reader = WindowsDirectoryChangeReader.__new__(WindowsDirectoryChangeReader)
    reader._root = Path(tmp_path)

    changes = reader._parse_changes(first + second)

    assert changes == {
        (Change.added, str(tmp_path / "node_modules\\package\\index.js")),
        (Change.added, str(tmp_path / "src\\renamed.py")),
    }


@pytest.mark.skipif(sys.platform != "win32", reason="requires the Windows file API")
def test_windows_directory_change_reader_receives_nested_changes(tmp_path):
    reader = WindowsDirectoryChangeReader(Path(tmp_path))
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            pending_read = executor.submit(reader.read)
            time.sleep(0.05)
            nested = tmp_path / "node_modules" / "package"
            nested.mkdir(parents=True)
            changed_file = nested / "index.js"
            changed_file.write_text("export {};", encoding="utf-8")
            changes = pending_read.result(timeout=3)
    finally:
        reader.close()

    changed_paths = {path for _change, path in changes}
    assert any(path.endswith("node_modules") for path in changed_paths) or any(
        path.endswith("node_modules\\package\\index.js") for path in changed_paths
    )


def test_windows_watch_process_queue_degrades_to_one_overflow_event():
    event_queue: queue.Queue = queue.Queue(maxsize=2)
    _offer_event(event_queue, ("changed", ("first",)))
    _offer_event(event_queue, ("changed", ("second",)))
    _offer_event(event_queue, ("changed", ("third",)))

    assert event_queue.qsize() == 1
    assert event_queue.get_nowait() == ("overflow", ())


def _record(action: int, name: str) -> bytes:
    encoded_name = name.encode("utf-16-le")
    body = (
        (0).to_bytes(4, "little")
        + action.to_bytes(4, "little")
        + len(encoded_name).to_bytes(4, "little")
        + encoded_name
    )
    padding = (-len(body)) % 4
    return body + (b"\x00" * padding)
