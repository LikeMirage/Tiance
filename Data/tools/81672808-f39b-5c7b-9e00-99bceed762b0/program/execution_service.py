from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys
import tempfile
from typing import Literal

from managed_process import (
    ManagedProcess,
    create_execution_directory,
    discard_execution_artifacts,
    reap_process_in_background,
    start_managed_script,
    wait_for_completion,
)
from python_runtime import PythonRuntime, PythonRuntimeError, run_script


RunMode = Literal["wait", "detached", "auto_detach"]
RUN_MODES: frozenset[str] = frozenset({"wait", "detached", "auto_detach"})
DEFAULT_RUN_MODE: RunMode = "wait"
DEFAULT_WAIT_TIMEOUT_SECONDS = 60
DEFAULT_DETACH_AFTER_SECONDS = 10


@dataclass(frozen=True, slots=True)
class ScriptSource:
    script_path: Path | None
    script_text: str | None
    script_filename: str


@dataclass(frozen=True, slots=True)
class ExecutionRequest:
    args: list[str]
    detach_after_seconds: int
    expected_exit_codes: tuple[int, ...]
    max_output_chars: int
    run_mode: RunMode
    runtime: PythonRuntime
    source: ScriptSource
    stdin_text: str | None
    timeout_seconds: int
    workdir: Path


@dataclass(frozen=True, slots=True)
class ExecutionOutcome:
    command: tuple[str, ...]
    detach_after_seconds: int | None
    execution_directory: Path | None
    execution_id: str | None
    exit_code: int | None
    launch_status: str
    pid: int | None
    process_state: str
    run_mode: RunMode
    source: dict[str, str]
    stderr: str
    stderr_log_path: Path | None
    stderr_truncated: bool
    stdout: str
    stdout_log_path: Path | None
    stdout_truncated: bool
    still_running: bool | None
    timed_out: bool
    timeout_seconds: int | None


def execute(request: ExecutionRequest) -> ExecutionOutcome:
    if request.run_mode == "wait":
        return _execute_wait(request)
    return _execute_managed(request)


def _execute_wait(request: ExecutionRequest) -> ExecutionOutcome:
    if request.source.script_path is not None:
        return _run_wait_script(
            request,
            request.source.script_path,
            {"type": "file", "script_path": str(request.source.script_path)},
        )

    try:
        with tempfile.TemporaryDirectory(prefix="tiance_python_") as temp_dir:
            script_path = Path(temp_dir) / request.source.script_filename
            script_path.write_text(request.source.script_text or "", encoding="utf-8")
            return _run_wait_script(
                request,
                script_path,
                {"type": "inline", "script_filename": request.source.script_filename},
            )
    except OSError as exc:
        raise PythonRuntimeError(
            "SCRIPT_STORAGE_FAILED",
            "无法保存待执行的 Python 脚本。",
        ) from exc


def _run_wait_script(
    request: ExecutionRequest,
    script_path: Path,
    source_details: dict[str, str],
) -> ExecutionOutcome:
    completed = run_script(
        script_path,
        request.args,
        stdin_text=request.stdin_text,
        workdir=request.workdir,
        runtime=request.runtime,
        timeout=request.timeout_seconds,
    )
    stdout, stdout_truncated = truncate_text(completed.stdout, request.max_output_chars)
    stderr, stderr_truncated = truncate_text(completed.stderr, request.max_output_chars)
    if completed.timed_out:
        process_state = "terminated"
    elif completed.exit_code in request.expected_exit_codes:
        process_state = "completed"
    else:
        process_state = "failed"
    return ExecutionOutcome(
        command=(sys.executable, str(script_path), *request.args),
        detach_after_seconds=None,
        execution_directory=None,
        execution_id=None,
        exit_code=completed.exit_code,
        launch_status="completed",
        pid=None,
        process_state=process_state,
        run_mode=request.run_mode,
        source=source_details,
        stderr=stderr,
        stderr_log_path=None,
        stderr_truncated=stderr_truncated,
        stdout=stdout,
        stdout_log_path=None,
        stdout_truncated=stdout_truncated,
        still_running=False,
        timed_out=completed.timed_out,
        timeout_seconds=request.timeout_seconds,
    )


