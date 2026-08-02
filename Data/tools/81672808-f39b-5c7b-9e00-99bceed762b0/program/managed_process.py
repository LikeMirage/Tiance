from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess
from threading import Thread
import time
import uuid

from child_process_control import (
    CONTROL_READY_FILENAME,
    EXECUTION_DIRECTORY_ENV,
    RECORD_FILENAME,
)
from python_runtime import (
    PythonRuntime,
    PythonRuntimeError,
    acquire_environment_lease,
    build_script_command,
    resolve_user_packages_root,
)


_PROCESS_LEASE_ENV = "TIANCE_PYTHON_PROCESS_LEASE_FILE"


@dataclass(frozen=True, slots=True)
class ManagedProcess:
    execution_id: str
    execution_directory: Path
    expected_exit_codes: tuple[int, ...]
    process: subprocess.Popen[bytes]
    run_mode: str
    script_path: Path
    stderr_log_path: Path
    stdout_log_path: Path
    workdir: Path


@dataclass(frozen=True, slots=True)
class ProcessCompletion:
    exit_code: int
    state: str
    stderr: str
    stderr_truncated: bool
    stdout: str
    stdout_truncated: bool


def default_execution_root() -> Path:
    user_packages_root = resolve_user_packages_root()
    if user_packages_root is not None:
        runtime_root = user_packages_root.parents[2]
        return runtime_root / "tool-processes" / "run_python_script"
    workspace = os.environ.get("TIANCE_WORKSPACE_ROOT") or os.getcwd()
    return (
        Path(workspace).resolve(strict=False)
        / "Data"
        / "runtime"
        / "tool-processes"
        / "run_python_script"
    )


def create_execution_directory(root: Path | None = None) -> tuple[str, Path]:
    execution_id = uuid.uuid4().hex
    execution_directory = (root or default_execution_root()) / execution_id
    try:
        execution_directory.mkdir(parents=True, exist_ok=False)
    except OSError as exc:
        raise PythonRuntimeError(
            "EXECUTION_STORAGE_FAILED",
            "无法创建后台程序运行目录。",
            {"execution_directory": str(execution_directory)},
        ) from exc
    return execution_id, execution_directory


def start_managed_script(
    *,
    args: list[str],
    execution_directory: Path,
    execution_id: str,
    expected_exit_codes: tuple[int, ...],
    run_mode: str,
    runtime: PythonRuntime,
    script_path: Path,
    stdin_text: str | None,
    workdir: Path,
) -> ManagedProcess:
    stdout_log_path = execution_directory / "stdout.log"
    stderr_log_path = execution_directory / "stderr.log"
    stdin_path = execution_directory / "stdin.txt"
    record_path = execution_directory / RECORD_FILENAME
    _write_process_record(
        record_path,
        {
            "schema_version": 1,
            "execution_id": execution_id,
            "pid": None,
            "state": "launching",
            "exit_code": None,
            "expected_exit_codes": list(expected_exit_codes),
            "run_mode": run_mode,
            "script_path": str(script_path),
            "workdir": str(workdir),
            "created_at": time.time(),
            "updated_at": time.time(),
            "stdout_log_path": str(stdout_log_path),
            "stderr_log_path": str(stderr_log_path),
        },
        strict=True,
    )
    command = build_script_command(script_path, args, runtime=runtime)
    child_lease = acquire_environment_lease()
    environment = dict(runtime.environment)
    environment[EXECUTION_DIRECTORY_ENV] = str(execution_directory)
    if child_lease.path is not None:
        environment[_PROCESS_LEASE_ENV] = str(child_lease.path)

    stdin_handle = None
    stdout_handle = None
    stderr_handle = None
    try:
        if stdin_text is not None:
            stdin_path.write_text(stdin_text, encoding="utf-8")
            stdin_handle = stdin_path.open("rb")
        stdout_handle = stdout_log_path.open("ab", buffering=0)
        stderr_handle = stderr_log_path.open("ab", buffering=0)
        process = subprocess.Popen(
            command,
            cwd=str(workdir),
            env=environment,
            stdin=stdin_handle if stdin_handle is not None else subprocess.DEVNULL,
            stdout=stdout_handle,
            stderr=stderr_handle,
            close_fds=True,
            **_detached_process_options(),
        )
    except (OSError, ValueError) as exc:
        child_lease.release()
        _update_failed_launch_record(record_path, "launch_failed")
        raise PythonRuntimeError(
            "SCRIPT_LAUNCH_FAILED",
            "无法创建 Python 子进程。",
            {"execution_directory": str(execution_directory)},
        ) from exc
    finally:
        if stdin_handle is not None:
            stdin_handle.close()
        if stdout_handle is not None:
            stdout_handle.close()
        if stderr_handle is not None:
            stderr_handle.close()

    managed = ManagedProcess(
        execution_id=execution_id,
        execution_directory=execution_directory,
        expected_exit_codes=expected_exit_codes,
        process=process,
        run_mode=run_mode,
        script_path=script_path,
        stderr_log_path=stderr_log_path,
        stdout_log_path=stdout_log_path,
        workdir=workdir,
    )
    try:
        record_process_state(managed, "spawned", strict=True)
        (execution_directory / CONTROL_READY_FILENAME).write_text(
            "ready\n",
            encoding="utf-8",
        )
    except (OSError, PythonRuntimeError) as exc:
        _terminate_spawned_process(process)
        child_lease.release()
        _update_failed_launch_record(record_path, "control_failed")
        raise PythonRuntimeError(
            "PROCESS_CONTROL_SETUP_FAILED",
            "无法建立后台进程控制通道。",
            {"execution_directory": str(execution_directory)},
        ) from exc
    return managed


