import os
import platform
import subprocess
import sys
from pathlib import Path


SHELL_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = SHELL_ROOT.parent
RUNTIME_ROOT = PROJECT_ROOT / "runtime"
WINDOWS_EMBEDDED_PYTHON = RUNTIME_ROOT / "python" / "py313" / "python.exe"
WINDOWS_EMBEDDED_PYTHONW = RUNTIME_ROOT / "python" / "py313" / "pythonw.exe"
LEGACY_POSIX_EMBEDDED_PYTHON = RUNTIME_ROOT / "python" / "py313" / "python"


def _read_bool_env(name: str, *, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _is_current_python(python_path: Path) -> bool:
    current = Path(sys.executable)
    try:
        return current.samefile(python_path)
    except OSError:
        return current.resolve() == python_path.resolve()


def _is_current_embedded_python() -> bool:
    return any(_is_current_python(candidate) for candidate in _embedded_python_candidates())


def _embedded_python_candidates() -> list[Path]:
    if os.name == "nt":
        return [WINDOWS_EMBEDDED_PYTHON, WINDOWS_EMBEDDED_PYTHONW]

    candidates: list[Path] = []
    runtime_segment = _runtime_platform_segment()
    if runtime_segment:
        candidates.extend(
            [
                RUNTIME_ROOT / "python" / runtime_segment / "py313" / "bin" / "python3",
                RUNTIME_ROOT / "python" / runtime_segment / "py313" / "bin" / "python",
            ]
        )
    candidates.append(LEGACY_POSIX_EMBEDDED_PYTHON)
    return candidates


def _embedded_python_for_reexec() -> Path | None:
    for candidate in _embedded_python_candidates():
        if candidate.is_file():
            return candidate
    return None


def _runtime_platform_segment() -> str | None:
    if sys.platform == "darwin":
        machine = platform.machine().lower()
        if machine == "arm64":
            return "macos-arm64"
        if machine in {"x86_64", "amd64"}:
            return "macos-x64"
    return None


def _resolve_site_packages_path(package_group: str) -> Path:
    runtime_segment = _runtime_platform_segment()
    if runtime_segment:
        candidate = (
            RUNTIME_ROOT
            / "python-packages"
            / package_group
            / runtime_segment
            / "py313"
            / "site-packages"
        )
        if candidate.is_dir():
            return candidate

    return RUNTIME_ROOT / "python-packages" / package_group / "py313" / "site-packages"


def _activate_shell_path() -> None:
    shell_root = str(SHELL_ROOT)
    if shell_root not in sys.path:
        sys.path.insert(0, shell_root)


def _maybe_reexec_with_embedded_python() -> None:
    from app.startup_timing import mark

    if not _read_bool_env("TIANCE_SHELL_USE_EMBEDDED_PYTHON", default=True):
        mark("embedded python: disabled by env")
        return
    embedded_python = _embedded_python_for_reexec()
    if embedded_python is None:
        mark("embedded python: not found")
        return
    if _is_current_embedded_python():
        mark("embedded python: already active", path=sys.executable)
        return

    mark("embedded python: reexec", path=embedded_python)
    if os.name == "nt":
        completed = subprocess.run(
            [str(embedded_python), str(Path(__file__).resolve()), *sys.argv[1:]]
        )
        raise SystemExit(completed.returncode)

    os.execv(
        str(embedded_python),
        [str(embedded_python), str(Path(__file__).resolve()), *sys.argv[1:]],
    )


def _activate_desktop_shell_dependencies() -> None:
    from app.startup_timing import mark

    if not _is_current_embedded_python():
        mark("desktop shell dependencies: skipped for non-embedded python")
        return
    desktop_shell_site_packages = str(_resolve_site_packages_path("desktop-shell"))
    if desktop_shell_site_packages not in sys.path:
        sys.path.insert(0, desktop_shell_site_packages)
        mark("desktop shell dependencies: site-packages inserted", path=desktop_shell_site_packages)
        return

    mark("desktop shell dependencies: already active", path=desktop_shell_site_packages)


if __name__ == "__main__":
    _activate_shell_path()

    from app.startup_timing import ensure_start_time_env, mark, timed_stage

    ensure_start_time_env()
    mark("run.py: entered", python=sys.executable)

    with timed_stage("embedded python check"):
        _maybe_reexec_with_embedded_python()

    with timed_stage("activate desktop shell dependencies"):
        _activate_desktop_shell_dependencies()

    with timed_stage("acquire single instance lock"):
        from app.single_instance import acquire_single_instance_lock, notify_existing_instance

        single_instance_lock = acquire_single_instance_lock(PROJECT_ROOT)
        if single_instance_lock is None:
            notify_existing_instance(PROJECT_ROOT)
            raise SystemExit(0)

    with timed_stage("import app.main"):
        from app.main import main

    print(f"Tiance Shell Python: {sys.executable}", flush=True)
    mark("run.py: starting main")
    try:
        main()
    finally:
        single_instance_lock.close()
