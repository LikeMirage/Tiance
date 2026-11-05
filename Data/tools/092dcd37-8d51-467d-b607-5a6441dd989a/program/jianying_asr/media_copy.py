"""Copy supported AAC/MP4 packets, preserving compression and audio timing."""
from __future__ import annotations

from fractions import Fraction
from pathlib import Path

from .common import ASRError, Budget
from .media_runtime import get_av


def copy_frame_seconds(container, stream) -> Fraction | None:
    """Only opt in to the AAC-LC layout validated with the bundled decoder.

    Other formats/codecs retain the decoded FLAC path. Do not infer that all
    files with an .m4a extension have the same packet or priming semantics.
    """
    ctx = stream.codec_context
    extra = ctx.extradata or b""
    if ("mov" not in container.format.name.split(",") or ctx.name != "aac"
            or ctx.frame_size != 1024 or len(extra) < 2
            or stream.start_time != 0 or stream.duration is None):
        return None
    config = int.from_bytes(extra[:2], "big")
    object_type, frequency_index = config >> 11, (config >> 7) & 15
    channel_config = (config >> 3) & 15
    frequencies = (96000, 88200, 64000, 48000, 44100, 32000, 24000,
                   22050, 16000, 12000, 11025, 8000, 7350)
    # No 960-sample frames, core coder dependency, PCE or SBR/PS layouts.
    if (object_type != 2 or config & 7 or frequency_index >= len(frequencies)
            or frequencies[frequency_index] != ctx.sample_rate
            or channel_config not in (1, 2) or ctx.channels != channel_config
            or stream.time_base != Fraction(1, ctx.sample_rate)):
        return None
    return Fraction(1024, ctx.sample_rate)


def copy_aac_part(source: Path, output: Path, start: float, length: float, budget: Budget) -> None:
    av = get_av()
    with av.open(str(source)) as reader:
        stream = reader.streams.audio[0]
        frame_seconds = copy_frame_seconds(reader, stream)
        if frame_seconds is None:
            raise ASRError("INPUT_CHANGED", "音轨已不符合压缩数据直拷条件，请重新调用。")
        rate, origin = stream.codec_context.sample_rate, stream.start_time
        begin = origin + round(Fraction(str(start)) * rate)
        end = origin + round((Fraction(str(start)) + Fraction(str(length))) * rate)
        source_end = origin + stream.duration
        if ((begin - origin) % 1024 or (end != source_end and (end - origin) % 1024)
                or not origin <= begin < end <= source_end):
            raise ASRError("INVALID_SEGMENT", "压缩音频切点未对齐音频帧或超出音轨范围。")
        budget.remaining()
        if begin > origin:
            # Carry decoder preroll as negative-timestamp packets. The MP4 edit
            # list excludes it from presentation; it is not repeated speech.
            reader.seek(max(origin, begin - rate), stream=stream, backward=True)
        options = {"use_editlist": "1", "movie_timescale": str(rate),
                   "avoid_negative_ts": "disabled"}
        covered_end = None
        with av.open(str(output), "w", format="mp4", options=options) as writer:
            target = writer.add_stream_from_template(stream)
            target.time_base = stream.time_base
            for packet in reader.demux(stream):
                budget.remaining()
                if not packet.size:
                    continue  # Decoder-flush packet, not audio data.
                pts = packet.pts
                if (pts is None or packet.dts != pts or packet.is_corrupt or packet.duration <= 0):
                    raise ASRError("INVALID_AUDIO_TIMELINE", "音轨压缩包缺少有效、连续的时间戳。")
                if pts >= end:
                    break
                if (covered_end is not None and pts != covered_end) or (pts - origin) % 1024:
                    raise ASRError("INVALID_AUDIO_TIMELINE", "音轨压缩包时间轴不连续，未上传该片段。")
                if covered_end is None and pts > begin:
                    raise ASRError("INCOMPLETE_SEGMENT", "无法读取切片开头，未上传该片段。")
                # An MP4 edit list may end a few samples before the last
                # packet's declared duration (movie-timescale rounding).
                if packet.duration != 1024 and not pts < source_end <= pts + packet.duration:
                    raise ASRError("INVALID_AUDIO_TIMELINE", "音轨压缩帧长度发生变化，未上传该片段。")
                covered_end = min(pts + packet.duration, source_end)
                packet.duration = min(packet.duration, end - pts)
                packet.pts -= begin
                packet.dts -= begin
                packet.stream = target
                writer.mux(packet)
        if covered_end != end:
            raise ASRError("INCOMPLETE_SEGMENT", "压缩音频未覆盖完整切片，未上传该片段。")
        budget.remaining()
