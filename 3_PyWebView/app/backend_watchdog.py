from __future__ import annotations

import hmac
import json
import secrets
import threading
import uuid
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Protocol, cast
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener


LEASE_HEARTBEAT_PATH = "/heartbeat"
LEASE_INSTANCE_HEADER = "X-Tiance-Instance-Id"
LEASE_TOKEN_HEADER = "X-Tiance-Lease-Token"
DEFAULT_HEALTH_INTERVAL_SECONDS = 2.0
DEFAULT_HEALTH_TIMEOUT_SECONDS = 1.0
DEFAULT_HEALTH_FAILURE_THRESHOLD = 3


class ProcessHandle(Protocol):
    def poll(self) -> int | None: ...


@dataclass(frozen=True)
class ShellLease:
    instance_id: str
    token: str
    heartbeat_url: str


@dataclass
class BackendHealthState:
    failure_threshold: int = DEFAULT_HEALTH_FAILURE_THRESHOLD
    ready: bool = False
    consecutive_failures: int = 0

    def observe(self, available: bool) -> bool:
        if available:
            self.ready = True
            self.consecutive_failures = 0
            return False

        if not self.ready:
            return False

        self.consecutive_failures += 1
        return self.consecutive_failures >= self.failure_threshold


class ShellLeaseServer:
    """Loopback-only lease endpoint owned by the desktop shell process."""

    def __init__(self) -> None:
        self._instance_id = uuid.uuid4().hex
        self._token = secrets.token_urlsafe(32)
        self._server: _LeaseHttpServer | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def start(self) -> ShellLease:
        with self._lock:
            if self._server is None:
                server = _LeaseHttpServer(
                    ("127.0.0.1", 0),
                    instance_id=self._instance_id,
                    token=self._token,
                )
                thread = threading.Thread(
                    target=server.serve_forever,
                    name="tiance-shell-lease-server",
                    daemon=True,
                )
                thread.start()
                self._server = server
                self._thread = thread

            server = self._server
            port = int(server.server_address[1])
            return ShellLease(
                instance_id=self._instance_id,
                token=self._token,
                heartbeat_url=f"http://127.0.0.1:{port}{LEASE_HEARTBEAT_PATH}",
            )

    def stop(self) -> None:
        with self._lock:
            server = self._server
            thread = self._thread
            self._server = None
            self._thread = None

        if server is None:
            return

        server.shutdown()
        server.server_close()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2)


class BackendHealthMonitor:
    """Continuously verifies that the managed backend belongs to this shell."""

    def __init__(
        self,
        *,
        process: ProcessHandle,
        api_url: str,
        instance_id: str,
        on_unavailable: Callable[[str], None],
        interval_seconds: float = DEFAULT_HEALTH_INTERVAL_SECONDS,
        timeout_seconds: float = DEFAULT_HEALTH_TIMEOUT_SECONDS,
        failure_threshold: int = DEFAULT_HEALTH_FAILURE_THRESHOLD,
        probe: Callable[[], bool] | None = None,
    ) -> None:
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be at least 1")
        self._process = process
        self._on_unavailable = on_unavailable
        self._interval_seconds = max(float(interval_seconds), 0.01)
        self._probe = probe or (
            lambda: _probe_backend_health(
                api_url,
                instance_id=instance_id,
                timeout_seconds=timeout_seconds,
            )
        )
        self._state = BackendHealthState(failure_threshold=failure_threshold)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def state(self) -> BackendHealthState:
        return self._state

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run,
            name="tiance-backend-health-monitor",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2)

    def _run(self) -> None:
        while not self._stop_event.is_set():
            if self._process.poll() is not None:
                if self._state.ready:
                    self._on_unavailable("backend_process_exited")
                return

            try:
                available = bool(self._probe())
            except Exception:
                available = False

            if self._state.observe(available):
                self._on_unavailable("backend_health_check_failed")
                return

            self._stop_event.wait(self._interval_seconds)


class _LeaseHttpServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        *,
        instance_id: str,
        token: str,
    ) -> None:
        self.instance_id = instance_id
        self.token = token
        super().__init__(server_address, _LeaseRequestHandler)


class _LeaseRequestHandler(BaseHTTPRequestHandler):
    server: _LeaseHttpServer

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
        server = cast(_LeaseHttpServer, self.server)
        if self.path != LEASE_HEARTBEAT_PATH:
            self.send_error(404)
            return

        instance_id = self.headers.get(LEASE_INSTANCE_HEADER, "")
        token = self.headers.get(LEASE_TOKEN_HEADER, "")
        if not (
            hmac.compare_digest(instance_id, server.instance_id)
            and hmac.compare_digest(token, server.token)
        ):
            self.send_error(403)
            return

        self.send_response(204)
        self.end_headers()

    def log_message(self, _format: str, *_args: object) -> None:
        return


def _probe_backend_health(
    api_url: str,
    *,
    instance_id: str,
    timeout_seconds: float,
) -> bool:
    request = Request(f"{api_url.rstrip('/')}/api/health", method="GET")
    opener = build_opener(ProxyHandler({}))
    try:
        with opener.open(request, timeout=max(float(timeout_seconds), 0.05)) as response:
            if getattr(response, "status", 200) != 200:
                return False
            payload = json.loads(response.read(64 * 1024).decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError):
        return False

    return (
        isinstance(payload, dict)
        and payload.get("status") == "ok"
        and payload.get("instance_id") == instance_id
    )


def build_managed_backend_environment(
    process_environment: dict[str, str],
    lease: ShellLease,
) -> dict[str, str]:
    environment = dict(process_environment)
    environment["TIANCE_SHELL_INSTANCE_ID"] = lease.instance_id
    environment["TIANCE_SHELL_LEASE_TOKEN"] = lease.token
    environment["TIANCE_SHELL_HEARTBEAT_URL"] = lease.heartbeat_url
    return environment
