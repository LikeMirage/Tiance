from __future__ import annotations

import asyncio
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.api.routes.health import get_health
from app.core.shell_lease import ShellLeaseConfiguration, ShellLeaseMonitor


class _HeartbeatCaptureHandler(BaseHTTPRequestHandler):
    received: dict[str, str] = {}

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
        type(self).received = {
            "path": self.path,
            "instance_id": self.headers.get("X-Tiance-Instance-Id", ""),
            "token": self.headers.get("X-Tiance-Lease-Token", ""),
        }
        self.send_response(204)
        self.end_headers()

    def log_message(self, _format: str, *_args: object) -> None:
        return


def test_manual_backend_has_no_shell_lease() -> None:
    assert ShellLeaseConfiguration.from_environment({}) is None


def test_shell_lease_requires_complete_configuration() -> None:
    with pytest.raises(RuntimeError, match="incomplete"):
        ShellLeaseConfiguration.from_environment(
            {"TIANCE_SHELL_INSTANCE_ID": "shell-instance"}
        )


def test_shell_lease_rejects_non_loopback_heartbeat_url() -> None:
    with pytest.raises(RuntimeError, match="loopback"):
        ShellLeaseConfiguration.from_environment(
            {
                "TIANCE_SHELL_INSTANCE_ID": "shell-instance",
                "TIANCE_SHELL_LEASE_TOKEN": "secret-token",
                "TIANCE_SHELL_HEARTBEAT_URL": "https://example.com/heartbeat",
            }
        )


def test_shell_lease_rejects_unknown_loopback_path() -> None:
    with pytest.raises(RuntimeError, match="path"):
        ShellLeaseConfiguration.from_environment(
            {
                "TIANCE_SHELL_INSTANCE_ID": "shell-instance",
                "TIANCE_SHELL_LEASE_TOKEN": "secret-token",
                "TIANCE_SHELL_HEARTBEAT_URL": "http://127.0.0.1:19000/not-heartbeat",
            }
        )


def test_monitor_requires_consecutive_failures_and_resets_after_success() -> None:
    outcomes = iter([False, False, True, False, False, False])
    shutdown_requests: list[bool] = []
    configuration = ShellLeaseConfiguration(
        instance_id="shell-instance",
        token="secret-token",
        heartbeat_url="http://127.0.0.1:19000/heartbeat",
    )
    monitor = ShellLeaseMonitor(
        configuration,
        request_shutdown=lambda: shutdown_requests.append(True),
        heartbeat_sender=lambda _configuration: next(outcomes),
        failure_threshold=3,
    )

    assert monitor.heartbeat_once() is True
    assert monitor.heartbeat_once() is True
    assert monitor.heartbeat_once() is True
    assert monitor.consecutive_failures == 0
    assert monitor.heartbeat_once() is True
    assert monitor.heartbeat_once() is True
    assert monitor.heartbeat_once() is False
    assert shutdown_requests == [True]


def test_default_heartbeat_sender_uses_the_lease_contract() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _HeartbeatCaptureHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = int(server.server_address[1])
    configuration = ShellLeaseConfiguration(
        instance_id="shell-instance",
        token="secret-token",
        heartbeat_url=f"http://127.0.0.1:{port}/heartbeat",
    )
    monitor = ShellLeaseMonitor(configuration, request_shutdown=lambda: None)
    try:
        assert monitor.heartbeat_once() is True
        assert _HeartbeatCaptureHandler.received == {
            "path": "/heartbeat",
            "instance_id": "shell-instance",
            "token": "secret-token",
        }
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_health_response_exposes_managed_shell_instance(monkeypatch) -> None:
    monkeypatch.setenv("TIANCE_SHELL_INSTANCE_ID", "shell-instance")

    response = asyncio.run(get_health())

    assert response.instance_id == "shell-instance"
