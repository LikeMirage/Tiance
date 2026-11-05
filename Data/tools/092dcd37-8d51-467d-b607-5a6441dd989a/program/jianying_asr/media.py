from __future__ import annotations

import math
from contextlib import ExitStack
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from .common import ASRError, Budget
from .media_copy import copy_aac_part, copy_frame_seconds
from .media_runtime import get_av

SEGMENT_SECONDS = 10 * 60
MAX_PARTS = 20
DIRECT_AUDIO = {".mp3", ".m4a", ".flac", ".wav"}


@dataclass(frozen=True)
class MediaInfo:
    duration: float
    audio_only: bool
    copy_frame_seconds: Fraction | None = None


def probe(path: Path) -> MediaInfo:
    av = get_av()
    try:
        with av.open(str(path)) as container:
            if not container.streams.audio:
                raise ASRError("NO_AUDIO", "输入文件中没有音轨。")
            stream = container.streams.audio[0]
            duration = (float(stream.duration * stream.time_base) if stream.duration is not None
                        else float(container.duration / av.time_base) if container.duration is not None else None)
            if duration is None or not math.isfinite(duration) or duration <= 0:
                raise ASRError("UNKNOWN_DURATION", "无法确定音频完整时长，未上传；请先转换为 M4A、WAV 或 FLAC。")
            return MediaInfo(duration, not container.streams.video and len(container.streams.audio) == 1,
                             copy_frame_seconds(container, stream))
    except av.error.FFmpegError as exc:
        raise ASRError("INVALID_MEDIA", f"无法读取音视频文件（{type(exc).__name__}）。") from exc


