"""Incremental SSE framing shared by all model protocols.

Transport chunks are not events. Bound individual lines/events, never the total
response, and yield execution even when the transport already has bytes ready.
"""
import asyncio
from collections.abc import AsyncGenerator, Iterator
from dataclasses import dataclass
from json import loads as json_loads
import re

from app.core.config import get_settings
from app.core.errors import UpstreamProviderError

_NO_SSE_EVENT = object()
_DONE = re.compile(rb"\s*\[DONE\]\s*")
_SCAN_BYTES = 64 * 1024
_WORK_BYTES = 256 * 1024
_WORK_LINES = 256


@dataclass(frozen=True, slots=True)
class SseDone:
    pass


SSE_DONE = SseDone()


def _check_size(size: int, limit: int, unit: str) -> None:
    if size > limit:
        raise UpstreamProviderError(
            f"上游流式响应的{unit}超过解析保护上限 {limit} 字节"
            f"（已检测到 {size} 字节），本次请求已停止，未截断为成功结果。"
            "该限制不针对整篇回复；可通过后端配置 LLM_SSE_MAX_EVENT_BYTES 调整。",
            code="upstream_stream_event_too_large",
            details={"unit": unit, "limit_bytes": limit, "observed_bytes": size},
        )


class _SseLines:
    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.pending = bytearray()
        self.skip_lf = False

    def _append(self, part: bytes) -> None:
        _check_size(len(self.pending) + len(part), self.limit, "单行")
        self.pending.extend(part)

    def feed(self, block: bytes) -> Iterator[bytearray]:
        start = int(self.skip_lf and block.startswith(b"\n"))
        self.skip_lf = False
        # bytes.splitlines recognizes exactly CR/LF/CRLF; unlike str.splitlines
        # it does not split Unicode separators. Only scan this bounded block.
        for part in block[start:].splitlines(keepends=True):
            self.skip_lf = part.endswith(b"\r")
            ending = 2 if part.endswith(b"\r\n") else int(part.endswith((b"\r", b"\n")))
            if not ending:
                self._append(part)
                continue
            self._append(part[:-ending])
            line, self.pending = self.pending, bytearray()
            yield line


class _SseData:
    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.pending = bytearray()
        self.has_data = False
        self.first_line = True

    def consume(self, line: bytearray) -> bytearray | object:
        if self.first_line:
            self.first_line = False
            if line.startswith(b"\xef\xbb\xbf"):
                del line[:3]
        if not line:
            return self.flush()
        # Ignore comments/other fields without retaining their content.
        if line == b"data":
            start = len(line)
        elif line.startswith(b"data:"):
            start = 6 if line[5:6] == b" " else 5
        else:
            return _NO_SSE_EVENT
        size = len(self.pending) + int(self.has_data) + len(line) - start
        _check_size(size, self.limit, "单条事件")
        if self.has_data:
            self.pending.append(10)
        self.pending.extend(memoryview(line)[start:])
        self.has_data = True
        return _NO_SSE_EVENT

    def flush(self) -> bytearray | object:
        if not self.has_data:
            return _NO_SSE_EVENT
        data, self.pending = self.pending, bytearray()
        self.has_data = False
        return data


def _load_stream_payload(data: bytearray) -> dict[str, object] | None | SseDone:
    if _DONE.fullmatch(data):
        return SSE_DONE
    try:
        payload = json_loads(data)
    except (TypeError, ValueError, RecursionError):
        return None
    return payload if isinstance(payload, dict) else None


async def _iter_sse_payloads(
    chunks: AsyncGenerator[bytes, None],
) -> AsyncGenerator[dict[str, object] | None | SseDone, None]:
    try:
        limit = get_settings().llm_sse_max_event_bytes
        lines, data = _SseLines(limit), _SseData(limit)
        work_bytes = work_lines = work_chunks = 0
        async for chunk in chunks:
            work_chunks += 1
            # Bound work even for transports producing empty chunks.
            if work_chunks >= _WORK_LINES:
                await asyncio.sleep(0)
                work_bytes = work_lines = work_chunks = 0
            for offset in range(0, len(chunk), _SCAN_BYTES):
                block = chunk[offset:offset + _SCAN_BYTES]
                for line in lines.feed(block):
                    framed = data.consume(line)
                    work_lines += 1
                    if work_lines >= _WORK_LINES:
                        await asyncio.sleep(0)
                        work_bytes = work_lines = work_chunks = 0
                    if framed is not _NO_SSE_EVENT:
                        payload = _load_stream_payload(framed)
                        yield payload
                        if payload is SSE_DONE:
                            return
                work_bytes += len(block)
                if work_bytes >= _WORK_BYTES:
                    await asyncio.sleep(0)
                    work_bytes = work_lines = work_chunks = 0
        # Retain the existing provider compatibility for a final event without
        # a blank separator. Each protocol still checks its completion marker.
        if lines.pending:
            data.consume(lines.pending)
        framed = data.flush()
        if framed is not _NO_SSE_EVENT:
            yield _load_stream_payload(framed)
    finally:
        await chunks.aclose()
