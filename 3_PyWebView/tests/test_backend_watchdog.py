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
    returncode = None

    def poll(self) -> int | None:
        return self.returncode


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

    def test_live_process_survives_health_stall_then_recovers_and_exit_is_still_detected(self) -> None:
        outcomes = iter([True] + [False] * 20 + [True])
        notified = threading.Event()
        reasons: list[str] = []
        health_changes: list[bool] = []
        process = _RunningProcess()

        def probe():
            try:
                return next(outcomes)
            except StopIteration:
                process.returncode = 1
                return True

        monitor = BackendHealthMonitor(
            process=process,
            api_url="http://127.0.0.1:18000",
            instance_id="shell-instance",
            on_unavailable=lambda reason: (reasons.append(reason), notified.set()),
            interval_seconds=0.01,
            failure_threshold=3,
            probe=probe,
            on_health_changed=health_changes.append,
        )
        monitor.start()
        try:
            self.assertTrue(notified.wait(timeout=1))
        finally:
            monitor.stop()

        self.assertEqual(health_changes, [False, True])
        self.assertEqual(reasons, ["backend_process_exited"])

    def test_process_exit_is_detected_while_http_remains_unresponsive(self) -> None:
        process = _RunningProcess()
        notified = threading.Event()
        reasons: list[str] = []
        calls = 0

        def probe():
            nonlocal calls
            calls += 1
            if calls == 6:
                process.returncode = 1
            return calls == 1

        monitor = BackendHealthMonitor(
            process=process, api_url="http://127.0.0.1:18000", instance_id="instance",
            on_unavailable=lambda reason: (reasons.append(reason), notified.set()),
            interval_seconds=0.01, probe=probe,
        )
        monitor.start()
        try:
            self.assertTrue(notified.wait(timeout=1))
        finally:
            monitor.stop()
        self.assertEqual(reasons, ["backend_process_exited"])
        self.assertEqual(calls, 6)


if __name__ == "__main__":
    unittest.main()