def plan_parts(duration: float, *, segment_seconds: float = SEGMENT_SECONDS,
               frame_seconds: Fraction | None = None):
    if not math.isfinite(duration) or duration <= 0 or not math.isfinite(segment_seconds) or segment_seconds <= 0:
        raise ASRError("INVALID_DURATION", "音频时长和分段时长必须是有限正数。")
    # Ten minutes is a target, not a service limit. Cap the total plan, not just
    # active workers: long recordings get longer equal parts, never a next wave.
    count = min(MAX_PARTS, max(1, math.ceil(duration / segment_seconds)))
    if frame_seconds is not None and count > 1:
        # Shared frame boundaries cover the entire track exactly once. Store
        # these actual offsets, not the ideal fractional points, for subtitles.
        quantum, total = Fraction(frame_seconds), Fraction(str(duration))
        if quantum <= 0 or quantum >= segment_seconds:
            raise ASRError("INVALID_DURATION", "分段时长必须大于一个压缩音频帧。")
        boundaries = [quantum * (total * n // (count * quantum)) for n in range(count)] + [total]
        parts = [(left, right - left) for left, right in zip(boundaries, boundaries[1:])]
        if any(length <= 0 for _, length in parts):
            raise ASRError("INVALID_DURATION", "无法按当前目标时长划分非空压缩音频片段。")
        return [(float(start), float(length)) for start, length in parts]
    boundaries = [duration * n / count for n in range(count)] + [duration]
    return [(left, right - left) for left, right in zip(boundaries, boundaries[1:])]


def _encode_part(source: Path, output: Path, start: float, length: float, budget: Budget) -> None:
    av = get_av()

    with ExitStack() as resources:
        budget.remaining()
        container = resources.enter_context(av.open(str(source)))
        stream = container.streams.audio[0]
        # Decode one second of preroll for codec overlap/bit reservoirs (AAC,
        # MP3, etc.), then trim decoded samples. Seeking to only the containing
        # packet can corrupt the first samples even when the duration matches.
        if start > 0 and stream.start_time is not None:
            try:
                seek_start = max(Fraction(0), Fraction(str(start)) - 1)
                container.seek(stream.start_time + int(seek_start / stream.time_base),
                               stream=stream, backward=True)
            except av.error.FFmpegError:
                # Some containers cannot seek; reopen and decode from the start.
                container.close()
                budget.remaining()
                container = resources.enter_context(av.open(str(source)))
                stream = container.streams.audio[0]

        frames = container.decode(stream)
        first = next(frames, None)
        if first is None:
            raise ASRError("CONVERSION_FAILED", "音轨没有可解码的音频帧。")
        origin = (stream.start_time * stream.time_base if stream.start_time is not None
                  else first.pts * first.time_base if first.pts is not None else Fraction(0))
        begin = origin + Fraction(str(start))
        end = begin + Fraction(str(length))
        sample_format = "s32" if first.format.bits > 16 else "s16"
        graph = av.filter.Graph()
        nodes = [graph.add_abuffer(sample_rate=first.sample_rate, format=first.format.name,
                                  layout=first.layout.name, time_base=first.time_base),
                 graph.add("atrim", start=f"{float(begin):.9f}", end=f"{float(end):.9f}"),
                 graph.add("asetpts", "PTS-STARTPTS"),
                 graph.add("aformat", sample_fmts=sample_format),
                 graph.add("abuffersink")]
        for left, right in zip(nodes, nodes[1:]):
            left.link_to(right)
        graph.configure()

        target = resources.enter_context(av.open(str(output), "w", format="flac"))
        audio = target.add_stream("flac", rate=first.sample_rate)
        audio.layout = first.layout
        audio.format = sample_format

        def drain() -> None:
            while True:
                budget.remaining()
                try:
                    frame = graph.pull()
                except (av.error.BlockingIOError, av.error.EOFError):
                    return
                for packet in audio.encode(frame):
                    target.mux(packet)

        frame = first
        while frame is not None:
            budget.remaining()
            graph.push(frame)
            drain()
            if (frame.pts is not None and frame.pts * frame.time_base
                    + Fraction(frame.samples, frame.sample_rate) >= end):
                break
            frame = next(frames, None)
        graph.push(None)
        drain()
        for packet in audio.encode(None):
            budget.remaining()
            target.mux(packet)


def prepare_part(source: Path, info: MediaInfo, start: float, length: float,
                 temporary: Path, budget: Budget) -> Path:
    budget.remaining()
    if (start == 0 and length == info.duration and info.duration <= SEGMENT_SECONDS
            and info.audio_only and source.suffix.lower() in DIRECT_AUDIO):
        return source
    av = get_av()
    if info.copy_frame_seconds is not None:
        output = temporary / "audio-copy.m4a"
        if output.resolve() == source.resolve():
            raise ASRError("INVALID_OUTPUT", "临时切片路径不能覆盖原文件。")
        try:
            copy_aac_part(source, output, start, length, budget)
        except av.error.FFmpegError as exc:
            raise ASRError("PACKET_COPY_FAILED", f"压缩音频切片失败（{type(exc).__name__}），未上传该片段。") from exc
        actual = probe(output)
        if abs(actual.duration - length) > float(info.copy_frame_seconds) / 1024 + 1e-9:
            raise ASRError("INCOMPLETE_SEGMENT", "压缩音频切片时长不符，未上传该片段。")
        return output
    output = temporary / "audio.flac"
    if output.resolve() == source.resolve():
        raise ASRError("INVALID_OUTPUT", "临时切片路径不能覆盖原文件。")
    try:
        _encode_part(source, output, start, length, budget)
    except (av.error.FFmpegError, ValueError) as exc:
        raise ASRError("CONVERSION_FAILED", f"PyAV 提取或切分音轨失败：{exc}") from exc
    budget.remaining()
    actual = probe(output).duration
    # Metadata rounding and a final codec frame can differ slightly, never accept a missing tail.
    if abs(actual - length) > 0.1:
        raise ASRError("INCOMPLETE_SEGMENT", f"切分音频时长不符：预期 {length:.3f} 秒，实际 {actual:.3f} 秒。")
    return output
