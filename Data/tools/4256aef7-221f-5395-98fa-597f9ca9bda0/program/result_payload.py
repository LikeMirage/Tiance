from __future__ import annotations

import sys
from typing import Any

from installed_packages import InstalledPackage
from package_environment import RuntimePaths
from package_spec import PackageRequest
from package_target import PackageTarget


MAX_OUTPUT_CHARS = 20_000


def success(
    request: PackageRequest,
    runtime_paths: RuntimePaths,
    target: PackageTarget,
    packages: tuple[InstalledPackage, ...],
    *,
    summary: str,
    requested_packages: tuple[str, ...] | None = None,
    changed_packages: tuple[InstalledPackage, ...] = (),
    removed_packages: tuple[str, ...] = (),
    warnings: list[str] | None = None,
    command_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = {
        **base_data(request, runtime_paths, target),
        "requested_packages": list(requested_packages or request.packages),
        "packages": [package.to_dict() for package in packages],
        "changed_packages": [package.to_dict() for package in changed_packages],
        "removed_packages": list(removed_packages),
    }
    if command_result is not None:
        data["command_result"] = command_result
    return {
        "ok": True,
        "summary": summary,
        "data": data,
        "warnings": warnings if warnings is not None else list(target.warnings),
    }


def base_data(
    request: PackageRequest,
    runtime_paths: RuntimePaths,
    target: PackageTarget,
) -> dict[str, Any]:
    return {
        "operation": request.operation,
        "python_executable": str(runtime_paths.python_executable),
        "python_version": sys.version.split()[0],
        "target_kind": target.kind,
        "target_identifier": target.identifier,
        "target_name": target.display_name,
        "target_directory": str(target.target_directory),
        "requirements_path": str(target.requirements_path or ""),
    }


def command_result(completed: Any) -> dict[str, Any]:
    stdout, stdout_truncated = _truncate(completed.stdout or "")
    stderr, stderr_truncated = _truncate(completed.stderr or "")
    return {
        "exit_code": completed.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "stdout_truncated": stdout_truncated,
        "stderr_truncated": stderr_truncated,
    }


def install_failure(
    request: PackageRequest,
    runtime_paths: RuntimePaths,
    target: PackageTarget,
    result: dict[str, Any],
    return_code: int,
) -> dict[str, Any]:
    code = "INSTALL_TIMEOUT" if return_code == 124 else "INSTALL_FAILED"
    message = "依赖安装超时。" if return_code == 124 else "pip 安装失败。"
    return failure(
        code,
        message,
        {**base_data(request, runtime_paths, target), "command_result": result},
    )


def failure(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "ok": False,
        "error": f"{code}: {message}",
        "error_info": {"code": code, "message": message, "details": details or {}},
        "warnings": [],
    }


def _truncate(text: str) -> tuple[str, bool]:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text, False
    return text[:MAX_OUTPUT_CHARS] + f"\n...<truncated {len(text) - MAX_OUTPUT_CHARS} chars>", True