def _execute_managed(request: ExecutionRequest) -> ExecutionOutcome:
    execution_id, execution_directory = create_execution_directory()
    script_path, source_details = _prepare_managed_source(request.source, execution_directory)
    managed = start_managed_script(
        args=request.args,
        execution_directory=execution_directory,
        execution_id=execution_id,
        expected_exit_codes=request.expected_exit_codes,
        run_mode=request.run_mode,
        runtime=request.runtime,
        script_path=script_path,
        stdin_text=request.stdin_text,
        workdir=request.workdir,
    )
    # The public command intentionally mirrors a normal Python invocation rather
    # than exposing the internal launcher used to inject user dependencies.
    public_command = (sys.executable, str(script_path), *request.args)

    if request.run_mode == "detached":
        reap_process_in_background(managed)
        return _managed_outcome(
            request,
            managed,
            command=public_command,
            source_details=source_details,
            process_state="unchecked",
            still_running=None,
        )

    completion = wait_for_completion(
        managed,
        max_output_chars=request.max_output_chars,
        wait_seconds=request.detach_after_seconds,
    )
    if completion is None:
        reap_process_in_background(managed)
        return _managed_outcome(
            request,
            managed,
            command=public_command,
            source_details=source_details,
            process_state="running",
            still_running=True,
        )
    retain_artifacts = (
        completion.state == "stopped" or not discard_execution_artifacts(managed)
    )
    return _managed_outcome(
        request,
        managed,
        command=public_command,
        source_details=source_details,
        process_state=completion.state,
        still_running=False,
        exit_code=completion.exit_code,
        stderr=completion.stderr,
        stderr_truncated=completion.stderr_truncated,
        stdout=completion.stdout,
        stdout_truncated=completion.stdout_truncated,
        retain_artifacts=retain_artifacts,
    )


def _prepare_managed_source(
    source: ScriptSource,
    execution_directory: Path,
) -> tuple[Path, dict[str, str]]:
    if source.script_path is not None:
        return source.script_path, {"type": "file", "script_path": str(source.script_path)}
    script_path = execution_directory / source.script_filename
    try:
        script_path.write_text(source.script_text or "", encoding="utf-8")
    except OSError as exc:
        raise PythonRuntimeError(
            "SCRIPT_STORAGE_FAILED",
            "无法保存待执行的 Python 脚本。",
            {"script_path": str(script_path)},
        ) from exc
    return script_path, {
        "type": "inline",
        "script_filename": source.script_filename,
        "stored_script_path": str(script_path),
    }


def _managed_outcome(
    request: ExecutionRequest,
    managed: ManagedProcess,
    *,
    command: tuple[str, ...],
    source_details: dict[str, str],
    process_state: str,
    still_running: bool | None,
    exit_code: int | None = None,
    stderr: str = "",
    stderr_truncated: bool = False,
    stdout: str = "",
    stdout_truncated: bool = False,
    retain_artifacts: bool = True,
) -> ExecutionOutcome:
    source = dict(source_details)
    if not retain_artifacts:
        source.pop("stored_script_path", None)
    return ExecutionOutcome(
        command=command,
        detach_after_seconds=(
            request.detach_after_seconds if request.run_mode == "auto_detach" else None
        ),
        execution_directory=managed.execution_directory if retain_artifacts else None,
        execution_id=managed.execution_id if retain_artifacts else None,
        exit_code=exit_code,
        launch_status="spawned",
        pid=managed.process.pid,
        process_state=process_state,
        run_mode=request.run_mode,
        source=source,
        stderr=stderr,
        stderr_log_path=managed.stderr_log_path if retain_artifacts else None,
        stderr_truncated=stderr_truncated,
        stdout=stdout,
        stdout_log_path=managed.stdout_log_path if retain_artifacts else None,
        stdout_truncated=stdout_truncated,
        still_running=still_running,
        timed_out=False,
        timeout_seconds=None,
    )


def truncate_text(text: str, max_chars: int) -> tuple[str, bool]:
    if len(text) <= max_chars:
        return text, False
    return text[:max_chars] + f"\n...<truncated {len(text) - max_chars} chars>", True
