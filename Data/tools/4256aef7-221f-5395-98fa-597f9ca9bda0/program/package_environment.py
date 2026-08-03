from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

ACTIVE_ENVIRONMENT_SCHEMA_VERSION = 1
ACTIVE_ENVIRONMENT_FILE = "active.json"
ENVIRONMENTS_DIRECTORY = "environments"
LEGACY_SITE_PACKAGES_DIRECTORY = "site-packages"
OBSOLETE_ENVIRONMENT_GRACE_SECONDS = 3600
LEASES_DIRECTORY = "leases"
LEASE_STALE_SECONDS = 900


class EnvironmentError(RuntimeError):
    def __init__(self, code: str, message: str, details: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


@dataclass(frozen=True, slots=True)
class RuntimePaths:
    python_executable: Path
    pip_runner: Path
    runtime_root: Path
    tools_root: Path


def resolve_runtime_paths(python_executable: str | Path) -> RuntimePaths:
    executable = Path(python_executable).resolve()
    if executable.parent.name != "py313" or executable.parent.parent.name != "python":
        raise EnvironmentError(
            "EMBEDDED_PYTHON_REQUIRED",
            "PIP 依赖管理只能使用 天策 内置 Python。",
            {"python_executable": str(executable)},
        )
    runtime_root = executable.parents[2]
    if runtime_root.name != "runtime":
        raise EnvironmentError(
            "INVALID_RUNTIME_LAYOUT",
            "内置 Python 目录结构不符合 天策 运行时约定。",
            {"python_executable": str(executable)},
        )
    pip_runner = executable.parent.parent / "run_pip.py"
    if not pip_runner.is_file():
        raise EnvironmentError("PIP_NOT_FOUND", "内置 pip 入口不存在。", {"pip_runner": str(pip_runner)})
    return RuntimePaths(
        python_executable=executable,
        pip_runner=pip_runner,
        runtime_root=runtime_root,
        tools_root=runtime_root.parent / "tools",
    )


def resolve_active_site_packages(packages_root: Path) -> Path:
    legacy_directory = packages_root / LEGACY_SITE_PACKAGES_DIRECTORY
    pointer_file = packages_root / ACTIVE_ENVIRONMENT_FILE
    if not pointer_file.is_file():
        return legacy_directory

    try:
        payload = json.loads(pointer_file.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EnvironmentError(
            "ACTIVE_ENVIRONMENT_INVALID",
            "工具依赖活动环境记录损坏。",
            {"pointer_file": str(pointer_file)},
        ) from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != ACTIVE_ENVIRONMENT_SCHEMA_VERSION:
        raise EnvironmentError(
            "ACTIVE_ENVIRONMENT_INVALID",
            "工具依赖活动环境记录版本无效。",
            {"pointer_file": str(pointer_file)},
        )
    relative_value = payload.get("site_packages")
    if not isinstance(relative_value, str) or not relative_value.strip():
        raise EnvironmentError(
            "ACTIVE_ENVIRONMENT_INVALID",
            "工具依赖活动环境路径无效。",
            {"pointer_file": str(pointer_file)},
        )

    root = packages_root.resolve()
    relative_path = Path(relative_value)
    site_packages = (root / relative_path).resolve()
    if relative_path.is_absolute() or not _is_relative_to(site_packages, root):
        raise EnvironmentError(
            "ACTIVE_ENVIRONMENT_INVALID",
            "工具依赖活动环境路径越出存储目录。",
            {"pointer_file": str(pointer_file)},
        )
    if not site_packages.is_dir():
        raise EnvironmentError(
            "ACTIVE_ENVIRONMENT_MISSING",
            "工具依赖活动环境不存在。",
            {"target_directory": str(site_packages)},
        )
    return site_packages


class EnvironmentLock:
    def __init__(self, packages_root: Path) -> None:
        self._lock_file = packages_root / ".package-manager.lock"
        self._acquired = False

    def __enter__(self) -> "EnvironmentLock":
        self._lock_file.parent.mkdir(parents=True, exist_ok=True)
        self._remove_stale_lock()
        try:
            descriptor = os.open(self._lock_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise EnvironmentError("ENVIRONMENT_BUSY", "另一个依赖管理任务正在运行。") from exc
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(f"pid={os.getpid()}\ncreated={time.time()}\n")
        self._acquired = True
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        if self._acquired:
            self._lock_file.unlink(missing_ok=True)
            self._acquired = False

    def _remove_stale_lock(self) -> None:
        try:
            age = time.time() - self._lock_file.stat().st_mtime
        except FileNotFoundError:
            return
        if age > 1800:
            self._lock_file.unlink(missing_ok=True)


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
