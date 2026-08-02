from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time
from typing import Callable
import uuid

from process_liveness import (
    LIVENESS_FILENAME,
    LivenessStatus,
    PidStatus,
    probe_liveness_lock,
    probe_pid,
)


EXECUTION_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
FINAL_STATES = frozenset(
    {"completed", "failed", "stopped", "launch_failed", "control_failed"}
)
ORPHANED_STATE = "orphaned"
HEARTBEAT_FRESH_SECONDS = 5.0


class ProcessRepositoryError(RuntimeError):
    def __init__(self, code: str, message: str, details: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


@dataclass(frozen=True, slots=True)
class ProcessSnapshot:
    active: bool | None
    data: dict[str, object]
    state: str


class ProcessRepository:
    def __init__(
        self,
        execution_root: Path,
        *,
        liveness_probe: Callable[[Path, str | None], LivenessStatus] = probe_liveness_lock,
        pid_probe: Callable[[object], PidStatus] = probe_pid,
    ) -> None:
        self.execution_root = execution_root.resolve(strict=False)
        self._liveness_probe = liveness_probe
        self._pid_probe = pid_probe

    def list_processes(
        self,
        *,
        limit: int,
        offset: int,
    ) -> tuple[list[ProcessSnapshot], int, int]:
        if not self.execution_root.is_dir():
            return [], 0, 0
        snapshots: list[ProcessSnapshot] = []
        skipped = 0
        for directory in self.execution_root.iterdir():
            if not directory.is_dir() or not EXECUTION_ID_PATTERN.fullmatch(directory.name):
                continue
            try:
                snapshots.append(self.get_process(directory.name))
            except ProcessRepositoryError:
                skipped += 1
        snapshots.sort(
            key=lambda item: _number(item.data.get("created_at")) or 0.0,
            reverse=True,
        )
        total = len(snapshots)
        return snapshots[offset : offset + limit], total, skipped

    def get_process(self, execution_id: str) -> ProcessSnapshot:
        execution_directory = self._execution_directory(execution_id)
        record_path = execution_directory / "execution.json"
        if not record_path.is_file():
            raise ProcessRepositoryError(
                "PROCESS_NOT_FOUND",
                "未找到指定的 Python 后台进程记录。",
                {"execution_id": execution_id},
            )
        payload = _read_json_object(record_path)
        if payload.get("execution_id") != execution_id:
            raise ProcessRepositoryError(
                "PROCESS_RECORD_INVALID",
                "Python 后台进程记录与执行目录不一致。",
                {"execution_id": execution_id, "record_path": str(record_path)},
            )
        return self._snapshot(execution_directory, payload)

    def read_logs(
        self,
        execution_id: str,
        *,
        stream: str,
        tail_chars: int,
    ) -> dict[str, object]:
        snapshot = self.get_process(execution_id)
        execution_directory = self._execution_directory(execution_id)
        logs: dict[str, object] = {}
        selected_streams = ("stdout", "stderr") if stream == "both" else (stream,)
        for name in selected_streams:
            path = execution_directory / f"{name}.log"
            text, truncated = _read_text_tail(path, tail_chars)
            logs[name] = {
                "path": str(path),
                "text": text,
                "truncated": truncated,
            }
        return {"process": snapshot.data, "logs": logs}

    def request_stop(self, execution_id: str, *, timeout_seconds: int) -> ProcessSnapshot:
        snapshot = self.get_process(execution_id)
        if snapshot.state in FINAL_STATES or snapshot.state == ORPHANED_STATE:
            return snapshot
        execution_directory = self._execution_directory(execution_id)
        request_path = execution_directory / "stop.request"
        _write_json_atomic(
            request_path,
            {"schema_version": 1, "requested_at": time.time()},
        )
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            time.sleep(0.1)
            snapshot = self.get_process(execution_id)
            if snapshot.state in FINAL_STATES:
                return snapshot
        raise ProcessRepositoryError(
            "STOP_NOT_CONFIRMED",
            "停止请求已发送，但目标进程未在规定时间内确认结束。",
            {
                "execution_id": execution_id,
                "timeout_seconds": timeout_seconds,
                "process": snapshot.data,
            },
        )

    def cleanup(self, execution_id: str) -> Path:
        snapshot = self.get_process(execution_id)
        if snapshot.state not in FINAL_STATES and snapshot.state != ORPHANED_STATE:
            raise ProcessRepositoryError(
                "PROCESS_NOT_FINISHED",
                "只能清理已经结束或确认失联的 Python 后台进程记录。",
                {"execution_id": execution_id, "state": snapshot.state},
            )
        if snapshot.data.get("liveness_status") == "held":
            raise ProcessRepositoryError(
                "PROCESS_STILL_ACTIVE",
                "进程仍持有存活锁，不能清理记录。",
                {"execution_id": execution_id, "state": snapshot.state},
            )
        execution_directory = self._execution_directory(execution_id)
        try:
            shutil.rmtree(execution_directory)
        except OSError as exc:
            raise ProcessRepositoryError(
                "PROCESS_CLEANUP_FAILED",
                "无法清理 Python 后台进程记录。",
                {"execution_id": execution_id},
            ) from exc
        return execution_directory

    def _execution_directory(self, execution_id: str) -> Path:
        if not EXECUTION_ID_PATTERN.fullmatch(execution_id):
            raise ProcessRepositoryError(
                "INVALID_EXECUTION_ID",
                "execution_id 必须是 32 位小写十六进制字符串。",
            )
        directory = (self.execution_root / execution_id).resolve(strict=False)
        try:
            directory.relative_to(self.execution_root)
        except ValueError as exc:
            raise ProcessRepositoryError(
                "INVALID_EXECUTION_ID",
                "execution_id 越出进程记录目录。",
            ) from exc
        return directory

    def _snapshot(
        self,
        execution_directory: Path,
        payload: dict[str, object],
    ) -> ProcessSnapshot:
        now = time.time()
        recorded_state = _string(payload.get("state")) or "unknown"
        heartbeat_at = _number(payload.get("heartbeat_at"))
        updated_at = _number(payload.get("updated_at"))
        heartbeat_age = max(0.0, now - heartbeat_at) if heartbeat_at else None
        liveness_protocol = _string(payload.get("liveness_protocol"))
        liveness_status = self._liveness_probe(
            execution_directory / LIVENESS_FILENAME,
            liveness_protocol,
        )
        pid_status = self._pid_probe(payload.get("pid"))
        orphaned_reason: str | None = None
        if recorded_state in FINAL_STATES:
            state, active = recorded_state, False
        elif heartbeat_age is not None and heartbeat_age <= HEARTBEAT_FRESH_SECONDS:
            state, active = "running", True
        elif liveness_status == "held":
            state, active = "running", True
        elif liveness_status == "released":
            state, active = ORPHANED_STATE, False
            orphaned_reason = "liveness_lock_released"
        elif pid_status == "absent":
            state, active = ORPHANED_STATE, False
            orphaned_reason = "pid_not_found"
        elif recorded_state in {"launching", "spawned"} and updated_at:
            if now - updated_at <= HEARTBEAT_FRESH_SECONDS:
                state, active = "starting", True
            else:
                state, active = "unknown", None
        else:
            state, active = "unknown", None
        record_updated_at = next(
            (
                value
                for value in (
                    updated_at,
                    heartbeat_at,
                    _number(payload.get("finished_at")),
                    _number(payload.get("created_at")),
                )
                if value is not None
            ),
            now,
        )
        data = {
            "execution_id": payload.get("execution_id"),
            "pid": payload.get("pid"),
            "state": state,
            "recorded_state": recorded_state,
            "active": active,
            "orphaned": state == ORPHANED_STATE,
            "orphaned_reason": orphaned_reason,
            "liveness_status": liveness_status,
            "pid_status": pid_status,
            "run_mode": payload.get("run_mode"),
            "exit_code": payload.get("exit_code"),
            "expected_exit_codes": _expected_exit_codes(
                payload.get("expected_exit_codes")
            ),
            "script_path": payload.get("script_path"),
            "workdir": payload.get("workdir"),
            "created_at": payload.get("created_at"),
            "started_at": payload.get("started_at"),
            "finished_at": payload.get("finished_at"),
            "heartbeat_at": heartbeat_at,
            "heartbeat_age_seconds": round(heartbeat_age, 3) if heartbeat_age is not None else None,
            "updated_at": updated_at,
            "record_age_seconds": round(max(0.0, now - record_updated_at), 3),
            "execution_directory": str(execution_directory),
            "record_path": str(execution_directory / "execution.json"),
            "stdout_log_path": str(execution_directory / "stdout.log"),
            "stderr_log_path": str(execution_directory / "stderr.log"),
        }
        return ProcessSnapshot(active=active, data=data, state=state)


def default_execution_root() -> Path:
    executable = Path(sys.executable).resolve(strict=False)
    if executable.parent.name == "py313" and executable.parent.parent.name == "python":
        runtime_root = executable.parents[2]
        if runtime_root.name == "runtime":
            return runtime_root / "tool-processes" / "run_python_script"
    workspace = os.environ.get("TIANCE_WORKSPACE_ROOT") or os.getcwd()
    return Path(workspace).resolve(strict=False) / "Data/runtime/tool-processes/run_python_script"


def _read_json_object(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProcessRepositoryError(
            "PROCESS_RECORD_INVALID",
            "Python 后台进程记录无法读取。",
            {"record_path": str(path)},
        ) from exc
    if not isinstance(payload, dict):
        raise ProcessRepositoryError(
            "PROCESS_RECORD_INVALID",
            "Python 后台进程记录不是 JSON 对象。",
            {"record_path": str(path)},
        )
    return payload


def _write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    temporary_path = path.parent / f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    try:
        temporary_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary_path, path)
    except OSError as exc:
        temporary_path.unlink(missing_ok=True)
        raise ProcessRepositoryError(
            "STOP_REQUEST_FAILED",
            "无法写入 Python 后台进程停止请求。",
            {"request_path": str(path)},
        ) from exc


def _read_text_tail(path: Path, max_chars: int) -> tuple[str, bool]:
    if not path.is_file():
        return "", False
    max_bytes = max_chars * 4
    try:
        with path.open("rb") as handle:
            size = handle.seek(0, os.SEEK_END)
            handle.seek(max(0, size - max_bytes))
            text = handle.read().decode("utf-8", errors="replace")
    except OSError as exc:
        raise ProcessRepositoryError(
            "PROCESS_LOG_READ_FAILED",
            "无法读取 Python 后台进程日志。",
            {"log_path": str(path)},
        ) from exc
    truncated = size > max_bytes or len(text) > max_chars
    return text[-max_chars:], truncated


def _string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _expected_exit_codes(value: object) -> list[int]:
    if not isinstance(value, list):
        return [0]
    codes = [
        item
        for item in value
        if isinstance(item, int) and not isinstance(item, bool)
    ]
    return codes or [0]
