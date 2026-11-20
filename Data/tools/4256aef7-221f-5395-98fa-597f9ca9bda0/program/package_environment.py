from __future__ import annotations

import errno
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
        tools_root=runtime_root.parent / "Data" / "tools",
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
        self._root = packages_root
        self._handle = None

    def __enter__(self) -> "EnvironmentLock":
        self._root.mkdir(parents=True, exist_ok=True)
        # Keep a stable inode. Closing the handle (including process death)
        # releases the OS lock; removing its file would race other openers.
        handle = (self._root / ".package-manager.guard").open("a+b")
        try:
            handle.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                    raise
                raise self._busy() from exc
            self._recover_legacy_lock()
        except BaseException:
            handle.close()
            raise
        self._handle = handle
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None

    def _busy(self) -> EnvironmentError:
        return EnvironmentError("ENVIRONMENT_BUSY", "同一 Python 依赖目录正被另一项依赖操作占用，请在该操作结束后重试。",
                                {"environment_root": str(self._root)})

    def _recover_legacy_lock(self) -> None:
        marker = self._root / ".package-manager.lock"
        try:
            with marker.open("rb") as handle:
                age = time.time() - os.fstat(handle.fileno()).st_mtime
                first_line = handle.readline(64).strip()
        except FileNotFoundError:
            return
        pid = first_line.removeprefix(b"pid=")
        if first_line.startswith(b"pid=") and pid.isdigit() and 0 < int(pid) <= 0x7fffffff:
            if _legacy_owner_alive(int(pid)):
                raise self._busy()
        elif age < 1800:
            # An old process may still be writing the marker.
            raise EnvironmentError("ENVIRONMENT_BUSY", "旧版依赖锁缺少有效的进程信息，暂时无法确认占用状态。",
                                   {"environment_root": str(self._root)})
        marker.unlink(missing_ok=True)


def _legacy_owner_alive(pid: int) -> bool:
    if os.name == "nt":
        import _winapi
        try:
            handle = _winapi.OpenProcess(_winapi.SYNCHRONIZE, False, pid)
        except PermissionError:
            return True
        except OSError as exc:
            if exc.winerror == 87:  # ERROR_INVALID_PARAMETER for a nonexistent PID
                return False
            raise
        try:
            return _winapi.WaitForSingleObject(handle, 0) == _winapi.WAIT_TIMEOUT
        finally:
            _winapi.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
