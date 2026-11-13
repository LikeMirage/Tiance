from __future__ import annotations

import asyncio
import io
import json
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from test_transcribe import FakeClient, response, httpx, JianyingClient
import test_parallel
from jianying_asr.common import ASRError, Budget
from jianying_asr.client import upload_chunks
from jianying_asr.media import MediaInfo


class NetworkDeadlineTests(unittest.TestCase):
    def test_blocked_upload_expires_and_releases_source_reader(self):
        consumed = []

        class BlockedUpload(httpx.AsyncBaseTransport):
            async def handle_async_request(self, request):
                async for block in request.stream:
                    consumed.append(len(block))
                    await asyncio.Event().wait()
                raise AssertionError("must be cancelled during upload")

        source_reader = io.BytesIO(b"test audio")
        with JianyingClient(Budget(30), transport=BlockedUpload()) as client:
            client.budget.deadline = time.monotonic() + 0.1
            with patch.object(Path, "open", return_value=source_reader):
                with self.assertRaises(ASRError) as caught:
                    client.request("PUT", "https://upload.test/audio", "上传音频",
                                   content=upload_chunks(Path("fixture.wav"), client.budget))
                self.assertEqual(caught.exception.code, "TIMEOUT")
        self.assertEqual(consumed, [10])
        self.assertTrue(source_reader.closed)

    def test_no_headers_is_cancelled_at_total_deadline(self):
        cancelled = []

        async def handler(_):
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.append(True)

        with JianyingClient(Budget(30), transport=httpx.MockTransport(handler)) as client:
            client.budget.deadline = time.monotonic() + 0.1
            started = time.monotonic()
            with self.assertRaises(ASRError) as caught:
                client.poll("already-submitted")
            self.assertEqual(caught.exception.code, "TIMEOUT")
            self.assertLess(time.monotonic() - started, 1)
            self.assertEqual(cancelled, [True])

    def test_dripping_body_does_not_restart_deadline_and_connection_closes(self):
        class Dripping(httpx.AsyncByteStream):
            closed = False
            delivered = 0

            async def __aiter__(self):
                while True:
                    await asyncio.sleep(0.02)
                    self.delivered += 1
                    yield b" "

            async def aclose(self):
                self.closed = True

        stream = Dripping()
        with JianyingClient(Budget(30), transport=httpx.MockTransport(
                lambda _: httpx.Response(200, stream=stream))) as client:
            client.budget.deadline = time.monotonic() + 0.12
            started = time.monotonic()
            with self.assertRaises(ASRError) as caught:
                client.poll("already-submitted")
            self.assertEqual(caught.exception.code, "TIMEOUT")
            self.assertLess(time.monotonic() - started, 1)
            self.assertGreater(stream.delivered, 1)
            self.assertTrue(stream.closed)

    def test_timeout_covers_headers_and_body_together(self):
        class SlowBody(httpx.AsyncByteStream):
            async def __aiter__(self):
                await asyncio.sleep(0.1)
                yield json.dumps(response()).encode()

        async def handler(_):
            await asyncio.sleep(0.1)
            return httpx.Response(200, stream=SlowBody())

        with JianyingClient(Budget(30), transport=httpx.MockTransport(handler)) as client:
            client.budget.deadline = time.monotonic() + 0.16
            with self.assertRaises(ASRError) as caught:
                client.poll("task")
            self.assertEqual(caught.exception.code, "TIMEOUT")

    def test_rejected_long_audio_is_not_resubmitted(self):
        seen = []

        def handler(request):
            seen.append(request.url.path)
            return httpx.Response(200, json={"ret": 4001, "errmsg": "audio duration not supported"})

        with JianyingClient(Budget(30), transport=httpx.MockTransport(handler)) as client:
            with self.assertRaises(ASRError) as caught:
                client.submit("uploaded-three-hour-part")
        self.assertEqual(caught.exception.code, "UPSTREAM_ERROR")
        self.assertIn("audio duration not supported", str(caught.exception))
        self.assertEqual(len(seen), 1)

    def test_query_retries_same_id_and_reports_recovery(self):
        seen = []

        def handler(request):
            seen.append(json.loads(request.read())["id"])
            if len(seen) == 1:
                raise httpx.RemoteProtocolError("private signed URL", request=request)
            if len(seen) == 2:
                return httpx.Response(429)
            return httpx.Response(200, json=response())

        with JianyingClient(Budget(30), transport=httpx.MockTransport(handler)) as client, \
                patch.object(client.budget, "sleep"):
            self.assertEqual(client.poll("original-task"), response())
            self.assertEqual(seen, ["original-task"] * 3)
            self.assertEqual(len(client.warnings), 1)
            self.assertIn("2 次", client.warnings[0])
            self.assertNotIn("private", client.warnings[0])

    def test_empty_http_body_is_failure_not_silent_success(self):
        with JianyingClient(Budget(30), transport=httpx.MockTransport(
                lambda _: httpx.Response(200, content=b""))) as client:
            with self.assertRaises(ASRError) as caught:
                client.poll("task")
            self.assertEqual(caught.exception.code, "INVALID_RESPONSE")


