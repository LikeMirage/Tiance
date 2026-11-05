from __future__ import annotations

import array
import hashlib
import math
import sys
import tempfile
import unittest
import wave
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "program"))
sys.path.insert(0, str(ROOT / "dependencies/py313/site-packages"))

from jianying_asr.media_runtime import get_av
av = get_av()
from jianying_asr.common import ASRError, Budget
from jianying_asr.media import plan_parts, prepare_part, probe


def pcm(path: Path, sample_format="s16"):
    """Decode fixture/output to packed PCM without depending on NumPy."""
    data = bytearray()
    with av.open(str(path)) as container:
        stream = container.streams.audio[0]
        rate, channels = stream.codec_context.sample_rate, stream.codec_context.channels
        for frame in container.decode(stream):
            assert frame.format.name == sample_format
            data.extend(memoryview(frame.planes[0])[:frame.samples * channels * frame.format.bytes])
    return bytes(data), rate, channels


def encode(source: Path, target: Path, codec="flac", origin=0):
    # M4A is an MP4 audio container; avoid selecting the optional iPod muxer.
    container_format = "mp4" if target.suffix == ".m4a" else None
    with av.open(str(source)) as reader, av.open(str(target), "w", format=container_format) as writer:
        original = reader.streams.audio[0]
        output = writer.add_stream(codec, rate=original.codec_context.sample_rate)
        output.layout = "stereo" if original.codec_context.channels == 2 else original.codec_context.layout
        for frame in reader.decode(original):
            frame.pts += origin
            for packet in output.encode(frame): writer.mux(packet)
        for packet in output.encode(None): writer.mux(packet)


class MediaPrecisionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "双声道.wav"
        self.rate = 44100
        samples = array.array("h", ((index * 613 + channel * 719) % 50001 - 25000
                                   for index in range(self.rate * 3) for channel in range(2)))
        self.original = samples.tobytes()
        with wave.open(str(self.source), "wb") as output:
            output.setnchannels(2)
            output.setsampwidth(2)
            output.setframerate(self.rate)
            output.writeframes(self.original)

    def check_adjacent_parts(self, source):
        info = probe(source)
        before = hashlib.sha256(source.read_bytes()).digest()
        boundaries = [0, 44123, 88261, self.rate * 3]
        merged = bytearray()
        with patch("jianying_asr.media.SEGMENT_SECONDS", 1):
            for index, (begin, end) in enumerate(zip(boundaries, boundaries[1:])):
                folder = self.root / f"part{index}"
                folder.mkdir(exist_ok=True)
                output = prepare_part(source, info, begin / self.rate, (end - begin) / self.rate,
                                      folder, Budget(30))
                data, rate, channels = pcm(output)
                self.assertEqual((rate, channels), (self.rate, 2))
                self.assertEqual(data, self.original[begin * 4:end * 4])
                merged.extend(data)
        self.assertEqual(merged, self.original)
        self.assertEqual(hashlib.sha256(source.read_bytes()).digest(), before)

    def test_wav_sample_exact_adjacent_parts_keep_stereo_and_rate(self):
        self.check_adjacent_parts(self.source)

    def test_balanced_fractional_cuts_preserve_every_sample(self):
        info = probe(self.source)
        merged = bytearray()
        parts = plan_parts(info.duration, segment_seconds=0.28)
        self.assertEqual(len(parts), 11)
        for index, (start, length) in enumerate(parts):
            folder = self.root / f"balanced-{index}"
            folder.mkdir()
            output = prepare_part(self.source, info, start, length, folder, Budget(30))
            self.assertNotEqual(output, self.source)
            data, rate, channels = pcm(output)
            self.assertEqual((rate, channels), (self.rate, 2))
            merged.extend(data)
        self.assertEqual(merged, self.original)

    def test_flac_sample_exact_adjacent_parts_after_seek(self):
        source = self.root / "compressed.flac"
        encode(self.source, source)
        self.check_adjacent_parts(source)

    def test_nonzero_audio_start_is_relative_to_audio_origin(self):
        source = self.root / "offset.nut"
        encode(self.source, source, codec="pcm_s16le", origin=5 * self.rate)
        with av.open(str(source)) as reader:
            stream = reader.streams.audio[0]
            self.assertEqual(stream.start_time * stream.time_base, 5)
        self.check_adjacent_parts(source)

    def test_unseekable_container_decodes_from_start(self):
        source = self.root / "compressed.flac"
        encode(self.source, source)
        original_open = av.open
        attempts = []
        class Unseekable:
            def __init__(self, reader): self.reader = reader
            def __enter__(self): return self
            def __exit__(self, *_): self.reader.close()
            def __getattr__(self, name): return getattr(self.reader, name)
            def seek(self, *args, **kwargs):
                attempts.append(args)
                raise av.error.FFmpegError(1, "no seek")
        def open_container(path, mode="r", **kwargs):
            container = original_open(path, mode, **kwargs)
            return Unseekable(container) if mode == "r" else container
        with patch.object(av, "open", side_effect=open_container):
            self.check_adjacent_parts(source)
        self.assertEqual(len(attempts), 2)

    def test_aac_float_frames_seek_and_exact_length(self):
        tones = array.array("h", (round(14000 * math.sin(2 * math.pi * (440 + channel * 220) * index / self.rate))
                                  for index in range(self.rate * 3) for channel in range(2)))
        with wave.open(str(self.source), "wb") as output:
            output.setnchannels(2)
            output.setsampwidth(2)
            output.setframerate(self.rate)
            output.writeframes(tones.tobytes())
        source = self.root / "audio.m4a"
        encode(self.source, source, codec="aac")
        before = source.read_bytes()
        info = probe(source)
        # Retain coverage of the decoded fallback independently of packet copy.
        info = replace(info, copy_frame_seconds=None)
        with patch("jianying_asr.media.SEGMENT_SECONDS", 1):
            full = prepare_part(source, info, 0, info.duration, self.root, Budget(30))
            reference, _, _ = pcm(full, "s32")
            for start in (1, 2):
                output = prepare_part(source, info, start, 1, self.root, Budget(30))
                data, rate, channels = pcm(output, "s32")
                self.assertEqual((rate, channels), (self.rate, 2))
                self.assertEqual(len(data), self.rate * 2 * 4)
                expected = array.array("i", reference[start * self.rate * 8:(start + 1) * self.rate * 8])
                actual = array.array("i", data)
                # AAC noise synthesis may differ after seeking. Check waveform
                # alignment within 0.1% RMS instead of requiring lossless equality.
                relative_error = math.sqrt(sum((a - b) ** 2 for a, b in zip(actual, expected))
                                           / sum(b * b for b in expected))
                self.assertLess(relative_error, 0.001)
        self.assertEqual(source.read_bytes(), before)

    def test_24bit_pcm_preserves_all_samples(self):
        source = self.root / "24bit.wav"
        raw = b"".join(((index * 2613) % 16777216).to_bytes(3, "little")
                       for index in range(self.rate * 2))
        with wave.open(str(source), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(3)
            output.setframerate(self.rate)
            output.writeframes(raw)
        original, _, _ = pcm(source, "s32")
        with patch("jianying_asr.media.SEGMENT_SECONDS", 1):
            cut = prepare_part(source, probe(source), 1, 1, self.root, Budget(30))
        data, rate, channels = pcm(cut, "s32")
        self.assertEqual((rate, channels), (self.rate, 1))
        self.assertEqual(data, original[self.rate * 4:])

    def test_budget_expires_during_decoding(self):
        budget = Budget(30)
        checks = 0
        def remaining():
            nonlocal checks
            checks += 1
            if checks > 8:
                raise ASRError("TIMEOUT", "test budget exhausted")
            return 10
        with patch("jianying_asr.media.SEGMENT_SECONDS", 1), patch.object(budget, "remaining", side_effect=remaining):
            with self.assertRaisesRegex(ASRError, "test budget exhausted"):
                prepare_part(self.source, probe(self.source), 0, 2, self.root, budget)


if __name__ == "__main__":
    unittest.main()
