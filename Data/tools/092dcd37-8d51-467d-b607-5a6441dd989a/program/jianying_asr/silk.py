"""Decode raw SILK v3 recordings before the ordinary audio pipeline."""
from __future__ import annotations

import os
import re
import struct
import subprocess
import tempfile
import wave
from contextlib import contextmanager
from pathlib import Path

from .common import ASRError, Budget

HEADER = b"#!SILK_V3"
SAMPLE_RATE = 24000  # Decoder SDK default; covers SILK's supported native rates.
MAX_PACKET_BYTES = 1024 * 5  # SDK MAX_BYTES_PER_FRAME * MAX_INPUT_FRAMES.
DECODER = Path(__file__).resolve().parents[1] / "vendor/silk/windows/silk_v3_decoder.exe"


def _stage_packets(source: Path, destination: Path, budget: Budget) -> int:
    """Check packet framing before handing untrusted data to the native SDK."""
    count = 0
    first = b""
    with source.open("rb") as reader, destination.open("wb") as writer:
        header = reader.read(1)
        if header == b"\x02":
            header = reader.read(len(HEADER))
        else:
            header += reader.read(len(HEADER) - 1)
        if header != HEADER:
            raise ASRError("INVALID_SILK", "SILK 文件头无效或文件在处理期间发生变化。")
        writer.write(HEADER)
        while True:
            budget.remaining()
            size_bytes = reader.read(2)
            if not size_bytes:
                break  # WeChat recordings normally omit the -1 terminator.
            if len(size_bytes) != 2:
                raise ASRError("INVALID_SILK", "SILK 音频包长度字段不完整。")
            size = struct.unpack("<h", size_bytes)[0]
            if size == -1:
                if reader.read(1):
                    raise ASRError("INVALID_SILK", "SILK 结束标记后仍有额外数据。")
                break
            if not 0 < size <= MAX_PACKET_BYTES:
                raise ASRError("INVALID_SILK", "SILK 音频包为空、缺失或长度无效，不能完整解码。")
            packet = reader.read(size)
            if len(packet) != size:
                raise ASRError("INVALID_SILK", "SILK 音频包被截断，不能完整解码。")
            writer.write(size_bytes)
            writer.write(packet)
            count += 1
            if count == 1:
                first = size_bytes + packet
        if not count:
            raise ASRError("INVALID_SILK", "SILK 文件没有音频包。")
        # This SDK's CLI always preloads two packets. For a one-packet clip,
        # duplicate only in the temporary input and discard the padded half.
        if count == 1:
            writer.write(first)
        writer.write(b"\xff\xff")
    return count


def _decode(directory: Path, packets: int, budget: Budget) -> Path:
    pcm = directory / "audio.pcm"
    log_path = directory / "decoder.log"
    with log_path.open("wb") as log:
        try:
            completed = subprocess.run(
                [str(DECODER), "input.silk", "audio.pcm", "-Fs_API", str(SAMPLE_RATE), "-quiet"],
                cwd=directory, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                timeout=budget.remaining(), creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except subprocess.TimeoutExpired as exc:
            raise ASRError("TIMEOUT", "SILK 解码已达到工具总执行时限。") from exc
        except OSError as exc:
            raise ASRError("SILK_DECODE_FAILED", "无法启动工具自带的 SILK 解码器。") from exc
    budget.remaining()
    # This CLI can return zero even on errors. A successful quiet run emits
    # exactly three numeric statistics; decoder errors must not be ignored.
    with log_path.open("rb") as log:
        report = log.read(4097)
    if (completed.returncode != 0 or len(report) > 4096
            or not re.fullmatch(rb"\s*\d+\.\d+\s+\d+\.\d+\s+\d+\s*", report)
            or not pcm.is_file()):
        raise ASRError("SILK_DECODE_FAILED", "SILK 解码失败，文件可能损坏或编码不受支持；未上传不完整音频。")
    size = pcm.stat().st_size
    # SILK packets contain 1–5 frames of 20 ms; check output against the
    # framed input instead of trusting the CLI's inaccurate duration label.
    frame_bytes = SAMPLE_RATE // 50 * 2
    decoded_packets = max(2, packets)
    if size % frame_bytes or not decoded_packets <= size // frame_bytes <= decoded_packets * 5:
        raise ASRError("SILK_DECODE_FAILED", "SILK 解码结果长度异常，未上传不完整音频。")
    if packets == 1:
        size //= 2
        if size % frame_bytes:
            raise ASRError("SILK_DECODE_FAILED", "单包 SILK 解码结果长度异常。")
    result = directory / "audio.wav"
    with pcm.open("rb") as reader, wave.open(str(result), "wb") as writer:
        writer.setparams((1, 2, SAMPLE_RATE, size // 2, "NONE", "not compressed"))
        remaining = size
        while remaining:
            budget.remaining()
            chunk = reader.read(min(1024 * 1024, remaining))
            if not chunk:
                raise ASRError("SILK_DECODE_FAILED", "SILK 解码结果不完整。")
            writer.writeframesraw(chunk)
            remaining -= len(chunk)
    return result


@contextmanager
def prepare_source(source: Path, budget: Budget):
    budget.remaining()
    with source.open("rb") as reader:
        header = reader.read(len(HEADER) + 1)
    if not (header.startswith(HEADER) or header.startswith(b"\x02" + HEADER)):
        yield source  # Real Speex and all ordinary media keep the existing path.
        return
    if os.name != "nt":
        raise ASRError("SILK_PLATFORM_UNSUPPORTED", "工具自带的 SILK 解码器仅支持 Windows。")
    if not DECODER.is_file():
        raise ASRError("DEPENDENCY_MISSING", "工具自带的 SILK 解码器缺失，请重新安装完整工具包。")
    with tempfile.TemporaryDirectory(prefix="audio-silk-") as directory:
        root = Path(directory)
        # The upstream CLI uses 150-byte ANSI filename buffers. Only short
        # ASCII relative paths reach it; Python handles the original path.
        packets = _stage_packets(source, root / "input.silk", budget)
        yield _decode(root, packets, budget)