class FailedPartsTests(unittest.TestCase):
    setUp = test_parallel.ParallelJobTests.setUp
    execute = test_parallel.ParallelJobTests.execute

    def test_one_timeout_keeps_completed_parts_and_terminal_checkpoint(self):
        class Partial(FakeClient):
            def __init__(self, budget, **kwargs):
                super().__init__(budget, **kwargs)
                self.budget = budget

            def upload(self, path): return path.name
            def submit(self, uri): return uri

            def poll(self, task_id):
                if task_id != "1":
                    return response(task_id)

                async def no_response(_):
                    await asyncio.Event().wait()

                with JianyingClient(self.budget, transport=httpx.MockTransport(no_response)) as client:
                    return client.poll(task_id)

        budget = Budget(30)
        budget.deadline = time.monotonic() + 0.5
        result, job = self.execute(3, Partial, budget)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "TIMEOUT")
        self.assertEqual(result["data"]["completed_parts"], 2)
        self.assertEqual([p["status"] for p in job["parts"]], ["completed", "failed", "completed"])
        self.assertEqual(job["files"], [])
        self.assertEqual(result["data"]["failed_parts"][0]["error_stage"], "processing")
        self.assertEqual(result["data"]["failed_parts"][0]["task_id"], "1")

    def test_three_hour_part_rejection_has_no_resplit_or_partial_success(self):
        from jianying_asr.runner import run
        uploads = []

        def prepare(_source, _info, start, length, temporary, _budget):
            self.assertAlmostEqual(length, 3 * 3600)
            path = temporary / str(int(start))
            path.write_bytes(b"offline fixture")
            return path

        class Reject(FakeClient):
            def upload(self, path):
                uploads.append(path.name)
                return path.name

            def submit(self, uri):
                raise ASRError("UPSTREAM_ERROR", "audio duration not supported")

        with patch("jianying_asr.engine.probe", return_value=MediaInfo(60 * 3600, True)), \
                patch("jianying_asr.parallel.prepare_part", side_effect=prepare):
            result = run({"input_path": str(self.source)}, client_factory=Reject)
        self.assertFalse(result["ok"])
        self.assertEqual(len(uploads), 20)
        self.assertEqual(result["data"]["total_parts"], 20)
        self.assertEqual(result["data"]["completed_parts"], 0)
        self.assertEqual(len(result["data"]["failed_parts"]), 20)
        for part in result["data"]["failed_parts"]:
            self.assertEqual(part["duration_seconds"], 10800)
            self.assertEqual(part["error_stage"], "submitting")
            self.assertEqual(part["error_code"], "UPSTREAM_ERROR")
            self.assertNotIn("task_id", part)

    def test_explicit_empty_transcript_is_reported_without_inventing_silence(self):
        class Empty(FakeClient):
            def poll(self, task_id): return {"ret": "0", "data": {"utterances": []}}

        result, _ = self.execute(2, Empty)
        self.assertTrue(result["ok"])
        self.assertIn("空转写", result["summary"])
        self.assertEqual(len(result["data"]["warnings"]), 2)


if __name__ == "__main__":
    unittest.main()
