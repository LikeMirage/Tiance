from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from test_transcribe import FakeClient, response, run, wav
from jianying_asr.common import ASRError, Budget


class ParallelJobTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "recording.wav"
        wav(self.source)
        env = patch.dict(os.environ, {"TIANCE_WORKSPACE_ROOT": str(self.root)})
        env.start()
        self.addCleanup(env.stop)

    def execute(self, count, factory, budget=None):
        plan = [(float(i), 1.0) for i in range(count)]
        def prepare(_source, _info, start, _length, _temporary, _budget):
            path = _temporary / str(int(start))
            path.write_bytes(b"fixture")
            return path
        with patch("jianying_asr.runner.plan_parts", return_value=plan), \
                patch("jianying_asr.parallel.prepare_part", side_effect=prepare):
            result = run({"input_path": str(self.source), "formats": ["json", "txt", "srt", "ass"]},
                         client_factory=factory, budget=budget or Budget(30))
        job = json.loads(Path(result["data"]["job_file"]).read_text(encoding="utf-8"))
        return result, job

    def test_reverse_completion_keeps_source_order_and_timestamps(self):
        ready = threading.Barrier(3)
        done = [threading.Event() for _ in range(3)]
        completed = []
        class Reverse(FakeClient):
            def upload(self, path): return path.name
            def submit(self, uri): return uri
            def poll(self, task_id):
                index = int(task_id)
                ready.wait(5)
                if index < 2 and not done[index + 1].wait(5):
                    raise AssertionError("Other parts must run concurrently")
                completed.append(index)
                done[index].set()
                return response(f"part-{index}")
        result, job = self.execute(3, Reverse)
        self.assertTrue(result["ok"], result)
        self.assertEqual(completed, [2, 1, 0])
        self.assertTrue(all(p["status"] == "completed" for p in job["parts"]))
        outputs = {f["format"]: Path(f["path"]) for f in result["data"]["files"]}
        data = json.loads(outputs["json"].read_text(encoding="utf-8"))
        self.assertEqual([s["text"] for s in data], ["part-0", "part-1", "part-2"])
        self.assertEqual([s["startMs"] for s in data], [10, 1010, 2010])
        self.assertEqual([s["words"][0]["endMs"] for s in data], [10, 1010, 2010])
        self.assertEqual(outputs["txt"].read_text(), "part-0\npart-1\npart-2\n")
        self.assertIn("00:00:02,010", outputs["srt"].read_text())

    def test_all_twenty_parts_start_together_and_share_identity_budget(self):
        lock = threading.Lock()
        barrier = threading.Barrier(20)
        active = peak = entered = 0
        identities, budgets = set(), set()
        class Measured(FakeClient):
            def __init__(self, budget, *, tdid=None):
                super().__init__(budget, tdid=tdid)
                with lock:
                    identities.add(tdid)
                    budgets.add(id(budget))
            def upload(self, path):
                nonlocal active, peak, entered
                with lock:
                    active += 1
                    peak = max(peak, active)
                    entered += 1
                    first_wave = entered <= 20
                if first_wave:
                    barrier.wait(5)
                return path.name
            def submit(self, uri): return uri
            def poll(self, task_id):
                nonlocal active
                self.warnings = ["shared", f"part-{task_id}"]
                with lock:
                    active -= 1
                return response(task_id)
        result, job = self.execute(20, Measured)
        self.assertTrue(result["ok"], result)
        self.assertEqual((entered, active, peak), (20, 0, 20))
        self.assertEqual((len(identities), len(budgets)), (1, 1))
        self.assertNotIn(None, identities)
        self.assertEqual(job["concurrent_parts"], 20)
        self.assertEqual(len(job["warnings"]), 21)
        self.assertEqual(len(job["parts"]), 20)

    def test_invalid_extra_parts_do_not_start_another_wave(self):
        result, job = self.execute(21, lambda *_args, **_kwargs: self.fail("must not upload"))
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "INVALID_PLAN")
        self.assertTrue(all(p["status"] == "failed" for p in job["parts"]))

    def test_one_failed_part_preserves_other_running_parts_and_error(self):
        ready = threading.Barrier(3)
        class OneFailure(FakeClient):
            def upload(self, path): return path.name
            def submit(self, uri): return uri
            def poll(self, task_id):
                ready.wait(5)
                if task_id == "1":
                    raise ASRError("NETWORK_ERROR", "模拟通信失败")
                return response(task_id)
        result, job = self.execute(3, OneFailure)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "NETWORK_ERROR")
        self.assertEqual(result["data"]["completed_parts"], 2)
        self.assertEqual([p["status"] for p in job["parts"]], ["completed", "failed", "completed"])
        self.assertEqual(job["parts"][1]["task_id"], "1")
        self.assertEqual(job["parts"][1]["error_code"], "NETWORK_ERROR")
        failure = result["data"]["failed_parts"][0]
        self.assertEqual(failure["part_number"], 2)
        self.assertEqual(failure["start_seconds"], 1)
        self.assertEqual(failure["duration_seconds"], 1)
        self.assertEqual(failure["error_stage"], "processing")
        self.assertEqual(failure["task_id"], "1")
        self.assertEqual(job["files"], [])
        output = Path(result["data"]["output_dir"])
        self.assertTrue((output / "parts/0001.raw.json").is_file())
        self.assertTrue((output / "parts/0003.raw.json").is_file())


if __name__ == "__main__":
    unittest.main()
