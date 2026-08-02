from __future__ import annotations

import json
import os
from pathlib import Path
from threading import Event, Lock, Thread, current_thread
import time
import uuid

from process_liveness import (
    LIVENESS_FILENAME,
    LIVENESS_PROTOCOL,
    ProcessLivenessLock,
)


EXECUTION_DIRECTORY_ENV = "TIANCE_PYTHON_EXECUTION_DIRECTORY"
CONTROL_READY_FILENAME = "control.ready"
STOP_REQUEST_FILENAME = "stop.request"
RECORD_FILENAME = "execution.json"
HEARTBEAT_INTERVAL_SECONDS = 1.0
STARTUP_WAIT_SECONDS = 5.0


class ChildProcessControl:
    def __init__(self, execution_directory: Path | None, lease_file: Path | None) -> None:
        self._execution_directory = execution_directory
        self._lease_file = lease_file
        self._record_lock = Lock()
        self._stop_event = Event()
        self._watcher: Thread | None = None
        self._liveness_lock: ProcessLivenessLock | None = None

    @classmethod
    def from_environment(cls, lease_file: str) -> "ChildProcessControl":
        raw_directory = os.environ.pop(EXECUTION_DIRECTORY_ENV, "").strip()
        execution_directory = (
            Path(raw_directory).resolve(strict=False) if raw_directory else None
        )
        lease_path = Path(lease_file) if lease_file else None
        return cls(execution_directory, lease_path)

    def start(self) -> None:
        if self._execution_directory is None:
            return
        ready_path = self._execution_directory / CONTROL_READY_FILENAME
        deadline = time.monotonic() + STARTUP_WAIT_SECONDS
        while not ready_path.is_file():
            if time.monotonic() >= deadline:
                raise RuntimeError("后台进程控制通道未就绪。")
            time.sleep(0.02)
        try:
            self._liveness_lock = ProcessLivenessLock.acquire(
                self._execution_directory / LIVENESS_FILENAME
            )
        except OSError as exc:
            raise RuntimeError("无法建立后台进程存活标识。") from exc
        now = time.time()
        if not self._update_record(
            state="running",
            pid=os.getpid(),
            started_at=now,
            heartbeat_at=now,
            liveness_protocol=LIVENESS_PROTOCOL,
        ):
            self._release_liveness_lock()
            raise RuntimeError("无法更新后台进程运行记录。")
        self._watcher = Thread(
            target=self._watch,
            name=f"tiance-process-control-{os.getpid()}",
            daemon=True,
        )
        self._watcher.start()

    def finish(self, exit_code: int) -> None:
        self._stop_event.set()
        if self._watcher is not None and self._watcher is not current_thread():
            self._watcher.join(timeout=HEARTBEAT_INTERVAL_SECONDS + 0.5)
        if self._execution_directory is not None:
            now = time.time()
            expected_exit_codes = self._read_expected_exit_codes()
            self._update_record(
                state="completed" if exit_code in expected_exit_codes else "failed",
                exit_code=exit_code,
                finished_at=now,
                heartbeat_at=now,
            )
        self._release_liveness_lock()
        self._release_lease()

    def _read_expected_exit_codes(self) -> tuple[int, ...]:
        if self._execution_directory is None:
            return (0,)
        payload = _read_record(self._execution_directory / RECORD_FILENAME)
        raw_codes = payload.get("expected_exit_codes") if payload else None
        if not isinstance(raw_codes, list):
            return (0,)
        codes = tuple(
            item
            for item in raw_codes
            if isinstance(item, int) and not isinstance(item, bool)
        )
        return codes or (0,)

    def _watch(self) -> None:
        assert self._execution_directory is not None
        stop_request_path = self._execution_directory / STOP_REQUEST_FILENAME
        while not self._stop_event.is_set():
            if stop_request_path.is_file():
                now = time.time()
                self._update_record(
                    state="stopped",
                    exit_code=143,
                    stop_requested_at=_file_timestamp(stop_request_path, now),
                    finished_at=now,
                    heartbeat_at=now,
                )
                self._release_liveness_lock()
                self._release_lease()
                os._exit(143)
            if self._stop_event.wait(HEARTBEAT_INTERVAL_SECONDS):
                break
            self._update_record(state="running", heartbeat_at=time.time())

    def _update_record(self, **changes: object) -> bool:
        if self._execution_directory is None:
            return True
        record_path = self._execution_directory / RECORD_FILENAME
        with self._record_lock:
            payload = _read_record(record_path)
            if payload is None:
                return False
            payload.update(changes)
            payload["updated_at"] = time.time()
            try:
                _write_record(record_path, payload)
            except OSError:
                return False
        return True

    def _release_lease(self) -> None:
        lease_file = self._lease_file
        if lease_file is None:
            return
        try:
            lease_file.unlink(missing_ok=True)
        except OSError:
            pass
        self._lease_file = None

    def _release_liveness_lock(self) -> None:
        liveness_lock = self._liveness_lock
        if liveness_lock is None:
            return
        liveness_lock.release()
        self._liveness_lock = None


def _read_record(path: Path) -> dict[str, object] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _write_record(path: Path, payload: dict[str, object]) -> None:
    temporary_path = path.parent / f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    temporary_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary_path, path)


def _file_timestamp(path: Path, default: float) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return default
