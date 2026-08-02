from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
from typing import Any

from shell_resolution import build_shell_command, display_argv, validate_argv_shell
from tool_errors import ToolError


@dataclass(frozen=True, slots=True)
class CommandSpec:
    process_args: list[str] | str
    argv: list[str]
    command_for_display: str
    execution_mode: str
    requested_shell: str | None
    resolved_shell: str | None
    shell_executable: str | None
    workdir: Path
    stdin_bytes: bytes | None
    timeout_seconds: int
    max_output_chars: int
    expected_exit_codes: tuple[int, ...]


def workspace_root() -> Path:
    raw = os.environ.get("TIANCE_WORKSPACE_ROOT") or os.environ.get("WORKSPACE_ROOT") or os.getcwd()
    return Path(raw).expanduser().resolve(strict=False)


def build_command_spec(payload: dict[str, Any], *, root: Path) -> CommandSpec:
    command = _read_command(payload.get("command"))
    direct_argv = _read_argv(payload.get("argv"))
    if bool(command) == bool(direct_argv):
        raise ToolError("INVALID_ARGUMENT", "command 和 argv 必须且只能提供一个。")

    stdin_bytes = _read_stdin(payload.get("stdin"))
    workdir = _resolve_workdir(payload.get("workdir"), root)
    timeout_seconds = _read_int(payload.get("timeout_seconds"), 30, 1, 300)
    max_output_chars = _read_int(payload.get("max_output_chars"), 20_000, 1_000, 200_000)
    expected_exit_codes = _read_expected_exit_codes(payload.get("expected_exit_codes"))

    if direct_argv is not None:
        validate_argv_shell(payload.get("shell"))
        return CommandSpec(
            process_args=direct_argv,
            argv=direct_argv,
            command_for_display=display_argv(direct_argv),
            execution_mode="argv",
            requested_shell=None,
            resolved_shell=None,
            shell_executable=None,
            workdir=workdir,
            stdin_bytes=stdin_bytes,
            timeout_seconds=timeout_seconds,
            max_output_chars=max_output_chars,
            expected_exit_codes=expected_exit_codes,
        )

    assert command is not None
    if _is_large_python_c_command(command):
        raise ToolError(
            "UNSAFE_INLINE_PYTHON_SCRIPT",
            "检测到大段 Python 脚本使用 python -c。run_command 只负责短命令，请改用 run_python_script 的 script_text。",
            {
                "recommended_tool": "run_python_script",
                "recommended_field": "script_text",
            },
        )

    shell_command = build_shell_command(command, payload.get("shell"))
    return CommandSpec(
        process_args=shell_command.process_args,
        argv=shell_command.argv,
        command_for_display=command,
        execution_mode="shell",
        requested_shell=shell_command.requested_shell,
        resolved_shell=shell_command.resolved_shell,
        shell_executable=shell_command.executable,
        workdir=workdir,
        stdin_bytes=stdin_bytes,
        timeout_seconds=timeout_seconds,
        max_output_chars=max_output_chars,
        expected_exit_codes=expected_exit_codes,
    )


def _read_command(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ToolError("INVALID_ARGUMENT", "command 必须是字符串。")
    command = value.strip()
    return command or None


def _read_argv(value: Any) -> list[str] | None:
    if value is None:
        return None
    if not isinstance(value, list) or not value:
        raise ToolError("INVALID_ARGUMENT", "argv 必须是非空字符串数组。")
    argv: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str):
            raise ToolError("INVALID_ARGUMENT", "argv 必须全部是字符串。", {"index": index})
        if index == 0 and not item.strip():
            raise ToolError("INVALID_ARGUMENT", "argv[0] 不能为空。")
        argv.append(item)
    return argv


def _read_stdin(value: Any) -> bytes | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ToolError("INVALID_ARGUMENT", "stdin 必须是字符串。")
    return value.encode("utf-8")


def _read_expected_exit_codes(value: Any) -> tuple[int, ...]:
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


def _read_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def _resolve_workdir(value: Any, root: Path) -> Path:
    raw = str(value or "").strip()
    path = Path(raw).expanduser() if raw else root
    if not path.is_absolute():
        path = root / path
    resolved = path.resolve(strict=False)
    if not resolved.exists():
        raise ToolError("DIRECTORY_NOT_FOUND", "工作目录不存在。", {"workdir": str(resolved)})
    if not resolved.is_dir():
        raise ToolError("IS_FILE", "工作目录必须是目录。", {"workdir": str(resolved)})
    return resolved


def _is_large_python_c_command(command: str) -> bool:
    if not command:
        return False
    if not re.search(r"(?i)(^|\s)(python|python3|py)(\.exe)?(\s+-\d+(\.\d+)?)?\s+-c(\s|$)", command):
        return False
    if "\n" in command or "\r" in command:
        return True
    if len(command) >= 500:
        return True
    return "\\n" in command and len(command) >= 160
