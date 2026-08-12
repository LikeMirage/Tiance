import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import BinaryIO
from urllib.parse import urlparse

from app.backend_watchdog import (
    BackendHealthMonitor,
    ShellLease,
    ShellLeaseServer,
    build_managed_backend_environment,
)
from app.backend_process_log import backend_log_path, open_backend_process_log
from app.backend_runtime_record import (
    clear_managed_backend_record,
    record_managed_backend,
)
from app.config import PROJECT_ROOT, ShellSettings
from app.port_probe import is_port_open
from app.startup_timing import mark, timed_stage


PYTHON_ENVIRONMENT_KEYS_TO_CLEAR = (
    "PYTHONHOME",
    "PYTHONPATH",
    "VIRTUAL_ENV",
    "CONDA_PREFIX",
    "CONDA_DEFAULT_ENV",
)
SHELL_DEFAULT_ALLOWED_ORIGINS = ("https://pywebview.flowrl.com",)


class BackendProcessManager:
    def __init__(self, settings: ShellSettings) -> None:
        self._settings = settings
        self._process: subprocess.Popen[bytes] | None = None
        self._started_by_shell = False
        self._lease_server = ShellLeaseServer()
        self._health_monitor: BackendHealthMonitor | None = None
        self._backend_log: BinaryIO | None = None
        self._on_backend_unavailable: Callable[[str], None] | None = None
        self._stopping = False
        self._lock = threading.Lock()

    @property
    def started_by_shell(self) -> bool:
        return self._started_by_shell

    def set_backend_unavailable_callback(self, callback: Callable[[str], None]) -> None:
        self._on_backend_unavailable = callback

    def ensure_running(self) -> None:
        with self._lock:
            process = self._process
            if process is not None:
                returncode = process.poll()
                if returncode is None:
                    mark("backend process: already managed", pid=process.pid)
                    return
                self._process = None
                self._stop_health_monitor()
                self._close_backend_log()
                clear_managed_backend_record(PROJECT_ROOT, pid=process.pid)
                mark(
                    "backend process: previous attempt exited",
                    pid=process.pid,
                    returncode=returncode,
                    log=backend_log_path(PROJECT_ROOT),
                )

            if not self._settings.manage_backend:
                mark("backend process: management disabled")
                if is_port_open(self._settings.api_host, self._settings.api_port):
                    return
                raise RuntimeError(
                    "Backend management is disabled and no backend is listening at "
                    f"{self._settings.api_url}."
                )

            if is_port_open(self._settings.api_host, self._settings.api_port):
                raise RuntimeError(
                    "Selected API port became occupied before backend startup: "
                    f"{self._settings.api_host}:{self._settings.api_port}"
                )

            backend_run_file = PROJECT_ROOT / "1_PythonServer" / "run.py"
            if not backend_run_file.is_file():
                mark("backend process: run.py missing", path=backend_run_file)
                raise FileNotFoundError(f"Backend entry is missing: {backend_run_file}")

            lease = self._lease_server.start()
            env = _build_backend_environment(self._settings, lease)

            creationflags = 0
            if os.name == "nt":
                creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

            with timed_stage("backend process: start"):
                backend_log: BinaryIO | None = None
                try:
                    backend_log = open_backend_process_log(PROJECT_ROOT)
                    process = subprocess.Popen(
                        [_resolve_backend_python_executable(), str(backend_run_file)],
                        cwd=str(backend_run_file.parent),
                        env=env,
                        creationflags=creationflags,
                        stdout=backend_log,
                        stderr=subprocess.STDOUT,
                    )
                except Exception:
                    if backend_log is not None:
                        backend_log.close()
                    self._lease_server.stop()
                    raise
                self._process = process
                self._backend_log = backend_log
                self._stopping = False
                self._started_by_shell = True
            record_managed_backend(
                PROJECT_ROOT,
                pid=process.pid,
                instance_id=lease.instance_id,
                api_url=self._settings.api_url,
            )
            mark("backend process: started", pid=process.pid)

            process = self._process
            if process is None:  # pragma: no cover - assigned by Popen above
                raise RuntimeError("Managed backend process was not created")
            monitor = BackendHealthMonitor(
                process=process,
                api_url=self._settings.api_url,
                instance_id=lease.instance_id,
                on_unavailable=lambda reason: self._handle_backend_unavailable(
                    process,
                    reason,
                ),
            )
            self._health_monitor = monitor
            monitor.start()

    def stop(self) -> None:
        with self._lock:
            self._stopping = True
            process = self._process
            self._process = None
            monitor = self._health_monitor
            self._health_monitor = None

        if monitor is not None:
            monitor.stop()

        if process is not None:
            if process.poll() is None:
                with timed_stage("backend process: stop", pid=process.pid):
                    if os.name == "nt":
                        # Kill the managed tree while its root still exists. If
                        # the root exits first, Windows can no longer discover
                        # its orphaned multiprocessing children.
                        _kill_process_tree(process)
                    else:
                        process.terminate()
                    deadline = time.monotonic() + 5
                    while process.poll() is None and time.monotonic() < deadline:
                        time.sleep(0.1)
                    if process.poll() is None:
                        _kill_process_tree(process)
                    mark("backend process: stopped", returncode=process.poll())
            if process.poll() is not None:
                clear_managed_backend_record(PROJECT_ROOT, pid=process.pid)

        self._lease_server.stop()
        self._close_backend_log()

    def _stop_health_monitor(self) -> None:
        monitor = self._health_monitor
        self._health_monitor = None
        if monitor is not None:
            monitor.stop()

    def _close_backend_log(self) -> None:
        backend_log = self._backend_log
        self._backend_log = None
        if backend_log is not None:
            backend_log.close()

    def _handle_backend_unavailable(
        self,
        process: subprocess.Popen[bytes],
        reason: str,
    ) -> None:
        if self._stopping or self._process is not process:
            return
        mark("backend process: unavailable", pid=process.pid, reason=reason)
        callback = self._on_backend_unavailable
        if callback is not None:
            callback(reason)


