from __future__ import annotations

import array
import hashlib
import math
import tempfile
import unittest
import wave
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch

from test_media import av, encode
from jianying_asr.common import ASRError, Budget
from jianying_asr.media import plan_parts, prepare_part, probe


def decoded_channels(path):
    with av.open(str(path)) as reader:
        st = reader.streams.audio[0]
        output = [array.array('f') for _ in range(st.codec_context.channels)]
        for frame in reader.decode(st):
            assert frame.format.name == 'fltp'
            for channel, plane in zip(output, frame.planes):
                channel.frombytes(bytes(plane)[:frame.samples * 4])
        # AAC's final encoded frame can include padding beyond track duration.
        count = round(st.duration * st.time_base * st.codec_context.sample_rate)
        return [ch[:count] for ch in output]


def presented_packets(path):
    with av.open(str(path)) as reader:
        st = reader.streams.audio[0]
        return [(p.pts, bytes(p)) for p in reader.demux(st)
                if p.size and p.pts is not None and 0 <= p.pts < st.duration]


class PacketCopyTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.rate = 44100
        original = self.root / 'tone.wav'
        samples = array.array('h', (round(14000 * math.sin(2*math.pi*(440+c*220)*i/self.rate))
                                   for i in range(self.rate*4+137) for c in range(2)))
        with wave.open(str(original), 'wb') as out:
            out.setnchannels(2)
            out.setsampwidth(2)
            out.setframerate(self.rate)
            out.writeframes(samples.tobytes())
        self.source = self.root / 'aac.m4a'
        encode(original, self.source, codec='aac')

    def test_balanced_copy_preserves_packets_samples_and_timeline(self):
        before = hashlib.sha256(self.source.read_bytes()).digest()
        info = probe(self.source)
        self.assertEqual(info.copy_frame_seconds, Fraction(1024, self.rate))
        parts = plan_parts(info.duration, segment_seconds=1.31, frame_seconds=info.copy_frame_seconds)
        original_packets = presented_packets(self.source)
        reference = decoded_channels(self.source)
        merged_packets, merged_pcm = [], [array.array('f'), array.array('f')]
        for i, (start, length) in enumerate(parts):
            temp = self.root / str(i)
            temp.mkdir()
            result = prepare_part(self.source, info, start, length, temp, Budget(30))
            self.assertEqual(result.suffix, '.m4a')
            self.assertLess(length, 1.31)
            offset = round(start*self.rate)
            merged_packets.extend((pts+offset, payload) for pts,payload in presented_packets(result))
            channels = decoded_channels(result)
            self.assertEqual(len(channels[0]), round(length*self.rate))
            for merged, channel in zip(merged_pcm, channels): merged.extend(channel)
            with av.open(str(result)) as reader:
                st = reader.streams.audio[0]
                self.assertEqual(st.start_time, 0)
                self.assertEqual(st.codec_context.sample_rate, self.rate)
                self.assertEqual(st.codec_context.channels, 2)
                self.assertAlmostEqual(float(st.duration*st.time_base), length, places=8)
        self.assertEqual(merged_packets, original_packets)
        for actual, expected in zip(merged_pcm, reference):
            self.assertEqual(len(actual), len(expected))
            error = math.sqrt(sum((a-b)**2 for a,b in zip(actual,expected))/sum(x*x for x in expected))
            # AAC PNS noise synthesis restarts after seeking; packet bytes are
            # asserted identical above. A 0.5% RMS bound catches time shifts
            # without treating the decoder's noise seed as re-encoding loss.
            self.assertLess(error, 0.005)
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).digest(), before)

    def test_direct_audio_still_returns_original(self):
        info = probe(self.source)
        self.assertEqual(prepare_part(self.source, info, 0, info.duration, self.root, Budget(30)), self.source)

    def test_unaligned_cut_rejected_without_modifying_source(self):
        before = self.source.read_bytes()
        with self.assertRaisesRegex(ASRError, '切点未对齐'):
            prepare_part(self.source, probe(self.source), 1, 1, self.root, Budget(30))
        self.assertEqual(self.source.read_bytes(), before)

    def test_frame_alignment_preserves_coverage_without_extra_parts(self):
        step = Fraction(1024, 48000)
        for duration in (600, 1199.999, 1800, 7200, 9663.19, 12000, 12000.01, 216000):
            parts = plan_parts(duration, segment_seconds=600, frame_seconds=step)
            self.assertEqual(len(parts), min(20, math.ceil(duration / 600)))
            self.assertAlmostEqual(sum(x[1] for x in parts), duration)
            self.assertTrue(all(abs(p[1]-duration/len(parts)) < float(step)+1e-9 for p in parts))
            for i,(start,length) in enumerate(parts):
                self.assertGreater(length, 0)
                self.assertEqual(round(start*48000)%1024, 0)
                if i: self.assertAlmostEqual(parts[i-1][0]+parts[i-1][1],start)

    def test_budget_expires_while_copying_packets(self):
        info = probe(self.source)
        start, length = plan_parts(info.duration, segment_seconds=2, frame_seconds=info.copy_frame_seconds)[0]
        with patch.object(Budget, 'remaining', side_effect=[30.0]*15+[ASRError('TIMEOUT','test expired')]):
            with self.assertRaisesRegex(ASRError, 'test expired'):
                prepare_part(self.source,info,start,length,self.root,Budget(30))

    def test_non_aac_uses_decoded_path_even_with_m4a_extension(self):
        original = self.root / 'tone.wav'
        source = self.root / 'not-aac.m4a'
        source.write_bytes(original.read_bytes())
        info = probe(source)
        self.assertIsNone(info.copy_frame_seconds)
        self.assertEqual(prepare_part(source,info,1,1,self.root,Budget(30)).suffix,'.flac')


if __name__ == '__main__': unittest.main()
