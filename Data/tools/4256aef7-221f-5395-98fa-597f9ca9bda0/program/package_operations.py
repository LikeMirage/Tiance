from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from typing import Any

from candidate_environment import CandidateEnvironment
from environment_health import inspect_environment, repair_environment
from installed_packages import (
    list_installed_packages,
    select_installed_packages,
    uninstall_packages,
)
from package_environment import EnvironmentLock, RuntimePaths
from package_spec import PackageRequest, normalize_package_name, requirement_name
from package_target import PackageTarget, read_target_requirements
from pip_runner import install_packages
from result_payload import base_data, command_result, failure, install_failure, success


@dataclass(frozen=True, slots=True)
class InstallResult:
    packages: tuple[Any, ...] = ()
    warnings: tuple[str, ...] = ()
    command: dict[str, Any] | None = None
    error: dict[str, Any] | None = None


def execute_request(
    request: PackageRequest,
    runtime_paths: RuntimePaths,
    target: PackageTarget,
) -> dict[str, Any]:
    if request.operation == "check":
        return _check_environment(request, runtime_paths, target)
    if request.operation == "repair":
        return _repair_environment(request, runtime_paths, target)
    if request.operation == "list":
        with _target_lock(target):
            packages = list_installed_packages(target.target_directory)
        return success(
            request,
            runtime_paths,
            target,
            packages,
            summary=f"目标环境已安装 {len(packages)} 个依赖包。",
        )
    if request.operation == "show":
        with _target_lock(target):
            packages, missing = select_installed_packages(
                list_installed_packages(target.target_directory),
                request.packages,
            )
        return success(
            request,
            runtime_paths,
            target,
            packages,
            warnings=[f"未安装：{name}" for name in missing],
            summary=f"找到 {len(packages)} 个指定依赖包。",
        )
    if request.operation in {"install", "install_requirements"}:
        requested = request.packages if request.operation == "install" else read_target_requirements(target)
        return _install(request, runtime_paths, target, requested)
    return _uninstall(request, runtime_paths, target)


def _install(
    request: PackageRequest,
    runtime_paths: RuntimePaths,
    target: PackageTarget,
    requested: tuple[str, ...],
) -> dict[str, Any]:
    if not requested:
        packages = list_installed_packages(target.target_directory)
        return success(
            request,
            runtime_paths,
            target,
            packages,
            summary="工具没有声明 Python 依赖，无需补齐。",
        )
    if target.is_managed:
        install_result = _install_managed(
            request, runtime_paths, target, requested
        )
    else:
        install_result = _install_path(
            request, runtime_paths, target, requested
        )
    if install_result.error is not None:
        return install_result.error

    installed = install_result.packages

    requested_names = {
        normalize_package_name(requirement_name(package)) for package in requested
    }
    changed = tuple(
        package
        for package in installed
        if normalize_package_name(package.name) in requested_names
    )
    action = "依赖声明补齐" if request.operation == "install_requirements" else "依赖安装"
    return success(
        request,
        runtime_paths,
        target,
        installed,
        requested_packages=requested,
        changed_packages=changed,
        warnings=list(install_result.warnings),
        command_result=install_result.command,
        summary=f"{action}完成，目标环境现有 {len(installed)} 个包。",
    )


def _install_managed(
    request: PackageRequest,
    runtime_paths: RuntimePaths,
    target: PackageTarget,
    requested: tuple[str, ...],
) -> InstallResult:
    assert target.environment_root is not None
    with EnvironmentLock(target.environment_root):
        with CandidateEnvironment(target.environment_root) as candidate:
            assert candidate.path is not None
            completed = install_packages(
                runtime_paths,
                candidate.path,
                requested,
                index_url=request.index_url,
                timeout_seconds=request.timeout_seconds,
            )
            result = command_result(completed)
            if completed.returncode != 0:
                return InstallResult(
                    command=result,
                    error=install_failure(
                        request,
                        runtime_paths,
                        target,
                        result,
                        completed.returncode,
                    ),
                )
            installed = list_installed_packages(candidate.path)
            warnings = [*target.warnings, *candidate.preparation_warnings, *candidate.commit()]
    return InstallResult(
        packages=installed,
        warnings=tuple(warnings),
        command=result,
    )


