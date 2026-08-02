from __future__ import annotations

import json
import sys
import tempfile
from threading import Thread
import time
import unittest
from pathlib import Path


PROGRAM_ROOT = Path(__file__).resolve().parents[1] / "program"
if str(PROGRAM_ROOT) not in sys.path:
    sys.path.insert(0, str(PROGRAM_ROOT))

from process_repository import ProcessRepository, ProcessRepositoryError  # noqa: E402
from process_pruning import prune_process_records  # noqa: E402
import process_liveness  # noqa: E402


class ProcessRepositoryTests(unittest.TestCase):
    def test_liveness_probe_distinguishes_held_and_released_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / process_liveness.LIVENESS_FILENAME
            path.write_bytes(b"\0")
            with path.open("r+b", buffering=0) as handle:
                handle.seek(0)
                process_liveness._lock(handle)
                try:
                    self.assertEqual(
                        process_liveness.probe_liveness_lock(
                            path,
                            process_liveness.LIVENESS_PROTOCOL,
                        ),
                        "held",
                    )
                finally:
                    handle.seek(0)
                    process_liveness._unlock(handle)
            self.assertEqual(
                process_liveness.probe_liveness_lock(
                    path,
                    process_liveness.LIVENESS_PROTOCOL,
                ),
                "released",
            )

    def test_running_state_requires_fresh_heartbeat(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            execution_id = "1" * 32
            self._write_record(root, execution_id, state="running", heartbeat_at=time.time())
            snapshot = ProcessRepository(root).get_process(execution_id)
        self.assertEqual(snapshot.state, "running")
        self.assertTrue(snapshot.active)

    def test_stale_running_record_is_unknown_not_stopped(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            execution_id = "2" * 32
            self._write_record(
                root,
                execution_id,
                state="running",
                heartbeat_at=time.time() - 60,
            )
            snapshot = ProcessRepository(
                root,
                liveness_probe=lambda *_args: "unsupported",
                pid_probe=lambda _pid: "unknown",
            ).get_process(execution_id)
        self.assertEqual(snapshot.state, "unknown")
        self.assertIsNone(snapshot.active)

    def test_stale_record_is_orphaned_only_with_strong_liveness_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            locked_id = "a" * 32
            legacy_id = "b" * 32
            self._write_record(
                root,
                locked_id,
                state="running",
                heartbeat_at=time.time() - 60,
                liveness_protocol="exclusive_file_lock_v1",
            )
            self._write_record(
                root,
                legacy_id,
                state="unchecked",
                heartbeat_at=None,
            )
            locked = ProcessRepository(
                root,
                liveness_probe=lambda *_args: "released",
                pid_probe=lambda _pid: "present",
            ).get_process(locked_id)
            legacy = ProcessRepository(
                root,
                liveness_probe=lambda *_args: "unsupported",
                pid_probe=lambda _pid: "absent",
            ).get_process(legacy_id)

        self.assertEqual(locked.state, "orphaned")
        self.assertFalse(locked.active)
        self.assertTrue(locked.data["orphaned"])
        self.assertEqual(locked.data["orphaned_reason"], "liveness_lock_released")
        self.assertEqual(legacy.state, "orphaned")
        self.assertEqual(legacy.data["orphaned_reason"], "pid_not_found")

    def test_held_liveness_lock_overrides_stale_heartbeat(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            execution_id = "c" * 32
            self._write_record(
                root,
                execution_id,
                state="running",
                heartbeat_at=time.time() - 60,
                liveness_protocol="exclusive_file_lock_v1",
            )
            snapshot = ProcessRepository(
                root,
                liveness_probe=lambda *_args: "held",
                pid_probe=lambda _pid: "absent",
            ).get_process(execution_id)

        self.assertEqual(snapshot.state, "running")
        self.assertTrue(snapshot.active)
        self.assertFalse(snapshot.data["orphaned"])

    def test_list_has_explicit_pagination_and_skips_invalid_records(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self._write_record(root, "3" * 32, state="completed", created_at=1.0)
            self._write_record(root, "4" * 32, state="completed", created_at=2.0)
            invalid = root / ("5" * 32)
            invalid.mkdir()
            (invalid / "execution.json").write_text("not-json", encoding="utf-8")
            snapshots, total, skipped = ProcessRepository(root).list_processes(
                limit=1,
                offset=0,
            )
        self.assertEqual(total, 2)
        self.assertEqual(skipped, 1)
        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0].data["execution_id"], "4" * 32)

    def test_read_logs_returns_latest_text(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            execution_id = "6" * 32
            directory = self._write_record(root, execution_id, state="completed")
            (directory / "stdout.log").write_text("start-" + "x" * 2000 + "-end", encoding="utf-8")
            result = ProcessRepository(root).read_logs(
                execution_id,
                stream="stdout",
                tail_chars=1000,
            )
        stdout = result["logs"]["stdout"]
        self.assertEqual(result["process"]["state"], "completed")
        self.assertEqual(result["process"]["expected_exit_codes"], [0])
        self.assertTrue(stdout["truncated"])
        self.assertTrue(stdout["text"].endswith("-end"))
        self.assertEqual(len(stdout["text"]), 1000)

    def test_stop_uses_execution_control_file_and_waits_for_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            execution_id = "7" * 32
            directory = self._write_record(
                root,
                execution_id,
                state="running",
                heartbeat_at=time.time(),
            )

            def emulate_child() -> None:
                request_path = directory / "stop.request"
                deadline = time.monotonic() + 3
                while not request_path.is_file() and time.monotonic() < deadline:
                    time.sleep(0.02)
                self._write_record(root, execution_id, state="stopped", exit_code=143)

            thread = Thread(target=emulate_child)
            thread.start()
            snapshot = ProcessRepository(root).request_stop(execution_id, timeout_seconds=2)
            thread.join(timeout=2)
        self.assertEqual(snapshot.state, "stopped")
        self.assertFalse(snapshot.active)

    def test_cleanup_refuses_active_record_and_removes_final_record(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            running_id = "8" * 32
            finished_id = "9" * 32
            self._write_record(
                root,
                running_id,
                state="running",
                heartbeat_at=time.time(),
            )
            finished = self._write_record(root, finished_id, state="completed")
            repository = ProcessRepository(root)
            with self.assertRaises(ProcessRepositoryError) as raised:
                repository.cleanup(running_id)
            repository.cleanup(finished_id)
            self.assertFalse(finished.exists())
        self.assertEqual(raised.exception.code, "PROCESS_NOT_FINISHED")

    def test_cleanup_allows_verified_orphaned_record(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            execution_id = "d" * 32
            directory = self._write_record(
                root,
                execution_id,
                state="running",
                heartbeat_at=time.time() - 120,
            )
            repository = ProcessRepository(
                root,
                liveness_probe=lambda *_args: "unsupported",
                pid_probe=lambda _pid: "absent",
            )

            repository.cleanup(execution_id)

            self.assertFalse(directory.exists())

    def test_prune_removes_only_old_final_and_verified_orphaned_records(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            old = time.time() - 120
            final_id = "e" * 32
            orphaned_id = "f" * 32
            running_id = "1" * 32
            unknown_id = "2" * 32
            final_but_locked_id = "5" * 32
            self._write_record(
                root,
                final_id,
                state="completed",
                updated_at=old,
            )
            self._write_record(
                root,
                orphaned_id,
                state="running",
                heartbeat_at=old,
                updated_at=old,
                liveness_protocol="exclusive_file_lock_v1",
            )
            self._write_record(
                root,
                running_id,
                state="running",
                heartbeat_at=old,
                updated_at=old,
                liveness_protocol="exclusive_file_lock_v1",
            )
            self._write_record(
                root,
                unknown_id,
                state="running",
                heartbeat_at=old,
                updated_at=old,
            )
            self._write_record(
                root,
                final_but_locked_id,
                state="completed",
                updated_at=old,
                liveness_protocol="exclusive_file_lock_v1",
            )
            liveness_by_id = {
                orphaned_id: "released",
                running_id: "held",
                final_but_locked_id: "held",
            }
            repository = ProcessRepository(
                root,
                liveness_probe=lambda path, _protocol: liveness_by_id.get(
                    path.parent.name,
                    "unsupported",
                ),
                pid_probe=lambda _pid: "present",
            )

            result = prune_process_records(
                repository,
                older_than_seconds=60,
                dry_run=False,
            )

            self.assertEqual(result["candidate_count"], 2)
            self.assertEqual(result["removed_count"], 2)
            self.assertEqual(
                {item["execution_id"] for item in result["removed"]},
                {final_id, orphaned_id},
            )
            self.assertFalse((root / final_id).exists())
            self.assertFalse((root / orphaned_id).exists())
            self.assertTrue((root / running_id).exists())
            self.assertTrue((root / unknown_id).exists())
            self.assertTrue((root / final_but_locked_id).exists())

    def test_prune_rechecks_liveness_immediately_before_deletion(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            execution_id = "3" * 32
            self._write_record(
                root,
                execution_id,
                state="running",
                heartbeat_at=time.time() - 120,
                updated_at=time.time() - 120,
                liveness_protocol="exclusive_file_lock_v1",
            )
            probes = iter(("released", "held"))
            repository = ProcessRepository(
                root,
                liveness_probe=lambda *_args: next(probes),
                pid_probe=lambda _pid: "present",
            )

            result = prune_process_records(
                repository,
                older_than_seconds=60,
                dry_run=False,
            )

            self.assertEqual(result["candidate_count"], 1)
            self.assertEqual(result["removed_count"], 0)
            self.assertEqual(result["failed_count"], 1)
            self.assertTrue((root / execution_id).exists())

    def test_prune_dry_run_does_not_remove_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            execution_id = "4" * 32
            self._write_record(
                root,
                execution_id,
                state="completed",
                updated_at=time.time() - 120,
            )

            result = prune_process_records(
                ProcessRepository(root),
                older_than_seconds=60,
                dry_run=True,
            )

            self.assertEqual(result["candidate_count"], 1)
            self.assertEqual(result["removed_count"], 0)
            self.assertTrue((root / execution_id).exists())

    @staticmethod
    def _write_record(
        root: Path,
        execution_id: str,
        *,
        state: str,
        heartbeat_at: float | None = None,
        created_at: float | None = None,
        updated_at: float | None = None,
        exit_code: int | None = None,
        liveness_protocol: str | None = None,
    ) -> Path:
        directory = root / execution_id
        directory.mkdir(parents=True, exist_ok=True)
        now = time.time()
        payload = {
            "schema_version": 1,
            "execution_id": execution_id,
            "pid": 123,
            "state": state,
            "exit_code": exit_code,
            "expected_exit_codes": [0],
            "created_at": created_at if created_at is not None else now,
            "updated_at": updated_at if updated_at is not None else now,
            "heartbeat_at": heartbeat_at,
            "liveness_protocol": liveness_protocol,
        }
        temporary = directory / ".execution.json.tmp"
        temporary.write_text(json.dumps(payload), encoding="utf-8")
        temporary.replace(directory / "execution.json")
        return directory


if __name__ == "__main__":
    unittest.main()
