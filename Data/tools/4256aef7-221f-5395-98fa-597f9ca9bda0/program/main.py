from __future__ import annotations

import sys
from typing import Any

from candidate_environment import CandidateEnvironment
from environment_health import inspect_environment, repair_environment
from package_environment import (
    EnvironmentError,
    EnvironmentLock,
    RuntimePaths,
    resolve_runtime_paths,
)
from installed_packages import (
    InstalledPackage,
    list_installed_packages,
    select_installed_packages,
    uninstall_packages,
)
from package_spec import (
    InputError,
    PackageRequest,
    normalize_package_name,
    parse_request,
    requirement_name,
)
from pip_runner import install_packages
from tiance_runtime import run_tool


MAX_OUTPUT_CHARS = 20_000


def run(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        request = parse_request(payload)
        runtime_paths = resolve_runtime_paths(sys.executable)
        if request.operation == "check":
            return _check_environment(request, runtime_paths)
        if request.operation == "repair":
            return _repair_environment(request, runtime_paths)
        if request.operation == "list":
            with EnvironmentLock(runtime_paths.user_packages_root):
                packages = list_installed_packages(runtime_paths.target_directory)
                return _success(
                    request,
                    runtime_paths,
                    packages,
                    summary=f"已安装 {len(packages)} 个用户依赖包。",
                )
        if request.operation == "show":
            with EnvironmentLock(runtime_paths.user_packages_root):
                packages, missing = select_installed_packages(
                    list_installed_packages(runtime_paths.target_directory),
                    request.packages,
                )
                warnings = [f"未安装：{name}" for name in missing]
                return _success(
                    request,
                    runtime_paths,
                    packages,
                    warnings=warnings,
                    summary=f"找到 {len(packages)} 个指定依赖包。",
                )
        if request.operation == "install":
            return _install(request, runtime_paths)
        return _uninstall(request, runtime_paths)
    except InputError as exc:
        return _failure(exc.code, exc.message, exc.details)
    except EnvironmentError as exc:
        return _failure(exc.code, exc.message, exc.details)
    except Exception as exc:
        return _failure("UNEXPECTED_ERROR", str(exc) or exc.__class__.__name__)


def _install(request: PackageRequest, runtime_paths: RuntimePaths) -> dict[str, Any]:
    with EnvironmentLock(runtime_paths.user_packages_root):
        with CandidateEnvironment(runtime_paths.user_packages_root) as candidate:
            assert candidate.path is not None
            completed = install_packages(
                runtime_paths,
                candidate.path,
                request.packages,
                index_url=request.index_url,
                timeout_seconds=request.timeout_seconds,
            )
            stdout, stdout_truncated = _truncate(completed.stdout or "")
            stderr, stderr_truncated = _truncate(completed.stderr or "")
            command_result = {
                "exit_code": completed.returncode,
                "stdout": stdout,
                "stderr": stderr,
                "stdout_truncated": stdout_truncated,
                "stderr_truncated": stderr_truncated,
            }
            if completed.returncode != 0:
                code = "INSTALL_TIMEOUT" if completed.returncode == 124 else "INSTALL_FAILED"
                message = "依赖安装超时。" if completed.returncode == 124 else "pip 安装失败。"
                return _failure(
                    code,
                    message,
                    {
                        **_base_data(request, runtime_paths),
                        "command_result": command_result,
                    },
                )
            installed = list_installed_packages(candidate.path)
            warnings = [*candidate.preparation_warnings, *candidate.commit()]
        requested_names = {
            normalize_package_name(requirement_name(package))
            for package in request.packages
        }
        changed = tuple(
            package
            for package in installed
            if normalize_package_name(package.name) in requested_names
        )
        return _success(
            request,
            runtime_paths,
            installed,
            changed_packages=changed,
            warnings=warnings,
            command_result=command_result,
            summary=f"依赖安装完成，用户环境现有 {len(installed)} 个包。",
        )


def _uninstall(request: PackageRequest, runtime_paths: RuntimePaths) -> dict[str, Any]:
    with EnvironmentLock(runtime_paths.user_packages_root):
        current = list_installed_packages(runtime_paths.target_directory)
        selected, missing = select_installed_packages(current, request.packages)
        if not selected:
            return _success(
                request,
                runtime_paths,
                current,
                warnings=[f"未安装：{name}" for name in missing],
                summary="指定依赖均未安装，无需卸载。",
            )
        with CandidateEnvironment(runtime_paths.user_packages_root) as candidate:
            assert candidate.path is not None
            removed = uninstall_packages(
                candidate.path,
                tuple(package.name for package in selected),
            )
            remaining = list_installed_packages(candidate.path)
            warnings = [*candidate.preparation_warnings, *candidate.commit()]
        warnings.extend(f"未安装：{name}" for name in missing)
        return _success(
            request,
            runtime_paths,
            remaining,
            removed_packages=removed,
            warnings=warnings,
            summary=f"已卸载 {len(removed)} 个依赖包。",
        )


def _check_environment(
    request: PackageRequest,
    runtime_paths: RuntimePaths,
) -> dict[str, Any]:
    with EnvironmentLock(runtime_paths.user_packages_root):
        report = inspect_environment(runtime_paths.user_packages_root)
    data = {**_base_data(request, runtime_paths), "environment_health": report.to_dict()}
    if not report.healthy:
        return _failure(
            "ENVIRONMENT_UNHEALTHY",
            "用户依赖环境存在权限或复制异常，可执行 repair 修复。",
            data,
        )
    return {
        "ok": True,
        "summary": "用户依赖环境检查通过。",
        "data": data,
        "warnings": [],
    }


def _repair_environment(
    request: PackageRequest,
    runtime_paths: RuntimePaths,
) -> dict[str, Any]:
    with EnvironmentLock(runtime_paths.user_packages_root):
        report = repair_environment(runtime_paths.user_packages_root)
    data = {**_base_data(request, runtime_paths), "environment_repair": report.to_dict()}
    if not report.succeeded:
        message = (
            "用户依赖环境仍无法修复，需要以管理员身份运行一次修复。"
            if report.requires_elevation
            else "用户依赖环境修复后仍未通过检查。"
        )
        return _failure("ENVIRONMENT_REPAIR_FAILED", message, data)
    return {
        "ok": True,
        "summary": "用户依赖环境权限已恢复并通过检查。",
        "data": data,
        "warnings": [],
    }


def _success(
    request: PackageRequest,
    runtime_paths: RuntimePaths,
    packages: tuple[InstalledPackage, ...],
    *,
    summary: str,
    changed_packages: tuple[InstalledPackage, ...] = (),
    removed_packages: tuple[str, ...] = (),
    warnings: list[str] | None = None,
    command_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = {
        **_base_data(request, runtime_paths),
        "packages": [package.to_dict() for package in packages],
        "changed_packages": [package.to_dict() for package in changed_packages],
        "removed_packages": list(removed_packages),
    }
    if command_result is not None:
        data["command_result"] = command_result
    return {"ok": True, "summary": summary, "data": data, "warnings": warnings or []}


def _base_data(request: PackageRequest, runtime_paths: RuntimePaths) -> dict[str, Any]:
    return {
        "operation": request.operation,
        "requested_packages": list(request.packages),
        "python_executable": str(runtime_paths.python_executable),
        "python_version": sys.version.split()[0],
        "target_directory": str(runtime_paths.target_directory),
    }


def _failure(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
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


if __name__ == "__main__":
    run_tool(run)
