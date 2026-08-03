# 开发服务器启动入口
# 通过 uvicorn 启动 FastAPI 应用，支持热重载和自定义主机/端口

import os
import platform
import subprocess
import sys
import threading
import time
from pathlib import Path

API_SERVER_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = API_SERVER_ROOT.parent
RUNTIME_ROOT = PROJECT_ROOT / "Data" / "runtime"
WINDOWS_EMBEDDED_PYTHON = RUNTIME_ROOT / "python" / "py313" / "python.exe"
WINDOWS_EMBEDDED_PYTHONW = RUNTIME_ROOT / "python" / "py313" / "pythonw.exe"
LEGACY_POSIX_EMBEDDED_PYTHON = RUNTIME_ROOT / "python" / "py313" / "python"
DEFAULT_API_PORT = 18000
SHELL_PARENT_PID_ENV = "TIANCE_SHELL_PARENT_PID"


def _read_bool_env(name: str, *, default: bool) -> bool:
    """读取布尔类型环境变量，识别 1/true/yes/on 为真值"""

    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _read_int_env(name: str, *, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value.strip())
    except ValueError:
        return default


def _read_optional_int_env(name: str) -> int | None:
    value = os.getenv(name)
    if value is None:
        return None
    try:
        parsed = int(value.strip())
    except ValueError:
        return None
    return parsed if parsed > 0 else None


def _is_current_python(python_path: Path) -> bool:
    current = Path(sys.executable)
    try:
        return current.samefile(python_path)
    except OSError:
        return current.resolve() == python_path.resolve()


def _is_current_embedded_python() -> bool:
    return any(_is_current_python(candidate) for candidate in _embedded_python_candidates())


def _runtime_platform_segment() -> str | None:
    if sys.platform == "darwin":
        machine = platform.machine().lower()
        if machine == "arm64":
            return "macos-arm64"
        if machine in {"x86_64", "amd64"}:
            return "macos-x64"
    return None


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


def _maybe_reexec_with_embedded_python() -> None:
    if not _read_bool_env("TIANCE_API_USE_EMBEDDED_PYTHON", default=True):
        return
    embedded_python = _embedded_python_for_reexec()
    if embedded_python is None:
        return
    if _is_current_embedded_python():
        return

    if os.name == "nt":
        completed = subprocess.run(
            [str(embedded_python), str(Path(__file__).resolve()), *sys.argv[1:]]
        )
        raise SystemExit(completed.returncode)

    os.execv(
        str(embedded_python),
        [str(embedded_python), str(Path(__file__).resolve()), *sys.argv[1:]],
    )


def _activate_backend_dependencies() -> None:
    if not _is_current_embedded_python():
        return
    backend_site_packages = str(_resolve_site_packages_path("backend"))
    if backend_site_packages not in sys.path:
        sys.path.insert(0, backend_site_packages)


def _load_uvicorn_runtime():
    """Load stable Uvicorn implementation modules instead of package re-exports."""

    from uvicorn.config import Config
    from uvicorn.main import run
    from uvicorn.server import Server

    return Config, Server, run


def _windows_process_handle(pid: int):
    if os.name != "nt":
        return None

    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    open_process = kernel32.OpenProcess
    open_process.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    open_process.restype = wintypes.HANDLE
    handle = open_process(0x00100000, False, pid)
    return handle or None


def _close_windows_handle(handle) -> None:
    if os.name != "nt" or not handle:
        return

    import ctypes

    ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle(handle)


def _wait_for_windows_process_exit(handle, stop_requested) -> bool:
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    wait_for_single_object = kernel32.WaitForSingleObject
    wait_for_single_object.argtypes = [ctypes.wintypes.HANDLE, ctypes.wintypes.DWORD]
    wait_for_single_object.restype = ctypes.wintypes.DWORD
    wait_object_0 = 0x00000000
    wait_timeout = 0x00000102
    wait_failed = 0xFFFFFFFF

    while not stop_requested():
        result = wait_for_single_object(handle, 1000)
        if result == wait_object_0:
            return True
        if result == wait_failed:
            return True
        if result != wait_timeout:
            return True
    return False


def _process_exists(pid: int) -> bool:
    if pid == os.getpid():
        return True

    if os.name == "nt":
        handle = _windows_process_handle(pid)
        if not handle:
            return False
        _close_windows_handle(handle)
        return True

    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _start_shell_parent_monitor(server, parent_pid: int) -> None:
    def request_shutdown() -> None:
        print("Tiance API: desktop shell exited; shutting down backend.", flush=True)
        server.should_exit = True

    def monitor() -> None:
        if os.name == "nt":
            handle = _windows_process_handle(parent_pid)
            if not handle:
                request_shutdown()
                return
            try:
                if _wait_for_windows_process_exit(handle, lambda: server.should_exit):
                    request_shutdown()
            finally:
                _close_windows_handle(handle)
            return

        while not server.should_exit:
            if not _process_exists(parent_pid):
                request_shutdown()
                return
            time.sleep(1)

    thread = threading.Thread(
        target=monitor,
        name="tiance-shell-parent-monitor",
        daemon=True,
    )
    thread.start()


if __name__ == "__main__":
    _maybe_reexec_with_embedded_python()
    _activate_backend_dependencies()

    if sys.version_info < (3, 11):
        raise SystemExit(
            "Python 3.11+ is required. Use the embedded runtime at "
            "`runtime/python/py313/python.exe`."
        )

    UvicornConfig, UvicornServer, run_uvicorn = _load_uvicorn_runtime()

    # Uvicorn 的 WatchFiles reloader 会额外监听当前工作目录。
    # 允许用户从仓库任意位置用绝对路径启动，但实际监听范围收口到 api-server。
    os.chdir(API_SERVER_ROOT)
    api_server_root_path = str(API_SERVER_ROOT)
    if api_server_root_path not in sys.path:
        sys.path.insert(0, api_server_root_path)
    print(f"Tiance API Python: {sys.executable}")

    reload_enabled = _read_bool_env(
        "TIANCE_API_RELOAD",
        default=True,
    )
    host = os.getenv("TIANCE_API_HOST", "127.0.0.1")
    port = int(os.getenv("TIANCE_API_PORT", str(DEFAULT_API_PORT)))
    graceful_shutdown_timeout = _read_int_env(
        "TIANCE_API_GRACEFUL_SHUTDOWN_TIMEOUT",
        default=5,
    )
    shell_parent_pid = _read_optional_int_env(SHELL_PARENT_PID_ENV)

    if not reload_enabled:
        from app.core.shell_lease import start_shell_lease_monitor

        config = UvicornConfig(
            "app.main:app",
            host=host,
            port=port,
            reload=False,
            timeout_graceful_shutdown=graceful_shutdown_timeout,
        )
        server = UvicornServer(config)
        if shell_parent_pid is not None:
            _start_shell_parent_monitor(server, shell_parent_pid)
        lease_monitor = start_shell_lease_monitor(server)
        try:
            server.run()
        finally:
            if lease_monitor is not None:
                lease_monitor.stop()
    else:
        run_uvicorn(
            "app.main:app",
            host=host,
            port=port,
            reload=reload_enabled,
            reload_dirs=[str(API_SERVER_ROOT / "app")] if reload_enabled else None,
            timeout_graceful_shutdown=graceful_shutdown_timeout,
            app_dir=str(API_SERVER_ROOT),
        )
