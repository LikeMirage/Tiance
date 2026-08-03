from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path


_SCRIPT_LAUNCHER = """
import os
import runpy
import sys

script_path = sys.argv[1]
path_count = int(sys.argv[2])
import_paths = sys.argv[3:3 + path_count]
script_args = sys.argv[3 + path_count:]
for import_path in reversed(import_paths):
    if import_path and import_path not in sys.path:
        sys.path.insert(0, import_path)
from child_process_control import ChildProcessControl

sys.argv = [script_path, *script_args]
lease_file = os.environ.pop("TIANCE_PYTHON_PROCESS_LEASE_FILE", "")
control = ChildProcessControl.from_environment(lease_file)
exit_code = 0
try:
    control.start()
    runpy.run_path(script_path, run_name="__main__")
except SystemExit as exc:
    exit_code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
    raise
except KeyboardInterrupt:
    exit_code = 130
    raise
except BaseException:
    exit_code = 1
    raise
finally:
    control.finish(exit_code)
""".strip()

_INHERITED_ENV_KEYS = {
    "COMSPEC",
    "PATH",
    "PATHEXT",
    "SystemRoot",
    "TEMP",
    "TMP",
    "WINDIR",
    "PYTHONPATH",
    "PYTHONIOENCODING",
    "TIANCE_WORKSPACE_ROOT",
    "TIANCE_PROJECT_ID",
    "TIANCE_SESSION_ID",
}