def wait_for_completion(
    managed: ManagedProcess,
    *,
    max_output_chars: int,
    wait_seconds: float,
) -> ProcessCompletion | None:
    deadline = time.monotonic() + wait_seconds
    while True:
        exit_code = managed.process.poll()
        if exit_code is not None:
            stdout, stdout_truncated = _read_log(
                managed.stdout_log_path,
                max_output_chars,
            )
            stderr, stderr_truncated = _read_log(
                managed.stderr_log_path,
                max_output_chars,
            )
            recorded_state = _read_record_state(managed.execution_directory)
            state = (
                "stopped"
                if recorded_state == "stopped"
                else (
                    "completed"
                    if exit_code in managed.expected_exit_codes
                    else "failed"
                )
            )
            record_process_state(managed, state, exit_code=exit_code)
            return ProcessCompletion(
                exit_code=exit_code,
                state=state,
                stderr=stderr,
                stderr_truncated=stderr_truncated,
                stdout=stdout,
                stdout_truncated=stdout_truncated,
            )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            record_process_state(managed, "running")
            return None
        time.sleep(min(0.05, remaining))


def reap_process_in_background(managed: ManagedProcess) -> None:
    """Release the local process handle after exit without delaying the tool result."""
    Thread(
        target=_wait_without_observing,
        args=(managed.process,),
        name=f"python-process-reaper-{managed.process.pid}",
        daemon=True,
    ).start()


def discard_execution_artifacts(managed: ManagedProcess) -> bool:
    try:
        shutil.rmtree(managed.execution_directory)
    except OSError:
        return False
    return True


def record_process_state(
    managed: ManagedProcess,
    state: str,
    *,
    exit_code: int | None = None,
    strict: bool = False,
) -> None:
    record_path = managed.execution_directory / RECORD_FILENAME
    payload = _read_process_record(record_path) or {}
    payload.update(
        {
            "schema_version": 1,
            "execution_id": managed.execution_id,
            "pid": managed.process.pid,
            "state": state,
            "exit_code": exit_code,
            "expected_exit_codes": list(managed.expected_exit_codes),
            "run_mode": managed.run_mode,
            "script_path": str(managed.script_path),
            "workdir": str(managed.workdir),
            "updated_at": time.time(),
            "stdout_log_path": str(managed.stdout_log_path),
            "stderr_log_path": str(managed.stderr_log_path),
        }
    )
    _write_process_record(record_path, payload, strict=strict)


def _write_process_record(
    record_path: Path,
    payload: dict[str, object],
    *,
    strict: bool,
) -> None:
    temporary_path = record_path.parent / (
        f".{record_path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    )
    try:
        temporary_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary_path, record_path)
    except OSError as exc:
        temporary_path.unlink(missing_ok=True)
        if strict:
            raise PythonRuntimeError(
                "PROCESS_RECORD_WRITE_FAILED",
                "无法写入后台进程运行记录。",
                {"record_path": str(record_path)},
            ) from exc


def _read_process_record(record_path: Path) -> dict[str, object] | None:
    try:
        payload = json.loads(record_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _read_record_state(execution_directory: Path) -> str:
    payload = _read_process_record(execution_directory / RECORD_FILENAME)
    value = payload.get("state") if payload else None
    return value if isinstance(value, str) else ""


def _terminate_spawned_process(process: subprocess.Popen[bytes]) -> None:
    try:
        process.terminate()
        process.wait(timeout=5)
    except (OSError, subprocess.SubprocessError):
        pass


def _update_failed_launch_record(record_path: Path, state: str) -> None:
    payload = _read_process_record(record_path) or {"schema_version": 1}
    now = time.time()
    payload.update(
        {
            "state": state,
            "finished_at": now,
            "updated_at": now,
        }
    )
    _write_process_record(record_path, payload, strict=False)


def _detached_process_options() -> dict[str, object]:
    if os.name == "nt":
        creation_flags = (
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "DETACHED_PROCESS", 0)
        )
        return {"creationflags": creation_flags}
    return {"start_new_session": True}


def _read_log(path: Path, max_chars: int) -> tuple[str, bool]:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            text = handle.read(max_chars + 1)
    except OSError:
        return "", False
    if len(text) <= max_chars:
        return text, False
    return text[:max_chars] + "\n...<truncated>", True


def _wait_without_observing(process: subprocess.Popen[bytes]) -> None:
    try:
        process.wait()
    except (OSError, subprocess.SubprocessError):
        pass