def _install_path(
    request: PackageRequest,
    runtime_paths: RuntimePaths,
    target: PackageTarget,
    requested: tuple[str, ...],
) -> InstallResult:
    target_directory = target.target_directory
    target_directory.mkdir(parents=True, exist_ok=True)
    with EnvironmentLock(target_directory):
        completed = install_packages(
            runtime_paths,
            target_directory,
            requested,
            index_url=request.index_url,
            timeout_seconds=request.timeout_seconds,
        )
        result = command_result(completed)
        if completed.returncode != 0:
            return InstallResult(
                command=result,
                error=install_failure(
                    request,
                    runtime_paths,
                    target,
                    result,
                    completed.returncode,
                ),
            )
        installed = list_installed_packages(target_directory)
    return InstallResult(
        packages=installed,
        warnings=target.warnings,
        command=result,
    )


def _uninstall(
    request: PackageRequest,
    runtime_paths: RuntimePaths,
    target: PackageTarget,
) -> dict[str, Any]:
    lock_root = target.environment_root or target.target_directory
    with EnvironmentLock(lock_root):
        current = list_installed_packages(target.target_directory)
        selected, missing = select_installed_packages(current, request.packages)
        if not selected:
            return success(
                request,
                runtime_paths,
                target,
                current,
                warnings=[*target.warnings, *[f"未安装：{name}" for name in missing]],
                summary="指定依赖均未安装，无需卸载。",
            )
        if target.is_managed:
            assert target.environment_root is not None
            with CandidateEnvironment(target.environment_root) as candidate:
                assert candidate.path is not None
                removed = uninstall_packages(candidate.path, tuple(item.name for item in selected))
                remaining = list_installed_packages(candidate.path)
                warnings = [*target.warnings, *candidate.preparation_warnings, *candidate.commit()]
        else:
            removed = uninstall_packages(target.target_directory, tuple(item.name for item in selected))
            remaining = list_installed_packages(target.target_directory)
            warnings = list(target.warnings)
    warnings.extend(f"未安装：{name}" for name in missing)
    return success(
        request,
        runtime_paths,
        target,
        remaining,
        removed_packages=removed,
        warnings=warnings,
        summary=f"已卸载 {len(removed)} 个依赖包。",
    )


def _check_environment(
    request: PackageRequest,
    runtime_paths: RuntimePaths,
    target: PackageTarget,
) -> dict[str, Any]:
    if not target.is_managed:
        return _check_path(request, runtime_paths, target)
    assert target.environment_root is not None
    with EnvironmentLock(target.environment_root):
        report = inspect_environment(target.environment_root)
    data = {**base_data(request, runtime_paths, target), "environment_health": report.to_dict()}
    if not report.healthy:
        return failure(
            "ENVIRONMENT_UNHEALTHY",
            "工具依赖环境存在权限或复制异常，可执行 repair 修复。",
            data,
        )
    return {
        "ok": True,
        "summary": "工具依赖环境检查通过。",
        "data": data,
        "warnings": list(target.warnings),
    }


def _check_path(
    request: PackageRequest,
    runtime_paths: RuntimePaths,
    target: PackageTarget,
) -> dict[str, Any]:
    target_directory = target.target_directory
    target_directory.mkdir(parents=True, exist_ok=True)
    probe = target_directory / f".tiance-write-probe-{os.getpid()}-{uuid.uuid4().hex}"
    try:
        probe.write_text("ok\n", encoding="utf-8")
    except OSError as exc:
        return failure(
            "TARGET_NOT_WRITABLE",
            "目标依赖目录不可写。",
            {**base_data(request, runtime_paths, target), "error": str(exc)},
        )
    finally:
        probe.unlink(missing_ok=True)
    return {
        "ok": True,
        "summary": "目标依赖目录可写。",
        "data": base_data(request, runtime_paths, target),
        "warnings": list(target.warnings),
    }


def _repair_environment(
    request: PackageRequest,
    runtime_paths: RuntimePaths,
    target: PackageTarget,
) -> dict[str, Any]:
    if not target.is_managed:
        return failure(
            "REPAIR_REQUIRES_TOOL_TARGET",
            "repair 只允许修复工具自己的依赖目录。",
            base_data(request, runtime_paths, target),
        )
    assert target.environment_root is not None
    with EnvironmentLock(target.environment_root):
        report = repair_environment(target.environment_root)
    data = {**base_data(request, runtime_paths, target), "environment_repair": report.to_dict()}
    if not report.succeeded:
        message = (
            "工具依赖环境仍无法修复，需要以管理员身份运行一次修复。"
            if report.requires_elevation
            else "工具依赖环境修复后仍未通过检查。"
        )
        return failure("ENVIRONMENT_REPAIR_FAILED", message, data)
    return {
        "ok": True,
        "summary": "工具依赖环境权限已恢复并通过检查。",
        "data": data,
        "warnings": list(target.warnings),
    }


def _target_lock(target: PackageTarget) -> EnvironmentLock:
    return EnvironmentLock(target.environment_root or target.target_directory)
