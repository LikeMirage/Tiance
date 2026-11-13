from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "program"))
PRIVATE = ROOT / "dependencies" / "py313" / "site-packages"
if PRIVATE.is_dir():
    sys.path.insert(0, str(PRIVATE))

import httpx
from jianying_asr.client import JianyingClient, BLOCK_BYTES, crc32_file, chunks
from jianying_asr.common import ASRError, Budget, write_json
from jianying_asr.export import segments, write_outputs
from jianying_asr.media import MediaInfo, plan_parts, prepare_part, probe
from jianying_asr.runner import run, validate
from jianying_asr.signing import api_headers, vod_headers


def response(text="你好", start=10, end=900):
    return {"ret": "0", "data": {"utterances": [{"text": text, "start_time": start, "end_time": end,
            "words": [{"text": text, "start_time": start, "end_time": start}], "attribute": {"extra": "keep"}}]}}


def wav(path, seconds=3):
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16000)
        output.writeframes(b"\x00\x00" * round(16000 * seconds))


class FakeClient:
    def __init__(self, budget, *, tdid=None):
        self.warnings = []
        self.count = 0
    def __enter__(self): return self
    def __exit__(self, *_): pass
    def upload(self, path): return "uploaded"
    def submit(self, uri):
        self.count += 1
        return f"task-{self.count}"
    def poll(self, task_id): return response(task_id)


class ProtocolTests(unittest.TestCase):
    def test_signatures_match_original_typescript(self):
        self.assertEqual(api_headers("/lv/v1/audio_subtitle/submit", "test-device", 1793844184)["sign"],
                         "169d8b8bb17fe86a7c4c2456e7589985")
        query = "Action=ApplyUploadInner&FileSize=16&FileType=object&IsInner=1&SpaceName=lv-mac-recognition&Version=2020-11-19&s=5y0udbjapi"
        signed = vod_headers("test-access", "test-secret", "test-token", query, "20261105T020304Z")
        self.assertTrue(signed["authorization"].endswith("06c0baba2fbfa19abd2545d10839aacc6f6c2be12578e344151dd5cb9214f2ec"))

    def test_streamed_crc_and_upload_blocks(self):
        import zlib
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / "big.wav"
            data = b"a" * (BLOCK_BYTES * 3 + 7)
            p.write_bytes(data)
            with patch.object(Path, "read_bytes", side_effect=AssertionError("whole file read")):
                self.assertEqual(crc32_file(p, Budget(30)), f"{zlib.crc32(data):08x}")
                sizes = [len(b) for b in chunks(p, Budget(30))]
            self.assertEqual(sizes, [BLOCK_BYTES, BLOCK_BYTES, BLOCK_BYTES, 7])

    def test_protocol_pipeline_and_pending_result(self):
        seen = []
        query_count = 0
        def handler(request):
            nonlocal query_count
            path = request.url.path
            seen.append((request.method, path, request.read()))
            if path.endswith("upload_sign"):
                return httpx.Response(200, json={"ret": "0", "data": {"access_key_id": "access", "secret_access_key": "secret", "session_token": "token"}})
            if request.url.host == "vod.bytedanceapi.com":
                return httpx.Response(200, json={"Result": {"UploadAddress": {"StoreInfos": [{"StoreUri": "audio/one", "UploadID": "id", "Auth": "auth"}], "UploadHosts": ["upload.test"]}}})
            if request.url.host == "upload.test":
                self.assertNotIn("x-amz-security-token", request.url.params)
                return httpx.Response(200, json={"success": 0})
            if path.endswith("submit"):
                return httpx.Response(200, json={"ret": "0", "data": {"id": "task"}})
            query_count += 1
            return httpx.Response(200, json={"ret": "0", "data": None} if query_count == 1 else response())
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / "a.wav"
            p.write_bytes(b"data")
            with JianyingClient(Budget(30), transport=httpx.MockTransport(handler)) as client, patch.object(client.budget, "sleep"):
                uri = client.upload(p)
                self.assertEqual(uri, "audio/one")
                task = client.submit(uri)
                self.assertEqual(client.poll(task), response())
                self.assertEqual(client.warnings, [])
        self.assertEqual(query_count, 2)
        self.assertEqual([body for method, path, body in seen if method == "PUT"], [b"data"])

    def test_no_duplicate_submit_after_connection_loss(self):
        calls = []
        def handler(request):
            calls.append(request)
            raise httpx.ReadError("signed-url-secret", request=request)
        with JianyingClient(Budget(30), transport=httpx.MockTransport(handler)) as client:
            with self.assertRaises(ASRError) as caught: client.submit("uri")
        self.assertEqual(len(calls), 1)
        self.assertNotIn("signed-url-secret", str(caught.exception))

    def test_query_recovers_from_503_and_never_accepts_malformed_success(self):
        replies = iter([httpx.Response(503), httpx.Response(200, json={"ret": "0", "data": {}})])
        with JianyingClient(Budget(30), transport=httpx.MockTransport(lambda _: next(replies))) as client, patch.object(client.budget, "sleep") as sleep:
            with self.assertRaisesRegex(ASRError, "utterances"): client.poll("id")
            sleep.assert_called_once_with(5)

    def test_expired_budget_makes_no_request(self):
        budget = Budget(10)
        budget.deadline = 0
        with JianyingClient(budget, transport=httpx.MockTransport(lambda _: self.fail("network request"))) as client:
            with self.assertRaisesRegex(ASRError, "总执行时限"): client.poll("id")


