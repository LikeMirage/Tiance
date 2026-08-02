from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
from threading import Thread
from time import monotonic
from typing import BinaryIO


_READ_CHUNK_BYTES = 64 * 1024
_MIN_CAPTURE_BYTES = 16 * 1024
_BYTES_PER_OUTPUT_CHAR = 4


@dataclass(frozen=True, slots=True)
class ProcessRunResult:
    returncode: int
    stdout: bytes
    stderr: bytes
    stdout_omitted_bytes: int
    stderr_omitted_bytes: int
    timed_out: bool
    elapsed_ms: int


class _BoundedByteCollector:
    def __init__(self, limit_bytes: int) -> None:
        self._limit_bytes = limit_bytes
        self._chunks: list[bytes] = []
        self._retained_bytes = 0
        self._total_bytes = 0

    def append(self, chunk: bytes) -> None:
        if not chunk:
            return
        self._total_bytes += len(chunk)
        remaining = self._limit_bytes - self._retained_bytes
        if remaining <= 0:
            return
        retained = chunk[:remaining]
        self._chunks.append(retained)
        self._retained_bytes += len(retained)

    def build(self) -> tuple[bytes, int]:
        return b"".join(self._chunks), max(0, self._total_bytes - self._retained_bytes)


def run_process(
    process_args: list[str] | str,
    *,
    stdin_bytes: bytes | None,
    cwd: Path,
    timeout_seconds: int,
    max_output_chars: int,
) -> ProcessRunResult:
    capture_limit = max(
        _MIN_CAPTURE_BYTES,
        max_output_chars * _BYTES_PER_OUTPUT_CHAR,
    )
    stdout_collector = _BoundedByteCollector(capture_limit)
    stderr_collector = _BoundedByteCollector(capture_limit)
    started_at = monotonic()
    process = subprocess.Popen(
        process_args,
        stdin=subprocess.PIPE if stdin_bytes is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(cwd),
    )
    assert process.stdout is not None
    assert process.stderr is not None

    stdout_thread = Thread(
        target=_read_stream,
        args=(process.stdout, stdout_collector),
        daemon=True,
    )
    stderr_thread = Thread(
        target=_read_stream,
        args=(process.stderr, stderr_collector),
        daemon=True,
    )
    stdout_thread.start()
    stderr_thread.start()

    stdin_thread: Thread | None = None
    if process.stdin is not None:
        stdin_thread = Thread(
            target=_write_stdin,
            args=(process.stdin, stdin_bytes or b""),
            daemon=True,
        )
        stdin_thread.start()

    timed_out = False
    try:
        returncode = process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
        process.kill()
        returncode = process.wait()

    if stdin_thread is not None:
        stdin_thread.join()
    stdout_thread.join()
    stderr_thread.join()
    stdout, stdout_omitted_bytes = stdout_collector.build()
    stderr, stderr_omitted_bytes = stderr_collector.build()
    return ProcessRunResult(
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
        stdout_omitted_bytes=stdout_omitted_bytes,
        stderr_omitted_bytes=stderr_omitted_bytes,
        timed_out=timed_out,
        elapsed_ms=max(0, round((monotonic() - started_at) * 1000)),
    )


def _read_stream(stream: BinaryIO, collector: _BoundedByteCollector) -> None:
    try:
        while chunk := stream.read(_READ_CHUNK_BYTES):
            collector.append(chunk)
    finally:
        stream.close()


def _write_stdin(stream: BinaryIO, content: bytes) -> None:
    try:
        stream.write(content)
        stream.flush()
    except BrokenPipeError:
        pass
    finally:
        stream.close()
