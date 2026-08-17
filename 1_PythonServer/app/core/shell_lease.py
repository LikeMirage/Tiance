from __future__ import annotations

import os
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import ProxyHandler, Request, build_opener


SHELL_INSTANCE_ID_ENV = "TIANCE_SHELL_INSTANCE_ID"
SHELL_LEASE_TOKEN_ENV = "TIANCE_SHELL_LEASE_TOKEN"
SHELL_HEARTBEAT_URL_ENV = "TIANCE_SHELL_HEARTBEAT_URL"
LEASE_INSTANCE_HEADER = "X-Tiance-Instance-Id"
LEASE_TOKEN_HEADER = "X-Tiance-Lease-Token"
LEASE_HEARTBEAT_PATH = "/heartbeat"
LEASE_REVOKED_STATUS = 410
DEFAULT_HEARTBEAT_INTERVAL_SECONDS = 2.0
DEFAULT_HEARTBEAT_TIMEOUT_SECONDS = 1.0
DEFAULT_HEARTBEAT_FAILURE_THRESHOLD = 3


class ShellLeaseRevokedError(RuntimeError):
    pass


@dataclass(frozen=True)
class ShellLeaseConfiguration:
    instance_id: str
    token: str
    heartbeat_url: str

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
    ) -> ShellLeaseConfiguration | None:
        values = environment if environment is not None else os.environ
        instance_id = values.get(SHELL_INSTANCE_ID_ENV, "").strip()
        token = values.get(SHELL_LEASE_TOKEN_ENV, "").strip()
        heartbeat_url = values.get(SHELL_HEARTBEAT_URL_ENV, "").strip()
        configured = [bool(instance_id), bool(token), bool(heartbeat_url)]
        if not any(configured):
            return None
        if not all(configured):
            raise RuntimeError("Managed shell lease configuration is incomplete")
        _validate_loopback_heartbeat_url(heartbeat_url)
        return cls(
            instance_id=instance_id,
            token=token,
            heartbeat_url=heartbeat_url,
        )


class ShellLeaseMonitor:
    """Renews the desktop-shell lease from a thread independent of FastAPI."""

    def __init__(
        self,
        configuration: ShellLeaseConfiguration,
        *,
        request_shutdown: Callable[[], None],
        heartbeat_sender: Callable[[ShellLeaseConfiguration], bool] | None = None,
        interval_seconds: float = DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
        failure_threshold: int = DEFAULT_HEARTBEAT_FAILURE_THRESHOLD,
    ) -> None:
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be at least 1")
        self._configuration = configuration
        self._request_shutdown = request_shutdown
        self._heartbeat_sender = heartbeat_sender or _send_heartbeat
        self._interval_seconds = max(float(interval_seconds), 0.01)
        self._failure_threshold = failure_threshold
        self._consecutive_failures = 0
        self._shutdown_requested = False
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def consecutive_failures(self) -> int:
        return self._consecutive_failures

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run,
            name="tiance-shell-lease-monitor",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2)

    def heartbeat_once(self) -> bool:
        try:
            succeeded = bool(self._heartbeat_sender(self._configuration))
        except ShellLeaseRevokedError:
            self._request_shutdown_once()
            return False
        except Exception:
            succeeded = False

        if succeeded:
            self._consecutive_failures = 0
            return True

        self._consecutive_failures += 1
        if (
            self._consecutive_failures >= self._failure_threshold
            and not self._shutdown_requested
        ):
            self._request_shutdown_once()
            return False
        return True

    def _request_shutdown_once(self) -> None:
        if self._shutdown_requested:
            return
        self._shutdown_requested = True
        self._request_shutdown()

    def _run(self) -> None:
        while not self._stop_event.is_set():
            if not self.heartbeat_once():
                return
            self._stop_event.wait(self._interval_seconds)


def managed_shell_instance_id() -> str | None:
    value = os.getenv(SHELL_INSTANCE_ID_ENV, "").strip()
    return value or None


def start_shell_lease_monitor(server) -> ShellLeaseMonitor | None:
    configuration = ShellLeaseConfiguration.from_environment()
    if configuration is None:
        return None

    def request_shutdown() -> None:
        print(
            "Tiance API: desktop shell lease expired; shutting down backend.",
            flush=True,
        )
        server.should_exit = True

    monitor = ShellLeaseMonitor(
        configuration,
        request_shutdown=request_shutdown,
    )
    monitor.start()
    return monitor


def _send_heartbeat(configuration: ShellLeaseConfiguration) -> bool:
    request = Request(
        configuration.heartbeat_url,
        data=b"",
        method="POST",
        headers={
            LEASE_INSTANCE_HEADER: configuration.instance_id,
            LEASE_TOKEN_HEADER: configuration.token,
        },
    )
    opener = build_opener(ProxyHandler({}))
    try:
        with opener.open(request, timeout=DEFAULT_HEARTBEAT_TIMEOUT_SECONDS) as response:
            return getattr(response, "status", None) == 204
    except HTTPError as exc:
        if exc.code == LEASE_REVOKED_STATUS:
            raise ShellLeaseRevokedError from exc
        return False
    except (URLError, TimeoutError, OSError, ValueError):
        return False


def _validate_loopback_heartbeat_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or parsed.port is None:
        raise RuntimeError("Managed shell heartbeat URL must use loopback HTTP")
    if parsed.path != LEASE_HEARTBEAT_PATH:
        raise RuntimeError("Managed shell heartbeat URL path is invalid")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise RuntimeError("Managed shell heartbeat URL is invalid")
