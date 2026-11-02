import os
import json
import logging
import subprocess
import threading
import time
from pathlib import Path
from urllib.request import Request, urlopen

from app.config import PROJECT_ROOT, ShellSettings
from app.gateway_process_log import GatewayProcessLog, configure_gateway_logging
from app.port_probe import is_port_open
from app.process_security import ProcessSecurity
from app.startup_timing import mark, timed_stage


GATEWAY_STARTUP_TIMEOUT_SECONDS = 20.0
GATEWAY_STOP_TIMEOUT_SECONDS = 8.0
logger = logging.getLogger(__name__)


class GatewayProcessManager:
    def __init__(self, settings: ShellSettings, security: ProcessSecurity) -> None:
        self._settings = settings
        self._security = security
        self._process: subprocess.Popen[bytes] | None = None
        self._log: GatewayProcessLog | None = None
        self._lock = threading.Lock()

    def ensure_running(self) -> None:
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                return
            if self._log is not None:
                if not self._log.finish():
                    raise RuntimeError("Previous gateway diagnostic output has not closed.")
                self._log = None
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
            configure_gateway_logging(env)
            self._log = GatewayProcessLog(PROJECT_ROOT / "Data" / "logs" / "gateway.log")
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
            try:
                with timed_stage("gateway process: start"):
                    self._process = subprocess.Popen(
                        [str(executable)],
                        cwd=str(executable.parent),
                        env=env,
                        creationflags=creationflags,
                        stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        bufsize=0,
                    )
                    assert self._process.stdout is not None
                    self._log.start(self._process.stdout)
                    assert self._process.stdin is not None
                    self._process.stdin.write(self._security.gateway_bootstrap())
                    self._process.stdin.close()
                self._wait_until_ready()
            except BaseException:
                try:
                    _stop_gateway_process(self._process)
                finally:
                    self._log.finish()
                    self._process = None
                raise
            mark("gateway process: started", pid=self._process.pid)

    def stop(self) -> None:
        with self._lock:
            process = self._process
            log = self._log
            try:
                _stop_gateway_process(process)
            finally:
                if process is None or process.poll() is not None:
                    self._process = None
                if log is not None and not log.finish():
                    # Keep the collector reference so a new start cannot race it.
                    logger.warning("Gateway exited but diagnostic output has not closed.")
                else:
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
                        if json.load(response).get("security_protocol") == 2:
                            return
                        raise RuntimeError("访问网关程序与桌面壳版本不一致，请重新构建访问网关。")
            except OSError:
                time.sleep(0.1)
        raise RuntimeError(f"Tiance remote gateway did not become ready: {health_url}")


def _stop_gateway_process(process: subprocess.Popen[bytes] | None) -> None:
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=GATEWAY_STOP_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)
