from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch


PROGRAM_ROOT = Path(__file__).resolve().parents[1] / "program"
if str(PROGRAM_ROOT) not in sys.path:
    sys.path.insert(0, str(PROGRAM_ROOT))

import execution_service  # noqa: E402
import managed_process  # noqa: E402
import python_runtime  # noqa: E402
from process_liveness import (  # noqa: E402
    LIVENESS_FILENAME,
    LIVENESS_PROTOCOL,
    ProcessLivenessLock,
)


def _runtime(workdir: Path) -> python_runtime.PythonRuntime:
    inherited_keys = (
        "COMSPEC",
        "PATH",
        "PATHEXT",
        "SystemRoot",
        "TEMP",
        "TMP",
        "WINDIR",
    )
    return python_runtime.PythonRuntime(
        environment={
            key: value
            for key in inherited_keys
            if (value := os.environ.get(key))
        },
        import_paths=(workdir,),
        dependency_site_packages=None,
    )


class ManagedProcessTests(unittest.TestCase):
    def test_system_python_uses_workspace_process_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with (
                patch.dict(
                    os.environ,
                    {"TIANCE_WORKSPACE_ROOT": str(root)},
                    clear=False,
                ),
                patch.object(
                    managed_process,
                    "resolve_embedded_runtime_root",
                    return_value=None,
                ),
            ):
                execution_root = managed_process.default_execution_root()

        self.assertEqual(
            execution_root,
            root / "Data" / "runtime" / "tool-processes" / "run_python_script",
        )

    def test_start_returns_without_waiting_and_child_keeps_running(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workdir = root / "workdir"
            workdir.mkdir()
            marker = root / "finished.txt"
            script = root / "background.py"
            script.write_text(
                "import pathlib, time\n"
                "time.sleep(0.4)\n"
                f"pathlib.Path({str(marker)!r}).write_text('done', encoding='utf-8')\n",
                encoding="utf-8",
            )
            execution_id, execution_directory = managed_process.create_execution_directory(
                root / "executions"
            )
            started_at = time.monotonic()
            managed = managed_process.start_managed_script(
                args=[],
                execution_directory=execution_directory,
                execution_id=execution_id,
                expected_exit_codes=(0,),
                run_mode="auto_detach",
                runtime=_runtime(workdir),
                script_path=script,
                stdin_text=None,
                workdir=workdir,
            )
            elapsed = time.monotonic() - started_at
            self.assertLess(elapsed, 0.3)
            completion = managed_process.wait_for_completion(
                managed,
                max_output_chars=1000,
                wait_seconds=3,
            )
            self.assertIsNotNone(completion)
            self.assertEqual(completion.exit_code, 0)
            self.assertEqual(marker.read_text(encoding="utf-8"), "done")
            record = json.loads(
                (execution_directory / "execution.json").read_text(encoding="utf-8")
            )
            self.assertEqual(record["state"], "completed")
            self.assertIsNotNone(record["heartbeat_at"])

    def test_child_releases_its_dependency_environment_lease(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            lease_path = root / "child-lease.json"
            lease_path.write_text("{}", encoding="utf-8")
            script = root / "quick.py"
            script.write_text("print('ok')\n", encoding="utf-8")
            execution_id, execution_directory = managed_process.create_execution_directory(
                root / "executions"
            )
            with patch.object(
                managed_process,
                "acquire_environment_lease",
                return_value=python_runtime.EnvironmentLease(lease_path),
            ):
                managed = managed_process.start_managed_script(
                    args=[],
                    execution_directory=execution_directory,
                    execution_id=execution_id,
                    expected_exit_codes=(0,),
                    run_mode="auto_detach",
                    runtime=_runtime(root),
                    script_path=script,
                    stdin_text=None,
                    workdir=root,
                )
            completion = managed_process.wait_for_completion(
                managed,
                max_output_chars=1000,
                wait_seconds=3,
            )
            self.assertIsNotNone(completion)
            self.assertEqual(completion.exit_code, 0)
            self.assertFalse(lease_path.exists())

    def test_managed_process_stops_through_its_control_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            script = root / "long_running.py"
            script.write_text(
                "import time\nwhile True:\n    time.sleep(1)\n",
                encoding="utf-8",
            )
            execution_id, execution_directory = managed_process.create_execution_directory(
                root / "executions"
            )
            managed = managed_process.start_managed_script(
                args=[],
                execution_directory=execution_directory,
                execution_id=execution_id,
                expected_exit_codes=(0,),
                run_mode="detached",
                runtime=_runtime(root),
                script_path=script,
                stdin_text=None,
                workdir=root,
            )
            (execution_directory / "stop.request").write_text("{}", encoding="utf-8")
            completion = managed_process.wait_for_completion(
                managed,
                max_output_chars=1000,
                wait_seconds=5,
            )
            self.assertIsNotNone(completion)
            self.assertEqual(completion.state, "stopped")
            self.assertEqual(completion.exit_code, 143)
            record = json.loads(
                (execution_directory / "execution.json").read_text(encoding="utf-8")
            )
            self.assertEqual(record["state"], "stopped")

    def test_child_holds_liveness_lock_until_process_exits(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            script = root / "long_running.py"
            script.write_text(
                "import time\nwhile True:\n    time.sleep(1)\n",
                encoding="utf-8",
            )
            execution_id, execution_directory = managed_process.create_execution_directory(
                root / "executions"
            )
            managed = managed_process.start_managed_script(
                args=[],
                execution_directory=execution_directory,
                execution_id=execution_id,
                expected_exit_codes=(0,),
                run_mode="detached",
                runtime=_runtime(root),
                script_path=script,
                stdin_text=None,
                workdir=root,
            )
            record_path = execution_directory / "execution.json"
            deadline = time.monotonic() + 3
            record: dict[str, object] = {}
            while time.monotonic() < deadline:
                record = json.loads(record_path.read_text(encoding="utf-8"))
                if record.get("liveness_protocol") == LIVENESS_PROTOCOL:
                    break
                time.sleep(0.05)

            self.assertEqual(record.get("liveness_protocol"), LIVENESS_PROTOCOL)
            liveness_path = execution_directory / LIVENESS_FILENAME
            with self.assertRaises(OSError):
                ProcessLivenessLock.acquire(liveness_path)

            (execution_directory / "stop.request").write_text("{}", encoding="utf-8")
            completion = managed_process.wait_for_completion(
                managed,
                max_output_chars=1000,
                wait_seconds=5,
            )
            self.assertIsNotNone(completion)
            released = ProcessLivenessLock.acquire(liveness_path)
            released.release()

    def test_detached_child_records_expected_nonzero_exit_as_completed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            script = root / "expected_exit.py"
            script.write_text("raise SystemExit(2)\n", encoding="utf-8")
            execution_id, execution_directory = managed_process.create_execution_directory(
                root / "executions"
            )
            managed = managed_process.start_managed_script(
                args=[],
                execution_directory=execution_directory,
                execution_id=execution_id,
                expected_exit_codes=(0, 2),
                run_mode="detached",
                runtime=_runtime(root),
                script_path=script,
                stdin_text=None,
                workdir=root,
            )

            self.assertEqual(managed.process.wait(timeout=3), 2)
            record = json.loads(
                (execution_directory / "execution.json").read_text(encoding="utf-8")
            )

            self.assertEqual(record["state"], "completed")
            self.assertEqual(record["exit_code"], 2)
            self.assertEqual(record["expected_exit_codes"], [0, 2])


class ExecutionServiceTests(unittest.TestCase):
    def test_wait_mode_returns_completed_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            outcome = execution_service.execute(
                self._request(root, "print('wait-finished')\n", "wait")
            )
        self.assertEqual(outcome.process_state, "completed")
        self.assertFalse(outcome.still_running)
        self.assertEqual(outcome.stdout.strip(), "wait-finished")

    def test_wait_mode_accepts_expected_nonzero_exit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            request = self._request(root, "raise SystemExit(2)\n", "wait")
            outcome = execution_service.execute(
                replace(request, expected_exit_codes=(0, 2))
            )
        self.assertEqual(outcome.exit_code, 2)
        self.assertEqual(outcome.process_state, "completed")

    def test_auto_detach_returns_completed_output_for_short_script(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with patch.object(
                execution_service,
                "create_execution_directory",
                side_effect=lambda: managed_process.create_execution_directory(root / "runs"),
            ):
                outcome = execution_service.execute(
                    self._request(root, "print('finished')\n", "auto_detach")
                )
        self.assertEqual(outcome.process_state, "completed")
        self.assertFalse(outcome.still_running)
        self.assertEqual(outcome.stdout.strip(), "finished")
        self.assertIsNone(outcome.execution_directory)
        self.assertNotIn("stored_script_path", outcome.source)

    def test_auto_detach_accepts_expected_nonzero_exit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            request = self._request(root, "raise SystemExit(2)\n", "auto_detach")
            request = replace(request, expected_exit_codes=(0, 2))
            with patch.object(
                execution_service,
                "create_execution_directory",
                side_effect=lambda: managed_process.create_execution_directory(
                    root / "runs"
                ),
            ):
                outcome = execution_service.execute(request)
        self.assertEqual(outcome.exit_code, 2)
        self.assertEqual(outcome.process_state, "completed")

    def test_auto_detach_leaves_long_script_running(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            marker = root / "auto-finished.txt"
            script_text = (
                "import pathlib, time\n"
                "time.sleep(0.4)\n"
                f"pathlib.Path({str(marker)!r}).write_text('done', encoding='utf-8')\n"
            )
            request = self._request(root, script_text, "auto_detach")
            request = replace(request, detach_after_seconds=0.05)
            with patch.object(
                execution_service,
                "create_execution_directory",
                side_effect=lambda: managed_process.create_execution_directory(root / "runs"),
            ):
                outcome = execution_service.execute(request)
            self.assertEqual(outcome.process_state, "running")
            self.assertTrue(outcome.still_running)
            self.assertTrue(Path(outcome.source["stored_script_path"]).is_file())
            deadline = time.monotonic() + 3
            while not marker.exists() and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertTrue(marker.is_file())
            time.sleep(0.1)

    def test_detached_returns_unchecked_without_claiming_process_is_running(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with patch.object(
                execution_service,
                "create_execution_directory",
                side_effect=lambda: managed_process.create_execution_directory(root / "runs"),
            ):
                outcome = execution_service.execute(
                    self._request(root, "print('quick')\n", "detached")
                )
            deadline = time.monotonic() + 3
            while (
                not Path(outcome.stdout_log_path or "").read_text(
                    encoding="utf-8",
                    errors="replace",
                ).strip()
                and time.monotonic() < deadline
            ):
                time.sleep(0.05)
            time.sleep(0.1)
            self.assertEqual(outcome.process_state, "unchecked")
            self.assertIsNone(outcome.still_running)
            self.assertIsNone(outcome.exit_code)

    @staticmethod
    def _request(
        workdir: Path,
        script_text: str,
        run_mode: execution_service.RunMode,
    ) -> execution_service.ExecutionRequest:
        return execution_service.ExecutionRequest(
            args=[],
            detach_after_seconds=2,
            expected_exit_codes=(0,),
            max_output_chars=2000,
            run_mode=run_mode,
            runtime=_runtime(workdir),
            source=execution_service.ScriptSource(
                script_path=None,
                script_text=script_text,
                script_filename="inline.py",
            ),
            stdin_text=None,
            timeout_seconds=2,
            workdir=workdir,
        )


if __name__ == "__main__":
    unittest.main()
