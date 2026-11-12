from __future__ import annotations

import json
import os
import struct
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from test_transcribe import FakeClient, ROOT, wav
from jianying_asr.common import ASRError, Budget
from jianying_asr.runner import run
from jianying_asr.silk import HEADER, prepare_source

FIXTURE = ROOT / "tests/fixtures/tone.silk"


@unittest.skipUnless(os.name == "nt", "bundled SILK decoder requires Windows")
class SilkTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def source(self, data=None, name="微信语音.speex"):
        path = self.root / name
        path.write_bytes(FIXTURE.read_bytes() if data is None else data)
        return path

    def test_standard_and_wechat_headers_decode_regardless_of_suffix(self):
        original = FIXTURE.read_bytes()
        for prefix, suffix in ((b"", ".silk"), (b"\x02", ".speex"), (b"\x02", ".bin")):
            with self.subTest(suffix=suffix):
                source = self.source(prefix + original, name="中文输入" + suffix)
                before = source.read_bytes()
                with prepare_source(source, Budget(30)) as converted:
                    self.assertNotEqual(converted, source)
                    with wave.open(str(converted), "rb") as audio:
                        self.assertEqual((audio.getnchannels(), audio.getsampwidth(), audio.getframerate()), (1, 2, 24000))
                        self.assertEqual(audio.getnframes(), 24000)
                        self.assertTrue(any(audio.readframes(audio.getnframes())))
                self.assertFalse(converted.parent.exists())
                self.assertEqual(source.read_bytes(), before)

    def test_short_ascii_native_arguments_even_with_long_unicode_input_path(self):
        source = self.root / ("中文" * 30) / ("音频" * 30 + ".speex")
        source.parent.mkdir()
        source.write_bytes(b"\x02" + FIXTURE.read_bytes())
        actual_run = subprocess.run
        with patch("jianying_asr.silk.subprocess.run", wraps=actual_run) as process:
            with prepare_source(source, Budget(30)) as converted:
                self.assertTrue(converted.is_file())
            args = process.call_args.args[0]
            self.assertEqual(args[1:3], ["input.silk", "audio.pcm"])
            self.assertNotIn(str(source), args)

    def test_one_packet_is_not_duplicated_in_output(self):
        data = FIXTURE.read_bytes()
        size = struct.unpack("<h", data[len(HEADER):len(HEADER) + 2])[0]
        source = self.source(data[:len(HEADER) + 2 + size])
        with prepare_source(source, Budget(30)) as converted:
            with wave.open(str(converted), "rb") as audio:
                self.assertEqual(audio.getnframes() / audio.getframerate(), 0.02)

    def test_regular_media_keeps_existing_route_despite_speex_suffix(self):
        source = self.root / "audio.speex"
        wav(source)
        with patch("jianying_asr.silk.subprocess.run") as process:
            with prepare_source(source, Budget(30)) as prepared:
                self.assertEqual(prepared, source)
            process.assert_not_called()
        self.assertTrue(source.exists())

    def test_malformed_packet_streams_fail_before_native_execution_or_upload(self):
        cases = [HEADER, HEADER + b"\x01", HEADER + b"\x02\x00a",
                 HEADER + b"\x00\x00", HEADER + struct.pack("<h", 5121),
                 HEADER + b"\xfe\xff", FIXTURE.read_bytes() + b"unexpected"]
        for data in cases:
            with self.subTest(data_length=len(data)):
                source = self.source(data)
                with patch("jianying_asr.silk.subprocess.run") as process, patch.object(FakeClient, "upload") as upload:
                    result = run({"input_path": str(source), "output_dir": str(self.root)}, client_factory=FakeClient)
                    self.assertFalse(result["ok"])
                    self.assertEqual(result["error_code"], "INVALID_SILK")
                    process.assert_not_called()
                    upload.assert_not_called()

    def test_native_zero_exit_with_error_is_not_success(self):
        source = self.source()
        working_directories = []
        def failed_decode(args, **kwargs):
            working_directories.append(kwargs["cwd"])
            kwargs["stdout"].write(b"Error: failed to open input\n")
            return subprocess.CompletedProcess(args, 0)
        with patch("jianying_asr.silk.subprocess.run", side_effect=failed_decode):
            result = run({"input_path": str(source), "output_dir": str(self.root)}, client_factory=FakeClient)
        self.assertEqual(result["error_code"], "SILK_DECODE_FAILED")
        self.assertFalse(working_directories[0].exists())

    def test_decoder_timeout_cleans_up_and_uses_remaining_job_budget(self):
        source = self.source()
        budget = Budget(30)
        working_directories = []
        def timeout(args, **kwargs):
            working_directories.append(kwargs["cwd"])
            self.assertGreater(kwargs["timeout"], 0)
            self.assertLessEqual(kwargs["timeout"], 30)
            raise subprocess.TimeoutExpired(args, kwargs["timeout"])
        with patch("jianying_asr.silk.subprocess.run", side_effect=timeout):
            result = run({"input_path": str(source), "output_dir": str(self.root)}, client_factory=FakeClient, budget=budget)
        self.assertEqual(result["error_code"], "TIMEOUT")
        self.assertFalse(working_directories[0].exists())

    def test_missing_decoder_has_explicit_dependency_error(self):
        source = self.source()
        with patch("jianying_asr.silk.DECODER", self.root / "missing.exe"):
            with self.assertRaises(ASRError) as caught:
                with prepare_source(source, Budget(30)):
                    self.fail("must not continue")
        self.assertEqual(caught.exception.code, "DEPENDENCY_MISSING")

    def test_pipeline_uploads_decoded_audio_but_reports_original_path_and_name(self):
        source = self.source(b"\x02" + FIXTURE.read_bytes())
        original = source.read_bytes()
        uploaded = []
        class Client(FakeClient):
            def upload(self, path):
                uploaded.append(path)
                with wave.open(str(path), "rb") as audio:
                    self_length = audio.getnframes() / audio.getframerate()
                if self_length != 1:
                    raise AssertionError(self_length)
                return "uploaded"
        result = run({"input_path": str(source), "output_dir": str(self.root), "formats": ["json", "txt"]}, client_factory=Client)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["data"]["input_path"], str(source))
        job = json.loads(Path(result["data"]["job_file"]).read_text(encoding="utf-8"))
        self.assertEqual(job["source_decoding"], "silk_v3_to_wav")
        self.assertEqual(job["parts"][0]["audio_processing"], "silk_decoded_wav")
        self.assertTrue((Path(result["data"]["output_dir"]) / (source.stem + ".txt")).is_file())
        self.assertEqual(source.read_bytes(), original)
        self.assertEqual(len(uploaded), 1)
        self.assertFalse(uploaded[0].exists())

    def test_cloud_failure_also_removes_decoded_temporary_audio(self):
        source = self.source()
        uploaded = []
        class FailingClient(FakeClient):
            def upload(self, path):
                uploaded.append(path)
                raise ASRError("TEST_FAILURE", "mock cloud failure")
        result = run({"input_path": str(source), "output_dir": str(self.root)}, client_factory=FailingClient)
        self.assertFalse(result["ok"])
        self.assertEqual(result["data"]["completed_parts"], 0)
        self.assertFalse(uploaded[0].exists())
        self.assertTrue(source.exists())
