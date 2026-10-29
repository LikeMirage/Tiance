from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
from tempfile import NamedTemporaryFile, TemporaryFile
from threading import Thread
from time import monotonic
from typing import BinaryIO


_MIN_CAPTURE_BYTES = 16 * 1024
_BYTES_PER_OUTPUT_CHAR = 4


@dataclass(frozen=True, slots=True)
class ProcessRunResult:
    returncode: int | None
    stdout: bytes
    stderr: bytes
    stdout_omitted_bytes: int
    stderr_omitted_bytes: int
    timed_out: bool
    elapsed_ms: int


def run_process(
    process_args: list[str] | str,
    *,
    stdin_bytes: bytes | None,
    cwd: Path,
    timeout_seconds: int,
    max_output_chars: int,
    extra_env: dict[str, str],
) -> ProcessRunResult:
    capture_limit = max(_MIN_CAPTURE_BYTES, max_output_chars * _BYTES_PER_OUTPUT_CHAR)
    started_at = monotonic()
    deadline = started_at + timeout_seconds
    environment = None
    if extra_env:
        environment = os.environ.copy()
        environment.update(extra_env)

    # This per-command deadline is independent from the host's tool.json budget.
    # File-backed I/O does not wait for descendants to close inherited handles.
    with ExitStack() as resources:
        output_file = NamedTemporaryFile if os.name == "nt" else TemporaryFile
        stdout_file = resources.enter_context(output_file(mode="w+b", buffering=0))
        stderr_file = resources.enter_context(output_file(mode="w+b", buffering=0))
        stdin_file = None
        if stdin_bytes is not None:
            stdin_file = resources.enter_context(TemporaryFile(mode="w+b"))
            stdin_file.write(stdin_bytes)
            stdin_file.seek(0)
        process = subprocess.Popen(
            process_args,
            stdin=stdin_file,
            stdout=stdout_file,
            stderr=stderr_file,
            cwd=str(cwd),
            env=environment,
        )
        timed_out = False
        try:
            returncode = process.wait(timeout=max(0.0, deadline - monotonic()))
        except subprocess.TimeoutExpired:
            timed_out = True
            process.kill()
            returncode = process.poll()
            if returncode is None:
                # Reap the direct process when the OS finishes terminating it.
                # This cleanup never blocks the result or adds another timeout.
                Thread(target=process.wait, daemon=True).start()
        stdout, stdout_omitted_bytes = _snapshot_output(stdout_file, capture_limit)
        stderr, stderr_omitted_bytes = _snapshot_output(stderr_file, capture_limit)
        return ProcessRunResult(
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
            stdout_omitted_bytes=stdout_omitted_bytes,
            stderr_omitted_bytes=stderr_omitted_bytes,
            timed_out=timed_out,
            elapsed_ms=max(0, round((monotonic() - started_at) * 1000)),
        )


def _snapshot_output(stream: BinaryIO, capture_limit: int) -> tuple[bytes, int]:
    size = os.fstat(stream.fileno()).st_size
    if os.name != "nt":
        # Anonymous files also disappear if the host terminates this tool.
        content = os.pread(stream.fileno(), min(size, capture_limit), 0)
        return content, max(0, size - len(content))
    # Use an independent read position so a descendant's inherited writer is
    # unaffected. Windows O_TEMPORARY shares delete access and removes the file
    # after the last handle closes, including a descendant's inherited handles.
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    flags |= os.O_TEMPORARY
    with os.fdopen(os.open(stream.name, flags), "rb") as reader:
        content = reader.read(min(size, capture_limit))
    return content, max(0, size - len(content))
