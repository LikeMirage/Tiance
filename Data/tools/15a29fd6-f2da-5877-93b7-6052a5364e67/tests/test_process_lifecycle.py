from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import subprocess
from threading import Event
import time
import unittest
from unittest.mock import patch


TOOL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL_ROOT / "program"))
import process_runner


class ProcessLifecycleTests(unittest.TestCase):
    def test_parent_exit_does_not_wait_for_or_kill_inheriting_child(self):
        self._check_inheriting_child(timed_out=False)

    def test_timeout_does_not_wait_for_or_kill_inheriting_child(self):
        self._check_inheriting_child(timed_out=True)

    def _check_inheriting_child(self, *, timed_out):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ready, release, done = (root / name for name in ("ready", "release", "done"))
            child = (
                "import pathlib,sys,time\n"
                f"ready,release,done=map(pathlib.Path,{[str(ready), str(release), str(done)]!r})\n"
                "print('child-ready',flush=True)\n"
                "ready.write_text('ready')\n"
                "deadline=time.monotonic()+6\n"
                "while not release.exists() and time.monotonic()<deadline: time.sleep(0.02)\n"
                "print('child-finished',flush=True)\n"
                "done.write_text('released' if release.exists() else 'expired')\n"
            )
            parent = (
                "import pathlib,subprocess,sys,time\n"
                f"subprocess.Popen([sys.executable,'-c',{child!r}])\n"
                f"ready=pathlib.Path({str(ready)!r})\n"
                "deadline=time.monotonic()+5\n"
                "while not ready.exists() and time.monotonic()<deadline: time.sleep(0.02)\n"
                "assert ready.exists()\n"
                "print('parent-finished',flush=True)\n"
            )
            if timed_out:
                parent += "time.sleep(20)\n"
            output_paths = []
            original_temporary = process_runner.NamedTemporaryFile

            def temporary_output(**kwargs):
                stream = original_temporary(dir=root, **kwargs)
                output_paths.append(Path(stream.name))
                return stream

            try:
                with patch.object(process_runner, "NamedTemporaryFile", side_effect=temporary_output):
                    result = process_runner.run_process(
                        [sys.executable, "-c", parent], stdin_bytes=b"x" * 1024 * 1024,
                        cwd=root, timeout_seconds=1 if timed_out else 30,
                        max_output_chars=20000, extra_env={},
                    )
                self.assertEqual(result.timed_out, timed_out)
                if not timed_out:
                    self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(b"child-ready", result.stdout)
                self.assertIn(b"parent-finished", result.stdout)
                self.assertNotIn(b"child-finished", result.stdout)
                self.assertFalse(done.exists(), "tool waited for the child instead of returning")
                if timed_out:
                    self.assertLess(result.elapsed_ms, 3000)
            finally:
                release.write_text("finish")
                deadline = time.monotonic() + 8
                while time.monotonic() < deadline:
                    if done.exists() and all(not path.exists() for path in output_paths):
                        break
                    time.sleep(0.02)
            self.assertEqual(done.read_text(), "released")
            self.assertTrue(all(not path.exists() for path in output_paths))

    def test_optional_timeout_and_platform_budget_are_separate(self):
        manifest = json.loads((TOOL_ROOT / ".tool/tool.json").read_text(encoding="utf-8"))
        schema = json.loads((TOOL_ROOT / ".tool/input.schema.json").read_text(encoding="utf-8"))
        output = json.loads((TOOL_ROOT / ".tool/output.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["runtime"]["timeout_seconds"], 180)
        self.assertEqual(schema["properties"]["timeout_seconds"]["default"], 30)
        self.assertNotIn("timeout_seconds", schema.get("required", []))
        self.assertIn("timeout_seconds", output["properties"]["data"]["properties"])
        for example in json.loads((TOOL_ROOT / ".tool/examples.json").read_text(encoding="utf-8")):
            payload = json.loads(example["content"])
            if "timeout_seconds" in payload:
                self.assertGreaterEqual(payload["timeout_seconds"], 1)
                self.assertLessEqual(payload["timeout_seconds"], 300)

    def test_slow_process_reaping_does_not_delay_timeout_result(self):
        release, reaped = Event(), Event()

        class Process:
            killed = False

            def wait(self, timeout=None):
                if timeout is not None:
                    raise subprocess.TimeoutExpired("test", timeout)
                release.wait()
                reaped.set()
                return -1

            def kill(self):
                self.killed = True

            def poll(self):
                return None

        process = Process()
        try:
            with tempfile.TemporaryDirectory() as directory:
                with patch.object(process_runner.subprocess, "Popen", return_value=process):
                    result = process_runner.run_process(
                        ["test"], stdin_bytes=None, cwd=Path(directory),
                        timeout_seconds=1, max_output_chars=1000, extra_env={},
                    )
            self.assertTrue(result.timed_out)
            self.assertTrue(process.killed)
            self.assertIsNone(result.returncode)
            self.assertFalse(reaped.is_set())
        finally:
            release.set()
        self.assertTrue(reaped.wait(2))


if __name__ == "__main__":
    unittest.main()