class MediaAndOutputTests(unittest.TestCase):
    def test_partition_balanced_target_and_twenty_part_cap(self):
        self.assertEqual(plan_parts(599), [(0, 599)])
        self.assertEqual(plan_parts(600), [(0, 600)])
        boundary = plan_parts(600.01)
        self.assertEqual(len(boundary), 2)
        self.assertAlmostEqual(boundary[0][1], 300.005)
        self.assertAlmostEqual(boundary[1][0], boundary[0][1])
        self.assertAlmostEqual(boundary[0][1], boundary[1][1])
        planned = plan_parts(9663.19)
        self.assertEqual(len(planned), 17)
        self.assertAlmostEqual(sum(length for _, length in planned), 9663.19)
        self.assertAlmostEqual(planned[0][1], planned[1][1])
        for duration in (0.001, 1, 600, 1200, 7200, 14400, 7200 * 100 + 0.1):
            parts = plan_parts(duration)
            self.assertLessEqual(len(parts), 20)
            self.assertTrue(all(length > 0 for _, length in parts))
            self.assertAlmostEqual(max(p[1] for p in parts), min(p[1] for p in parts))
            self.assertAlmostEqual(sum(length for _, length in parts), duration)
            for (start, length), (next_start, _) in zip(parts, parts[1:]):
                self.assertAlmostEqual(start + length, next_start)
        for duration in (0, -1, float("nan"), float("inf")):
            with self.assertRaises(ASRError): plan_parts(duration)
        for minutes, count in ((10, 1), (23, 3), (93, 10), (200, 20),
                               (200.001, 20), (400, 20), (600, 20), (3600, 20)):
            planned = plan_parts(minutes * 60)
            self.assertEqual(len(planned), count)
            self.assertAlmostEqual(planned[0][1], minutes * 60 / count)

    def test_real_pyav_extraction_preserves_duration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            p = root / "原音频.wav"
            wav(p, 3)
            info = probe(p)
            self.assertEqual(info.duration, 3)
            original = p.read_bytes()
            with patch("jianying_asr.media.SEGMENT_SECONDS", 2):
                cut = prepare_part(p, info, 2, 1, root, Budget(30))
            self.assertAlmostEqual(probe(cut).duration, 1, places=4)
            self.assertEqual(p.read_bytes(), original)

    def test_video_extracts_first_audio_track_without_changing_source(self):
        import shutil
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "视频.mkv"
            # A fixed input fixture keeps this extraction test independent of
            # video encoders: the tool needs to read audio, not create videos.
            shutil.copyfile(ROOT / "tests/fixtures/video-audio.mkv", source)
            before = source.read_bytes()
            info = probe(source)
            self.assertFalse(info.audio_only)
            extracted = prepare_part(source, info, 0, info.duration, root, Budget(30))
            self.assertNotEqual(extracted, source)
            self.assertTrue(probe(extracted).audio_only)
            self.assertAlmostEqual(probe(extracted).duration, 2, places=4)
            self.assertEqual(source.read_bytes(), before)

    def test_offsets_words_raw_preservation_and_all_formats(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = response("汉字 {符号}\n第二行")
            write_json(root / "raw.json", raw)
            part = {"status": "completed", "offset_ms": 7200000, "raw_result": "raw.json"}
            files, stats = write_outputs(root, "结果", ["json", "txt", "srt", "ass"], [part], Budget(30))
            data = json.loads((root / "结果.json").read_text(encoding="utf-8"))
            self.assertEqual(data[0]["startMs"], 7200010)
            self.assertEqual(data[0]["words"][0]["endMs"], 7200010)
            self.assertEqual(stats["non_positive_word_durations"], 1)
            self.assertIn("02:00:00,010", (root / "结果.srt").read_text(encoding="utf-8"))
            self.assertIn("2:00:00.01", (root / "结果.ass").read_text(encoding="utf-8"))
            self.assertEqual(json.loads((root / "raw.json").read_text(encoding="utf-8")), raw)
            self.assertTrue(all(Path(f["path"]).stat().st_size == f["bytes"] for f in files))

    def test_malformed_words_not_silently_dropped(self):
        raw = response()
        raw["data"]["utterances"][0]["words"][0].pop("start_time")
        with self.assertRaises(ASRError): list(segments(raw, 0))

    def test_empty_recognition_writes_valid_empty_json(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_json(root / "raw.json", {"ret": "0", "data": {"utterances": []}})
            files, stats = write_outputs(root, "empty", ["json"], [{"status": "completed", "offset_ms": 0, "raw_result": "raw.json"}], Budget(30))
            self.assertEqual(json.loads(Path(files[0]["path"]).read_text()), [])
            self.assertEqual(stats["segments"], 0)


class JobTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.audio = self.root / "会议.wav"
        wav(self.audio)
        self.env = patch.dict(os.environ, {"TIANCE_WORKSPACE_ROOT": str(self.root)})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_defaults_workspace_json_and_no_overwrite(self):
        one = run({"input_path": "会议.wav"}, client_factory=FakeClient)
        two = run({"input_path": "会议.wav"}, client_factory=FakeClient)
        self.assertTrue(one["ok"], one)
        self.assertTrue(two["ok"], two)
        self.assertNotEqual(one["data"]["output_dir"], two["data"]["output_dir"])
        self.assertEqual(Path(one["data"]["output_dir"]).parent, self.root)
        self.assertEqual([f["format"] for f in one["data"]["files"]], ["json"])

    def test_failed_second_part_keeps_task_id_and_completed_raw(self):
        class FailsSecond(FakeClient):
            def upload(self, path):
                return "short" if probe(path).duration < 1.5 else "long"
            def submit(self, uri):
                return "task-2" if uri == "short" else "task-1"
            def poll(self, task_id):
                if task_id == "task-2": raise ASRError("NETWORK_ERROR", "断线")
                return response()
        with patch("jianying_asr.engine.plan_parts", return_value=[(0, 2), (2, 1)]), patch("jianying_asr.media.SEGMENT_SECONDS", 2):
            result = run({"input_path": str(self.audio)}, client_factory=FailsSecond)
        self.assertFalse(result["ok"])
        self.assertEqual(result["data"]["completed_parts"], 1)
        job = json.loads(Path(result["data"]["job_file"]).read_text(encoding="utf-8"))
        self.assertEqual(job["parts"][1]["task_id"], "task-2")
        self.assertTrue((Path(result["data"]["output_dir"]) / "parts/0001.raw.json").exists())
        self.assertEqual(job["files"], [])

    def test_two_real_audio_cuts_merged_to_source_timeline(self):
        with patch("jianying_asr.engine.plan_parts", return_value=[(0, 2), (2, 1)]), patch("jianying_asr.media.SEGMENT_SECONDS", 2):
            result = run({"input_path": str(self.audio)}, client_factory=FakeClient)
        self.assertTrue(result["ok"], result)
        data = json.loads(Path(result["data"]["files"][0]["path"]).read_text(encoding="utf-8"))
        self.assertEqual([s["startMs"] for s in data], [10, 2010])
        self.assertEqual(data[1]["words"][0]["startMs"], 2010)

    def test_invalid_arguments_before_upload(self):
        for payload in [{}, [], {"input_path": "missing.wav"}, {"input_path": str(self.audio), "formats": []},
                        {"input_path": str(self.audio), "formats": ["json", "json"]},
                        {"input_path": str(self.audio), "formats": "json"},
                        {"input_path": str(self.audio), "timeout_seconds": 1}]:
            with self.subTest(payload=payload):
                result = run(payload, client_factory=lambda _: self.fail("must not upload"))
                self.assertFalse(result["ok"])

    def test_standalone_json_entry_failure_exit_code(self):
        code = ("import sys,runpy;sys.path.insert(0," + repr(str(PRIVATE)) + ");"
                "sys.path.insert(0," + repr(str(ROOT / "program")) + ");"
                "runpy.run_path(" + repr(str(ROOT / "program/main.py")) + ",run_name='__main__')")
        done = subprocess.run([sys.executable, "-X", "utf8", "-c", code], input='{"input_path":"not-found.wav"}',
                              capture_output=True, text=True, encoding="utf-8", timeout=15)
        self.assertEqual(done.returncode, 1)
        self.assertEqual(json.loads(done.stdout)["error_code"], "INPUT_NOT_FOUND")


if __name__ == "__main__":
    unittest.main()
