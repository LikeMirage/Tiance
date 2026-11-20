from __future__ import annotations

import array
import math
import tempfile
import unittest
import wave
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from test_media import av, encode, pcm
from test_media_copy import presented_packets
from test_transcribe import FakeClient, run
from jianying_asr.common import ASRError, Budget
from jianying_asr.media import plan_parts, prepare_part, probe
from jianying_asr.segmentation import _pauses, refine_parts


class SilenceSegmentationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def recording(self, pauses=(), *, stereo=False, right_talking=False, seconds=20):
        path = self.root / "source.wav"
        rate = 16000
        data = array.array("h")
        for index in range(rate * seconds):
            quiet = any(left <= index / rate < right for left, right in pauses)
            # A nonzero noise floor in the pause, not just synthetic zero bytes.
            tone = round(12000 * math.sin(2 * math.pi * 440 * index / rate))
            left = round(200 * math.sin(2 * math.pi * 130 * index / rate)) if quiet else tone
            data.append(left)
            if stereo:
                data.append(-tone if right_talking else -left)
        with wave.open(str(path), "wb") as writer:
            writer.setnchannels(2 if stereo else 1)
            writer.setsampwidth(2)
            writer.setframerate(rate)
            writer.writeframes(data.tobytes())
        return path

    def plan(self, source):
        info = probe(source)
        original = plan_parts(info.duration, segment_seconds=10, frame_seconds=info.copy_frame_seconds)
        parts, metadata = refine_parts(source, info, original, Budget(30))
        return info, original, parts, metadata["boundaries"]

    def test_nearby_pause_moves_cut_and_keeps_every_pcm_sample(self):
        source = self.recording([(11, 11.8)], stereo=True)
        info, _, parts, decisions = self.plan(source)
        self.assertEqual(len(parts), 2)
        self.assertEqual(decisions[0]["reason"], "silence")
        self.assertAlmostEqual(parts[1][0], 11.4, delta=.04)
        merged = bytearray()
        for number, (start, length) in enumerate(parts):
            folder = self.root / str(number)
            folder.mkdir()
            output = prepare_part(source, info, start, length, folder, Budget(30))
            merged.extend(pcm(output)[0])
        self.assertEqual(merged, pcm(source)[0])

    def test_existing_pause_keeps_target(self):
        source = self.recording([(9.6, 10.4)])
        _, original, parts, decisions = self.plan(source)
        self.assertEqual(parts, original)
        self.assertEqual(decisions[0]["reason"], "silence")

    def test_no_pause_short_gap_or_distant_pause_keeps_balanced_plan(self):
        for pauses in ([], [(10.3, 10.5)], [(16, 18)]):
            with self.subTest(pauses=pauses):
                _, original, parts, decisions = self.plan(self.recording(pauses))
                self.assertEqual(parts, original)
                self.assertEqual(decisions[0]["reason"], "no_pause")

    def test_one_talking_channel_and_opposite_phase_are_not_silence(self):
        for pauses in ([], [(11, 11.8)]):
            source = self.recording(pauses, stereo=True, right_talking=True)
            _, original, parts, decisions = self.plan(source)
            self.assertEqual(parts, original)
            self.assertEqual(decisions[0]["reason"], "no_pause")

    def test_nonzero_audio_origin_does_not_shift_pause(self):
        wav = self.recording([(11, 11.8)])
        source = self.root / "offset.nut"
        encode(wav, source, codec="pcm_s16le", origin=5 * 16000)
        # NUT reports an estimated container end, not an exact stream duration.
        # This fixture has exactly 20 seconds of samples starting at t=5.
        info = replace(probe(source), duration=20)
        parts, metadata = refine_parts(source, info, plan_parts(20, segment_seconds=10), Budget(30))
        self.assertAlmostEqual(parts[1][0], 11.4, delta=.04)
        self.assertEqual(metadata["boundaries"][0]["reason"], "silence")

    def test_aac_adjustment_preserves_frame_alignment_and_all_packets(self):
        wav = self.recording([(11, 11.8)], stereo=True)
        source = self.root / "source.m4a"
        encode(wav, source, codec="aac")
        info, _, parts, decisions = self.plan(source)
        self.assertIsNotNone(info.copy_frame_seconds)
        self.assertEqual(decisions[0]["reason"], "silence")
        self.assertAlmostEqual(parts[1][0], 11.4, delta=.08)
        self.assertAlmostEqual(parts[1][0] / float(info.copy_frame_seconds),
                               round(parts[1][0] / float(info.copy_frame_seconds)))
        merged = []
        for number, (start, length) in enumerate(parts):
            folder = self.root / str(number)
            folder.mkdir()
            output = prepare_part(source, info, start, length, folder, Budget(30))
            merged.extend((pts + round(start * 16000), data) for pts, data in presented_packets(output))
        self.assertEqual(merged, presented_packets(source))

    def test_single_part_never_opens_analysis(self):
        source = self.recording(seconds=1)
        info = probe(source)
        with patch("jianying_asr.segmentation._levels", side_effect=AssertionError("unnecessary decode")):
            parts, meta = refine_parts(source, info, plan_parts(info.duration), Budget(30))
        self.assertEqual(parts, [(0, 1)])
        self.assertEqual(meta["boundaries"], [])

    def test_optional_decode_failure_falls_back_but_cancellation_propagates(self):
        source = self.recording()
        info = probe(source)
        original = plan_parts(info.duration, segment_seconds=10)
        with patch("jianying_asr.segmentation._levels", side_effect=ValueError("bad timestamp")):
            parts, meta = refine_parts(source, info, original, Budget(30))
        self.assertEqual(parts, original)
        self.assertEqual(meta["boundaries"][0]["reason"], "analysis_unavailable")
        for code in ("TIMEOUT", "CANCELLED"):
            with patch("jianying_asr.segmentation._levels", side_effect=ASRError(code, code)):
                with self.assertRaisesRegex(ASRError, code):
                    refine_parts(source, info, original, Budget(30))

    def test_missing_audio_and_a_loud_frame_do_not_join_quiet_intervals(self):
        for middle in ([], [(0.2, .22, -10)]):
            frames = [(i * .02, (i + 1) * .02, -60) for i in range(10)]
            frames += middle
            frames += [(.24 + i * .02, .24 + (i + 1) * .02, -60) for i in range(10)]
            frames += [(1 + i * .02, 1 + (i + 1) * .02, -10) for i in range(30)]
            self.assertEqual(_pauses(frames)[0], [])

    def test_job_records_actual_boundary_and_uses_it_for_subtitle_offsets(self):
        import json
        source = self.recording([(11, 11.8)])
        with patch("jianying_asr.engine.plan_parts", return_value=[(0, 10), (10, 10)]):
            result = run({"input_path": str(source), "output_dir": str(self.root)},
                         client_factory=FakeClient, budget=Budget(30))
        self.assertTrue(result["ok"], result)
        job = json.loads(Path(result["data"]["job_file"]).read_text(encoding="utf-8"))
        self.assertEqual(job["split_mode"], "silence_aware_balanced")
        self.assertEqual(job["concurrent_parts"], 2)
        cut = job["segmentation"]["boundaries"][0]["actual_seconds"]
        self.assertAlmostEqual(cut, 11.4, delta=.04)
        self.assertEqual(job["parts"][1]["offset_ms"], round(cut * 1000))
        output = json.loads(Path(result["data"]["files"][0]["path"]).read_text(encoding="utf-8-sig"))
        self.assertEqual(output[1]["startMs"], round(cut * 1000) + 10)


if __name__ == "__main__":
    unittest.main()