def _build_backend_environment(settings: ShellSettings, lease: ShellLease) -> dict[str, str]:
    env = os.environ.copy()
    for key in PYTHON_ENVIRONMENT_KEYS_TO_CLEAR:
        env.pop(key, None)

    env["PYTHONNOUSERSITE"] = "1"
    env["TIANCE_API_HOST"] = settings.api_host
    env["TIANCE_API_PORT"] = str(settings.api_port)
    env["TIANCE_API_RELOAD"] = "false"
    env["TIANCE_API_USE_EMBEDDED_PYTHON"] = "true"
    env["TIANCE_SHELL_PARENT_PID"] = str(os.getpid())
    env["ALLOWED_ORIGINS"] = _merge_allowed_origins(
        env.get("ALLOWED_ORIGINS"),
        _frontend_dev_origins(settings.dev_url),
    )
    return build_managed_backend_environment(env, lease)


def _frontend_dev_origins(dev_url: str) -> tuple[str, ...]:
    try:
        parsed = urlparse(dev_url)
        port = parsed.port
    except ValueError:
        return ()
    if parsed.scheme not in {"http", "https"} or port is None:
        return ()
    if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        return ()

    origins = [f"{parsed.scheme}://{parsed.hostname}:{port}"]
    if parsed.hostname in {"127.0.0.1", "localhost"}:
        origins.extend(
            [
                f"{parsed.scheme}://127.0.0.1:{port}",
                f"{parsed.scheme}://localhost:{port}",
            ]
        )
    return tuple(dict.fromkeys(origins))


def _merge_allowed_origins(
    configured_origins: str | None,
    frontend_origins: tuple[str, ...],
) -> str:
    configured = [
        origin.strip()
        for origin in (configured_origins or "").split(",")
        if origin.strip()
    ]
    return ",".join(
        dict.fromkeys([*configured, *frontend_origins, *SHELL_DEFAULT_ALLOWED_ORIGINS])
    )


def _resolve_backend_python_executable() -> str:
    current_python = Path(sys.executable)
    if os.name == "nt" and current_python.name.lower() == "pythonw.exe":
        console_python = current_python.with_name("python.exe")
        if console_python.is_file():
            return str(console_python)

    return str(current_python)


def _kill_process_tree(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return

    if os.name == "nt":
        try:
            completed = subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                timeout=5,
            )
            if completed.returncode == 0:
                return
        except Exception:
            pass

    try:
        process.kill()
    except Exception:
        pass
