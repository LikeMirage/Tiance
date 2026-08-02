from __future__ import annotations

from dataclasses import dataclass
import os
import shlex
import shutil
import subprocess
from typing import Any

from tool_errors import ToolError


@dataclass(frozen=True, slots=True)
class ShellCommand:
    process_args: list[str] | str
    argv: list[str]
    requested_shell: str
    resolved_shell: str
    executable: str


def build_shell_command(command: str, shell_value: Any) -> ShellCommand:
    requested_shell = _read_shell(shell_value)
    resolved_shell = _resolve_shell_name(requested_shell)
    argv, executable = _shell_argv(command, resolved_shell)
    return ShellCommand(
        process_args=_process_args(
            argv,
            command=command,
            resolved_shell=resolved_shell,
        ),
        argv=argv,
        requested_shell=requested_shell,
        resolved_shell=resolved_shell,
        executable=executable,
    )


def validate_argv_shell(value: Any) -> None:
    if value is None:
        return
    requested = _read_shell(value)
    if requested != "default":
        raise ToolError("INVALID_ARGUMENT", "argv 模式不使用 shell 参数。")


def display_argv(argv: list[str]) -> str:
    if os.name == "nt":
        return subprocess.list2cmdline(argv)
    return shlex.join(argv)


def _read_shell(value: Any) -> str:
    if value is None:
        return "default"
    if not isinstance(value, str):
        raise ToolError("INVALID_ARGUMENT", "shell 必须是字符串。")
    requested = value.strip().lower() or "default"
    if requested not in {"default", "powershell", "cmd", "bash", "sh"}:
        raise ToolError("INVALID_ARGUMENT", "shell 参数无效。", {"shell": value})
    return requested


def _resolve_shell_name(requested: str) -> str:
    if requested == "default":
        return "powershell" if os.name == "nt" else "sh"
    return requested


def _shell_argv(command: str, resolved_shell: str) -> tuple[list[str], str]:
    if resolved_shell == "powershell":
        executable = shutil.which("pwsh") or shutil.which("powershell")
        if not executable:
            raise ToolError("SHELL_NOT_FOUND", "未找到 PowerShell。", {"shell": resolved_shell})
        return [
            executable,
            "-NoLogo",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            _powershell_command(command),
        ], executable
    if resolved_shell == "cmd":
        if os.name != "nt":
            raise ToolError("INVALID_ARGUMENT", "cmd 仅适用于 Windows。", {"shell": resolved_shell})
        executable = shutil.which("cmd") or "cmd"
        return [executable, "/d", "/s", "/c", command], executable
    if resolved_shell in {"bash", "sh"}:
        executable = shutil.which(resolved_shell)
        if not executable:
            raise ToolError("SHELL_NOT_FOUND", f"未找到 {resolved_shell}。", {"shell": resolved_shell})
        return [
            executable,
            "-lc" if resolved_shell == "bash" else "-c",
            command,
        ], executable
    raise ToolError("INVALID_ARGUMENT", "shell 参数无效。", {"shell": resolved_shell})


def _powershell_command(command: str) -> str:
    return (
        "$global:LASTEXITCODE = 0\n"
        f"{command}\n\n"
        "if ($?) { exit 0 }\n"
        "if ($global:LASTEXITCODE -ne 0) { exit $global:LASTEXITCODE }\n"
        "exit 1"
    )


def _process_args(
    argv: list[str],
    *,
    command: str,
    resolved_shell: str,
) -> list[str] | str:
    if resolved_shell != "cmd":
        return argv
    executable = subprocess.list2cmdline([argv[0]])
    return f"{executable} /d /s /c {command}"
