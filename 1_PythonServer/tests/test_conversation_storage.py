from concurrent.futures import ThreadPoolExecutor
import subprocess
import sys
import threading
from time import sleep

from app.repositories.project import conversation_storage


def test_conversation_write_lock_queues_local_writers_before_timeout(
    tmp_path,
    monkeypatch,
):
    writer_count = 12
    start = threading.Barrier(writer_count)
    state_lock = threading.Lock()
    active_writers = 0
    max_active_writers = 0

    monkeypatch.setattr(conversation_storage, "_WRITE_LOCK_TIMEOUT_SECONDS", 0.02)

    def write(writer_id: int) -> int:
        nonlocal active_writers, max_active_writers
        start.wait()
        with conversation_storage.conversation_write_lock(tmp_path):
            with state_lock:
                active_writers += 1
                max_active_writers = max(max_active_writers, active_writers)
            sleep(0.01)
            with state_lock:
                active_writers -= 1
        return writer_id

    with ThreadPoolExecutor(max_workers=writer_count) as executor:
        completed = list(executor.map(write, range(writer_count)))

    assert sorted(completed) == list(range(writer_count))
    assert max_active_writers == 1
    assert not (tmp_path / ".write.lock").exists()


def test_conversation_write_lock_retries_windows_permission_race(
    tmp_path,
    monkeypatch,
):
    real_open = conversation_storage.os.open
    attempts = 0

    def flaky_open(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise PermissionError("simulated Windows create/delete race")
        return real_open(*args, **kwargs)

    monkeypatch.setattr(conversation_storage.os, "open", flaky_open)

    with conversation_storage.conversation_write_lock(tmp_path):
        assert (tmp_path / ".write.lock").is_file()

    assert attempts == 2
    assert not (tmp_path / ".write.lock").exists()


def test_stale_lock_owned_by_live_process_is_not_removed(tmp_path, monkeypatch):
    lock_path = tmp_path / ".write.lock"
    lock_path.write_text("1234:owner-token", encoding="ascii")
    monkeypatch.setattr(conversation_storage, "_WRITE_LOCK_STALE_AFTER_SECONDS", -1)
    monkeypatch.setattr(conversation_storage, "_process_is_running", lambda pid: pid == 1234)

    conversation_storage._remove_stale_lock(lock_path)

    assert lock_path.is_file()


def test_process_liveness_distinguishes_running_and_stopped_process():
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(10)"],
    )
    try:
        assert conversation_storage._process_is_running(process.pid) is True
    finally:
        process.terminate()
        process.wait(timeout=5)

    assert conversation_storage._process_is_running(process.pid) is False


def test_lock_release_does_not_remove_another_owner(tmp_path):
    lock_path = tmp_path / ".write.lock"
    lock_path.write_text("1234:new-owner", encoding="ascii")

    conversation_storage._remove_owned_lock(lock_path, "1234:old-owner")

    assert lock_path.read_text(encoding="ascii") == "1234:new-owner"


def test_lock_release_retries_transient_windows_permission_error(
    tmp_path,
    monkeypatch,
):
    lock_path = tmp_path / ".write.lock"
    lock_path.write_text("1234:owner", encoding="ascii")
    real_unlink = type(lock_path).unlink
    attempts = 0

    def flaky_unlink(path, *args, **kwargs):
        nonlocal attempts
        attempts += 1
        if path == lock_path and attempts == 1:
            raise PermissionError("simulated Windows delete race")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(type(lock_path), "unlink", flaky_unlink)

    conversation_storage._remove_owned_lock(lock_path, "1234:owner")

    assert attempts == 2
    assert not lock_path.exists()
