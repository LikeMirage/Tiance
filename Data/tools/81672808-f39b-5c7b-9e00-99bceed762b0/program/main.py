from __future__ import annotations

import os
from pathlib import Path
import re
import sys
from typing import Any, cast

from execution_service import (
    DEFAULT_DETACH_AFTER_SECONDS,
    DEFAULT_RUN_MODE,
    DEFAULT_WAIT_TIMEOUT_SECONDS,
    RUN_MODES,
    ExecutionRequest,
    RunMode,
    ScriptSource,
    execute,
)
from python_runtime import PythonRuntimeError, prepared_runtime
from tiance_runtime import run_tool


class ToolError(Exception):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def ok(summary: str, data: dict[str, Any], warnings: list[str] | None = None) -> dict[str, Any]:
    return {"ok": True, "summary": summary, "data": data, "warnings": warnings or []}


def fail(
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "ok": False,
        "error": f"{code}: {message}",
        "error_info": {"code": code, "message": message, "details": details or {}},
        "warnings": warnings or [],
    }


def workspace_root() -> Path:
    raw = os.environ.get("TIANCE_WORKSPACE_ROOT") or os.environ.get("WORKSPACE_ROOT") or os.getcwd()
    return Path(raw).expanduser().resolve(strict=False)


def read_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "y", "on"}:
            return True
        if lowered in {"false", "0", "no", "n", "off"}:
            return False
    return default


def read_int(
    value: Any,
    default: int,
    minimum: int,
    maximum: int,
    *,
    field_name: str,
) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise ToolError("INVALID_ARGUMENT", f"{field_name} 必须是整数。")
    if value < minimum or value > maximum:
        raise ToolError(
            "INVALID_ARGUMENT",
            f"{field_name} 必须在 {minimum} 到 {maximum} 之间。",
        )
    return value


def read_string_list(value: Any, *, field_name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ToolError("INVALID_ARGUMENT", f"{field_name} 必须是字符串数组。")
    result: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str):
            raise ToolError("INVALID_ARGUMENT", f"{field_name} 必须全部是字符串。", {"index": index})
        result.append(item)
    return result