class PythonRuntimeError(RuntimeError):
    def __init__(self, code: str, message: str, details: dict[str, str] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


@dataclass(frozen=True, slots=True)
class PythonRuntime:
    environment: dict[str, str]
    import_paths: tuple[Path, ...]
    dependency_site_packages: Path | None


@dataclass(slots=True)
class EnvironmentLease:
    path: Path | None

    def release(self) -> None:
        if self.path is None:
            return
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            pass
        self.path = None

    def __enter__(self) -> "EnvironmentLease":
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.release()


@dataclass(frozen=True, slots=True)
class ScriptRunResult:
    exit_code: int | None
    stderr: str
    stdout: str
    timed_out: bool


def resolve_tool_dependencies_root() -> Path:
    return Path(__file__).resolve().parents[1] / "dependencies" / "py313"


def resolve_dependency_site_packages_path() -> Path:
    dependencies_root = resolve_tool_dependencies_root()
    _migrate_legacy_shared_environment(dependencies_root)
    legacy_directory = dependencies_root / "site-packages"
    pointer_file = dependencies_root / "active.json"
    if not pointer_file.is_file():
        return legacy_directory
    try:
        payload = json.loads(pointer_file.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PythonRuntimeError(
            "ACTIVE_ENVIRONMENT_INVALID",
            "Python 脚本工具依赖活动环境记录损坏。",
            {"pointer_file": str(pointer_file)},
        ) from exc
    relative_value = payload.get("site_packages") if isinstance(payload, dict) else None
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != 1
        or not isinstance(relative_value, str)
        or not relative_value.strip()
    ):
        raise PythonRuntimeError(
            "ACTIVE_ENVIRONMENT_INVALID",
            "Python 脚本工具依赖活动环境记录无效。",
            {"pointer_file": str(pointer_file)},
        )
    root = dependencies_root.resolve()
    relative_path = Path(relative_value)
    site_packages = (root / relative_path).resolve()
    try:
        site_packages.relative_to(root)
    except ValueError as exc:
        raise PythonRuntimeError(
            "ACTIVE_ENVIRONMENT_INVALID",
            "Python 脚本工具依赖活动环境路径越出存储目录。",
            {"pointer_file": str(pointer_file)},
        ) from exc
    if relative_path.is_absolute() or not site_packages.is_dir():
        raise PythonRuntimeError(
            "ACTIVE_ENVIRONMENT_MISSING",
            "Python 脚本工具依赖活动环境不存在。",
            {"target_directory": str(site_packages)},
        )
    return site_packages


@contextmanager
def prepared_runtime(workdir: Path, extra_env: dict[str, str]) -> Iterator[PythonRuntime]:
    with acquire_environment_lease():
        yield build_runtime(workdir, extra_env)


def acquire_environment_lease() -> EnvironmentLease:
    dependencies_root = resolve_tool_dependencies_root()
    _migrate_legacy_shared_environment(dependencies_root)
    if not (dependencies_root / "active.json").is_file():
        return EnvironmentLease(None)
    leases_root = dependencies_root / "leases"
    lease_file = leases_root / f"lease-{uuid.uuid4().hex}.json"
    try:
        leases_root.mkdir(parents=True, exist_ok=True)
        lease_file.write_text(
            json.dumps({"pid": os.getpid(), "created_at": time.time()}, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        raise PythonRuntimeError(
            "DEPENDENCY_ENVIRONMENT_LEASE_FAILED",
            "无法锁定当前 Python 脚本工具依赖环境。",
            {"lease_file": str(lease_file)},
        ) from exc
    return EnvironmentLease(lease_file)


def build_runtime(workdir: Path, extra_env: dict[str, str]) -> PythonRuntime:
    environment = {
        key: value
        for key in _INHERITED_ENV_KEYS
        if (value := os.environ.get(key))
    }
    environment.update(extra_env)

    inherited_pythonpath = environment.pop("PYTHONPATH", "")
    import_paths: list[Path] = [workdir]
    dependency_site_packages = resolve_dependency_site_packages_path()
    if dependency_site_packages.is_dir():
        import_paths.append(dependency_site_packages)
    import_paths.extend(Path(path) for path in inherited_pythonpath.split(os.pathsep) if path)
    environment["PYTHONIOENCODING"] = "utf-8"
    return PythonRuntime(
        environment=environment,
        import_paths=_unique_paths(import_paths),
        dependency_site_packages=(
            dependency_site_packages if dependency_site_packages.is_dir() else None
        ),
    )


def resolve_embedded_runtime_root(
    python_executable: str | Path | None = None,
) -> Path | None:
    executable = Path(python_executable or sys.executable).resolve()
    if executable.parent.name != "py313" or executable.parent.parent.name != "python":
        return None
    runtime_root = executable.parents[2]
    return runtime_root if runtime_root.name == "runtime" else None


def run_script(
    script_path: Path,
    args: list[str],
    *,
    stdin_text: str | None,
    workdir: Path,
    runtime: PythonRuntime,
    timeout: int,
) -> ScriptRunResult:
    command = build_script_command(script_path, args, runtime=runtime)
    try:
        completed = subprocess.run(
            command,
            input=stdin_text,
            cwd=str(workdir),
            env=runtime.environment,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        return ScriptRunResult(
            exit_code=completed.returncode,
            stderr=completed.stderr or "",
            stdout=completed.stdout or "",
            timed_out=False,
        )
    except subprocess.TimeoutExpired as exc:
        stderr = _timeout_output(exc.stderr)
        if stderr and not stderr.endswith("\n"):
            stderr += "\n"
        return ScriptRunResult(
            exit_code=None,
            stdout=_timeout_output(exc.stdout),
            stderr=stderr + f"脚本执行超过 {timeout} 秒，已停止。",
            timed_out=True,
        )


def build_script_command(
    script_path: Path,
    args: list[str],
    *,
    runtime: PythonRuntime,
) -> list[str]:
    import_paths = _unique_paths(
        [script_path.parent, Path(__file__).resolve().parent, *runtime.import_paths]
    )
    return [
        sys.executable,
        "-c",
        _SCRIPT_LAUNCHER,
        str(script_path),
        str(len(import_paths)),
        *[str(path) for path in import_paths],
        *args,
    ]


def _migrate_legacy_shared_environment(target_root: Path) -> None:
    runtime_root = resolve_embedded_runtime_root()
    if runtime_root is None:
        return
    legacy_root = runtime_root / "python-packages" / "user" / "py313"
    if not legacy_root.exists():
        return
    if target_root.exists() and any(target_root.iterdir()):
        raise PythonRuntimeError(
            "LEGACY_ENVIRONMENT_CONFLICT",
            "旧共享脚本依赖与 Python 脚本工具依赖同时存在，已停止迁移以避免覆盖。",
            {"legacy_root": str(legacy_root), "target_root": str(target_root)},
        )
    target_root.parent.mkdir(parents=True, exist_ok=True)
    if target_root.exists():
        target_root.rmdir()
    try:
        os.replace(legacy_root, target_root)
    except OSError:
        try:
            shutil.copytree(legacy_root, target_root)
            shutil.rmtree(legacy_root)
        except (OSError, shutil.Error) as exc:
            raise PythonRuntimeError(
                "LEGACY_ENVIRONMENT_MIGRATION_FAILED",
                "无法把旧共享脚本依赖迁入 Python 脚本执行工具。",
                {"legacy_root": str(legacy_root), "target_root": str(target_root)},
            ) from exc
    _remove_empty_parents(legacy_root.parent, runtime_root / "python-packages")


def _remove_empty_parents(path: Path, stop: Path) -> None:
    current = path
    while current != stop:
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent


def _unique_paths(paths: list[Path]) -> tuple[Path, ...]:
    unique: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = os.path.normcase(str(path.resolve(strict=False)))
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return tuple(unique)


def _timeout_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value
