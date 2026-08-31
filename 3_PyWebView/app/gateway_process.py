import os
import subprocess
import threading
import time
from pathlib import Path
from typing import BinaryIO
from urllib.request import Request, urlopen

from app.config import PROJECT_ROOT, ShellSettings
from app.port_probe import is_port_open
from app.startup_timing import mark, timed_stage


GATEWAY_STARTUP_TIMEOUT_SECONDS = 20.0
GATEWAY_STOP_TIMEOUT_SECONDS = 8.0


class GatewayProcessManager:
    def __init__(self, settings: ShellSettings) -> None:
        self._settings = settings
        self._process: subprocess.Popen[bytes] | None = None
        self._log: BinaryIO | None = None
        self._lock = threading.Lock()

    def ensure_running(self) -> None:
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                return
            if is_port_open(self._settings.api_host, self._settings.api_port):
                raise RuntimeError(
                    "Selected gateway port became occupied before startup: "
                    f"{self._settings.api_host}:{self._settings.api_port}"
                )
            executable = Path(self._settings.gateway_executable_path)
            if not executable.is_file():
                raise FileNotFoundError(
                    "Tiance remote gateway is missing. Build it with "
                    "scripts/build-remote-gateway.ps1. "
                    f"Expected: {executable}"
                )
            env = os.environ.copy()
            env.update(
                {
                    "TIANCE_GATEWAY_HOST": self._settings.gateway_listen_host,
                    "TIANCE_GATEWAY_PORT": str(self._settings.api_port),
                    "TIANCE_BACKEND_URL": self._settings.backend_url,
                    "TIANCE_DATA_ROOT": str(PROJECT_ROOT / "Data"),
                    "TIANCE_EXTERNAL_ACCESS_ENABLED": (
                        "true" if self._settings.external_access_enabled else "false"
                    ),
                    "TIANCE_FRONTEND_DEV_URL": self._settings.dev_url,
                }
            )
            log_path = PROJECT_ROOT / "Data" / "logs" / "gateway.log"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            self._log = log_path.open("ab", buffering=0)
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
            with timed_stage("gateway process: start"):
                self._process = subprocess.Popen(
                    [str(executable)],
                    cwd=str(executable.parent),
                    env=env,
                    creationflags=creationflags,
                    stdout=self._log,
                    stderr=subprocess.STDOUT,
                )
            self._wait_until_ready()
            mark("gateway process: started", pid=self._process.pid)

    def stop(self) -> None:
        with self._lock:
            process = self._process
            self._process = None
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=GATEWAY_STOP_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        if self._log is not None:
            self._log.close()
            self._log = None

    def _wait_until_ready(self) -> None:
        deadline = time.monotonic() + GATEWAY_STARTUP_TIMEOUT_SECONDS
        health_url = f"{self._settings.api_url}/gateway/health"
        while time.monotonic() < deadline:
            process = self._process
            if process is None or process.poll() is not None:
                raise RuntimeError("Tiance remote gateway exited during startup.")
            try:
                with urlopen(Request(health_url, method="GET"), timeout=0.5) as response:
                    if response.status == 200:
                        return
            except OSError:
                time.sleep(0.1)
        raise RuntimeError(f"Tiance remote gateway did not become ready: {health_url}")