def read_optional_text(value: Any, *, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ToolError("INVALID_ARGUMENT", f"{field_name} 必须是字符串。")
    return value


def resolve_directory(value: Any, root: Path, *, allow_outside: bool, field_name: str) -> Path:
    raw = str(value or "").strip()
    path = Path(raw).expanduser() if raw else root
    if not path.is_absolute():
        path = root / path
    resolved = path.resolve(strict=False)
    if not allow_outside:
        ensure_inside_workspace(resolved, root, field_name)
    if not resolved.exists():
        raise ToolError("DIRECTORY_NOT_FOUND", "工作目录不存在。", {field_name: str(resolved)})
    if not resolved.is_dir():
        raise ToolError("IS_FILE", "工作目录必须是目录。", {field_name: str(resolved)})
    return resolved


def resolve_script_path(value: str, root: Path, *, allow_outside: bool) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = root / path
    resolved = path.resolve(strict=False)
    if not allow_outside:
        ensure_inside_workspace(resolved, root, "script_path")
    if not resolved.exists():
        raise ToolError("SCRIPT_NOT_FOUND", "脚本文件不存在。", {"script_path": str(resolved)})
    if not resolved.is_file():
        raise ToolError("SCRIPT_NOT_FILE", "script_path 必须指向文件。", {"script_path": str(resolved)})
    if resolved.suffix.lower() != ".py":
        raise ToolError("SCRIPT_NOT_PYTHON", "script_path 只允许 .py 文件。", {"script_path": str(resolved)})
    return resolved


def ensure_inside_workspace(path: Path, root: Path, field_name: str) -> None:
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ToolError(
            "PATH_OUTSIDE_WORKSPACE",
            f"{field_name} 不在工作区内。",
            {field_name: str(path), "workspace_root": str(root)},
        ) from exc


def safe_temp_filename(value: Any) -> str:
    raw = str(value or "script.py").strip() or "script.py"
    if "/" in raw or "\\" in raw:
        raise ToolError("INVALID_ARGUMENT", "script_filename 只能是文件名，不能包含路径。")
    if not raw.endswith(".py"):
        raw += ".py"
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", raw):
        raise ToolError("INVALID_ARGUMENT", "script_filename 只能包含字母、数字、下划线、点和短横线。")
    return raw


def read_extra_env(value: Any) -> tuple[dict[str, str], list[str]]:
    if value is None:
        return {}, []
    if not isinstance(value, dict):
        raise ToolError("INVALID_ARGUMENT", "extra_env 必须是字符串键值对象。")
    environment: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not key:
            raise ToolError("INVALID_ARGUMENT", "extra_env 的键必须是非空字符串。")
        if not isinstance(item, str):
            raise ToolError("INVALID_ARGUMENT", "extra_env 的值必须是字符串。", {"key": key})
        environment[key] = item
    return environment, sorted(environment)


def read_run_mode(value: Any) -> RunMode:
    if value is None:
        return DEFAULT_RUN_MODE
    if not isinstance(value, str) or value not in RUN_MODES:
        raise ToolError(
            "INVALID_ARGUMENT",
            "run_mode 必须是 wait、detached 或 auto_detach。",
        )
    return cast(RunMode, value)


def read_expected_exit_codes(value: Any) -> tuple[int, ...]:
    if value is None:
        return (0,)
    if not isinstance(value, list) or not value:
        raise ToolError("INVALID_ARGUMENT", "expected_exit_codes 必须是非空整数数组。")
    codes: list[int] = []
    seen: set[int] = set()
    for index, item in enumerate(value):
        if isinstance(item, bool) or not isinstance(item, int):
            raise ToolError(
                "INVALID_ARGUMENT",
                "expected_exit_codes 必须全部是整数。",
                {"index": index},
            )
        if item in seen:
            raise ToolError(
                "INVALID_ARGUMENT",
                "expected_exit_codes 不允许重复值。",
                {"exit_code": item},
            )
        seen.add(item)
        codes.append(item)
    return tuple(codes)


def run(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        root = workspace_root()
        script_text = read_optional_text(payload.get("script_text"), field_name="script_text")
        script_path_raw = read_optional_text(payload.get("script_path"), field_name="script_path")
        if (script_text is None) == (script_path_raw is None):
            raise ToolError("INVALID_ARGUMENT", "script_text 和 script_path 必须二选一。")

        allow_workdir_outside = read_bool(payload.get("allow_workdir_outside_workspace"), False)
        allow_source_outside = read_bool(payload.get("allow_source_outside_workspace"), False)
        workdir = resolve_directory(
            payload.get("workdir"),
            root,
            allow_outside=allow_workdir_outside,
            field_name="workdir",
        )
        args = read_string_list(payload.get("args"), field_name="args")
        stdin_text = read_optional_text(payload.get("stdin"), field_name="stdin")
        run_mode = read_run_mode(payload.get("run_mode"))
        expected_exit_codes = read_expected_exit_codes(
            payload.get("expected_exit_codes")
        )
        timeout = read_int(
            payload.get("timeout_seconds"),
            DEFAULT_WAIT_TIMEOUT_SECONDS,
            1,
            600,
            field_name="timeout_seconds",
        )
        detach_after = read_int(
            payload.get("detach_after_seconds"),
            DEFAULT_DETACH_AFTER_SECONDS,
            1,
            600,
            field_name="detach_after_seconds",
        )
        max_output_chars = read_int(
            payload.get("max_output_chars"),
            20000,
            1000,
            200000,
            field_name="max_output_chars",
        )
        extra_env, extra_env_keys = read_extra_env(payload.get("extra_env"))
        warnings: list[str] = []

        if script_path_raw is not None:
            resolved_script_path = resolve_script_path(
                script_path_raw,
                root,
                allow_outside=allow_source_outside,
            )
            source = ScriptSource(
                script_path=resolved_script_path,
                script_text=None,
                script_filename=resolved_script_path.name,
            )
        else:
            source = ScriptSource(
                script_path=None,
                script_text=script_text,
                script_filename=safe_temp_filename(payload.get("script_filename")),
            )

        with prepared_runtime(workdir, extra_env) as runtime:
            outcome = execute(
                ExecutionRequest(
                    args=args,
                    detach_after_seconds=detach_after,
                    expected_exit_codes=expected_exit_codes,
                    max_output_chars=max_output_chars,
                    run_mode=run_mode,
                    runtime=runtime,
                    source=source,
                    stdin_text=stdin_text,
                    timeout_seconds=timeout,
                    workdir=workdir,
                )
            )

        if outcome.stdout_truncated:
            warnings.append("stdout 已截断。")
        if outcome.stderr_truncated:
            warnings.append("stderr 已截断。")

        data = {
            "python_executable": sys.executable,
            "python_version": sys.version.split()[0],
            "dependency_site_packages": str(runtime.dependency_site_packages or ""),
            "command": list(outcome.command),
            "workdir": str(workdir),
            "source": outcome.source,
            "args": args,
            "run_mode": outcome.run_mode,
            "launch_status": outcome.launch_status,
            "process_state": outcome.process_state,
            "pid": outcome.pid,
            "still_running": outcome.still_running,
            "exit_code": outcome.exit_code,
            "expected_exit_codes": list(expected_exit_codes),
            "stdout": outcome.stdout,
            "stderr": outcome.stderr,
            "stdout_truncated": outcome.stdout_truncated,
            "stderr_truncated": outcome.stderr_truncated,
            "timeout_seconds": outcome.timeout_seconds,
            "detach_after_seconds": outcome.detach_after_seconds,
            "execution_id": outcome.execution_id,
            "execution_directory": str(outcome.execution_directory or ""),
            "stdout_log_path": str(outcome.stdout_log_path or ""),
            "stderr_log_path": str(outcome.stderr_log_path or ""),
            "extra_env_keys": extra_env_keys,
        }
        if outcome.timed_out:
            return fail("SCRIPT_TIMEOUT", f"脚本在 {timeout} 秒后超时。", data, warnings)
        if (
            outcome.exit_code is not None
            and outcome.exit_code not in expected_exit_codes
        ):
            expected = ", ".join(str(code) for code in expected_exit_codes)
            return fail(
                "SCRIPT_FAILED",
                f"脚本退出码为 {outcome.exit_code}，预期退出码为 [{expected}]。",
                data,
                warnings,
            )
        if outcome.process_state == "unchecked":
            return ok("Python 程序已启动，后续运行状态未检查。", data, warnings)
        if outcome.still_running:
            warnings.append(
                "脚本已转入后台运行；使用 python_process_manager 并传入 "
                f"execution_id={outcome.execution_id} 查看状态和日志。"
            )
            return ok(
                f"Python 程序在 {detach_after} 秒后仍在运行，已转为后台运行。",
                data,
                warnings,
            )
        return ok("Python 脚本执行成功。", data, warnings)
    except ToolError as exc:
        return fail(exc.code, exc.message, exc.details)
    except PythonRuntimeError as exc:
        return fail(exc.code, exc.message, exc.details)


if __name__ == "__main__":
    run_tool(run)
