from __future__ import annotations

import threading
import unittest
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

from app.backend_watchdog import (
    LEASE_INSTANCE_HEADER,
    LEASE_REVOKED_STATUS,
    LEASE_TOKEN_HEADER,
    BackendHealthMonitor,
    BackendHealthState,
    ShellLease,
    ShellLeaseServer,
    build_managed_backend_environment,
)


class _RunningProcess:
    def poll(self) -> None:
        return None


class ShellLeaseServerTests(unittest.TestCase):
    def test_accepts_only_matching_instance_and_token(self) -> None:
        server = ShellLeaseServer()
        lease = server.start()
        opener = build_opener(ProxyHandler({}))
        try:
            request = Request(
                lease.heartbeat_url,
                data=b"",
                method="POST",
                headers={
                    LEASE_INSTANCE_HEADER: lease.instance_id,
                    LEASE_TOKEN_HEADER: lease.token,
                },
            )
            with opener.open(request, timeout=1) as response:
                self.assertEqual(response.status, 204)

            invalid_request = Request(
                lease.heartbeat_url,
                data=b"",
                method="POST",
                headers={
                    LEASE_INSTANCE_HEADER: lease.instance_id,
                    LEASE_TOKEN_HEADER: "wrong-token",
                },
            )
            with self.assertRaises(HTTPError) as error:
                opener.open(invalid_request, timeout=1)
            self.assertEqual(error.exception.code, 403)
        finally:
            server.stop()

    def test_authenticated_heartbeat_reports_revoked_lease(self) -> None:
        server = ShellLeaseServer()
        lease = server.start()
        opener = build_opener(ProxyHandler({}))
        try:
            server.revoke()
            request = Request(
                lease.heartbeat_url,
                data=b"",
                method="POST",
                headers={
                    LEASE_INSTANCE_HEADER: lease.instance_id,
                    LEASE_TOKEN_HEADER: lease.token,
                },
            )
            with self.assertRaises(HTTPError) as error:
                opener.open(request, timeout=1)
            self.assertEqual(error.exception.code, LEASE_REVOKED_STATUS)
        finally:
            server.stop()

    def test_managed_environment_contains_complete_lease(self) -> None:
        lease = ShellLease(
            instance_id="shell-instance",
            token="secret-token",
            heartbeat_url="http://127.0.0.1:19000/heartbeat",
        )

        environment = build_managed_backend_environment({"EXISTING": "value"}, lease)

        self.assertEqual(environment["EXISTING"], "value")
        self.assertEqual(environment["TIANCE_SHELL_INSTANCE_ID"], lease.instance_id)
        self.assertEqual(environment["TIANCE_SHELL_LEASE_TOKEN"], lease.token)
        self.assertEqual(environment["TIANCE_SHELL_HEARTBEAT_URL"], lease.heartbeat_url)


class BackendHealthStateTests(unittest.TestCase):
    def test_requires_consecutive_failures_after_first_success(self) -> None:
        state = BackendHealthState(failure_threshold=3)

        self.assertFalse(state.observe(False))
        self.assertFalse(state.observe(False))
        self.assertFalse(state.ready)

        self.assertFalse(state.observe(True))
        self.assertTrue(state.ready)
        self.assertFalse(state.observe(False))
        self.assertFalse(state.observe(False))
        self.assertFalse(state.observe(True))
        self.assertEqual(state.consecutive_failures, 0)
        self.assertFalse(state.observe(False))
        self.assertFalse(state.observe(False))
        self.assertTrue(state.observe(False))

    def test_monitor_reports_unavailable_after_threshold(self) -> None:
        outcomes = iter([True, False, False, False])
        notified = threading.Event()
        reasons: list[str] = []

        monitor = BackendHealthMonitor(
            process=_RunningProcess(),
            api_url="http://127.0.0.1:18000",
            instance_id="shell-instance",
            on_unavailable=lambda reason: (reasons.append(reason), notified.set()),
            interval_seconds=0.01,
            failure_threshold=3,
            probe=lambda: next(outcomes),
        )
        monitor.start()
        try:
            self.assertTrue(notified.wait(timeout=1))
        finally:
            monitor.stop()

        self.assertEqual(reasons, ["backend_health_check_failed"])


if __name__ == "__main__":
    unittest.main()
