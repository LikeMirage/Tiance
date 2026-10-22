from types import SimpleNamespace

import pytest
from watchfiles import Change

from app.infra.projects import windows_directory_watch_process as worker
from app.infra.projects import windows_directory_watcher as watcher


@pytest.mark.parametrize("has_entries", [False, True])
def test_zero_byte_notifications_request_rescan_even_when_folder_is_empty(tmp_path, has_entries):
    if has_entries:
        (tmp_path / "remaining").mkdir()
    reader = watcher.WindowsDirectoryChangeReader.__new__(watcher.WindowsDirectoryChangeReader)
    reader._root = tmp_path
    reader._handle = 1
    reader._closed = False
    reader._kernel32 = SimpleNamespace(ReadDirectoryChangesW=lambda *_: True)
    with pytest.raises(watcher.WindowsDirectoryOverflowError):
        reader.read()
    reader._closed = True
    assert reader.read() == set()


def test_notify_enum_dir_error_also_requests_rescan(tmp_path, monkeypatch):
    reader = watcher.WindowsDirectoryChangeReader.__new__(watcher.WindowsDirectoryChangeReader)
    reader._root = tmp_path
    reader._handle = 1
    reader._closed = False
    reader._kernel32 = SimpleNamespace(ReadDirectoryChangesW=lambda *_: False)
    monkeypatch.setattr(watcher.ctypes, "get_last_error", lambda: 1022)
    with pytest.raises(watcher.WindowsDirectoryOverflowError):
        reader.read()
    reader._closed = True
    assert reader.read() == set()


def test_worker_forwards_overflow_and_continues_watching(tmp_path, monkeypatch):
    events = []
    class Reader:
        reads = 0
        closed = False

        def read(self):
            self.reads += 1
            if self.reads == 1:
                raise watcher.WindowsDirectoryOverflowError
            if self.reads == 2:
                return {(Change.modified, str(tmp_path / "new.txt"))}
            raise RuntimeError("stop fake reader")

        def close(self):
            self.closed = True

    reader = Reader()
    monkeypatch.setattr(worker, "WindowsDirectoryChangeReader", lambda _: reader)
    monkeypatch.setattr(worker, "_offer_event", lambda _, event: events.append(event))
    monkeypatch.setattr(worker, "_replace_queue", lambda _, event: events.append(event))
    worker.run_windows_directory_watch_worker(str(tmp_path), object())
    assert events[:3] == [("ready", ()), ("overflow", ()), ("changed", (str(tmp_path / "new.txt"),))]
    assert events[-1][0] == "failed"
    assert reader.closed
