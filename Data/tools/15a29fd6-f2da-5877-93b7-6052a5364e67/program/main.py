from __future__ import annotations

from pathlib import Path
from typing import Any

from command_contract import CommandSpec, build_command_spec, workspace_root
from process_output import prepare_process_output
from process_runner import ProcessRunResult, run_process
from tiance_runtime import run_tool
from tool_errors import ToolError


def ok(summary: str, data: dict[str, Any], warnings: list[str] | None = None) -> dict[str, Any]:
    return {
        "ok": True,
        "summary": summary,
        "data": data,
        "warnings": warnings or [],
    }


def fail(
    code: str,
    message: str,
    *,
    data: dict[str, Any] | None = None,
    details: dict[str, Any] | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "ok": False,
        "summary": message,
        "data": data or {},
        "error": f"{code}: {message}",
        "error_info": {
            "code": code,
            "message": message,
            "details": details or {},
        },
        "warnings": warnings or [],
    }


def run(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        spec = build_command_spec(payload, root=workspace_root())
    except ToolError as exc:
        return fail(exc.code, exc.message, details=exc.details)

    try:
        result = run_process(
            spec.process_args,
            stdin_bytes=spec.stdin_bytes,
            cwd=spec.workdir,
            timeout_seconds=spec.timeout_seconds,
            max_output_chars=spec.max_output_chars,
            extra_env=spec.extra_env,
        )
    except FileNotFoundError as exc:
        message, details = _command_not_found(spec, exc)
        return fail(
            "COMMAND_NOT_FOUND",
            message,
            data=_execution_data(spec, status="start_failed"),
            details=details,
        )
    except PermissionError as exc:
        return fail(
            "PERMISSION_DENIED",
            "没有权限启动命令。",
            data=_execution_data(spec, status="start_failed"),
            details={"filename": str(exc.filename or spec.argv[0])},
        )
    except OSError as exc:
        return fail(
            "PROCESS_START_FAILED",
            "命令进程启动失败。",
            data=_execution_data(spec, status="start_failed"),
            details={
                "errno": exc.errno,
                "reason": exc.strerror or str(exc),
                "filename": str(exc.filename or spec.argv[0]),
            },
        )

    data, warnings = _completed_execution_data(spec, result)
    if result.timed_out:
        return fail(
            "COMMAND_TIMEOUT",
            f"命令在 {spec.timeout_seconds} 秒后超时。",
            data=data,
            warnings=warnings,
        )
    if result.returncode not in spec.expected_exit_codes:
        expected = ", ".join(str(code) for code in spec.expected_exit_codes)
        return fail(
            "COMMAND_FAILED",
            f"命令退出码为 {result.returncode}，预期退出码为 {expected}。",
            data=data,
            details={
                "exit_code": result.returncode,
                "expected_exit_codes": list(spec.expected_exit_codes),
            },
            warnings=warnings,
        )
    return ok("命令执行成功。", data, warnings)


def _completed_execution_data(
    spec: CommandSpec,
    result: ProcessRunResult,
) -> tuple[dict[str, Any], list[str]]:
    encoding_hint = spec.resolved_shell or "argv"
    stdout, stdout_text_truncated = prepare_process_output(
        result.stdout,
        encoding_hint=encoding_hint,
        max_chars=spec.max_output_chars,
    )
    stderr, stderr_text_truncated = prepare_process_output(
        result.stderr,
        encoding_hint=encoding_hint,
        max_chars=spec.max_output_chars,
    )
    stdout_truncated = stdout_text_truncated or result.stdout_omitted_bytes > 0
    stderr_truncated = stderr_text_truncated or result.stderr_omitted_bytes > 0
    status = "timeout" if result.timed_out else "completed"
    data = _execution_data(
        spec,
        status=status,
        exit_code=result.returncode,
        stdout=stdout,
        stderr=stderr,
        stdout_truncated=stdout_truncated,
        stderr_truncated=stderr_truncated,
        stdout_omitted_bytes=result.stdout_omitted_bytes,
        stderr_omitted_bytes=result.stderr_omitted_bytes,
        elapsed_ms=result.elapsed_ms,
    )
    warnings: list[str] = []
    if stdout_truncated:
        warnings.append("stdout 已截断。")
    if stderr_truncated:
        warnings.append("stderr 已截断。")
    return data, warnings


def _execution_data(
    spec: CommandSpec,
    *,
    status: str,
    exit_code: int | None = None,
    stdout: str = "",
    stderr: str = "",
    stdout_truncated: bool = False,
    stderr_truncated: bool = False,
    stdout_omitted_bytes: int = 0,
    stderr_omitted_bytes: int = 0,
    elapsed_ms: int | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "command": spec.command_for_display,
        "argv": spec.argv,
        "execution_mode": spec.execution_mode,
        "requested_shell": spec.requested_shell,
        "resolved_shell": spec.resolved_shell,
        "shell_executable": spec.shell_executable,
        "workdir": str(spec.workdir),
        "exit_code": exit_code,
        "expected_exit_codes": list(spec.expected_exit_codes),
        "extra_env_keys": list(spec.extra_env_keys),
        "stdout": stdout,
        "stderr": stderr,
        "stdout_truncated": stdout_truncated,
        "stderr_truncated": stderr_truncated,
        "stdout_omitted_bytes": stdout_omitted_bytes,
        "stderr_omitted_bytes": stderr_omitted_bytes,
        "timeout_seconds": spec.timeout_seconds,
        "elapsed_ms": elapsed_ms,
    }


def _command_not_found(
    spec: CommandSpec,
    exc: FileNotFoundError,
) -> tuple[str, dict[str, Any]]:
    filename = str(exc.filename or spec.argv[0])
    details: dict[str, Any] = {"filename": filename}
    if spec.execution_mode != "argv":
        return "找不到要启动的命令。", details

    executable = spec.argv[0]
    if Path(executable).name != executable:
        return "找不到要启动的命令。", details
    local_candidate = spec.workdir / executable
    if not local_candidate.is_file():
        return "找不到要启动的命令。", details

    details.update(
        {
            "local_candidate": str(local_candidate),
            "suggested_argv0": f".\\{executable}",
        }
    )
    return (
        "工作目录中存在该文件，但 argv 不会自动从工作目录查找可执行文件；"
        "请把 argv[0] 写成 .\\程序名或绝对路径。",
        details,
    )


if __name__ == "__main__":
    run_tool(run)
