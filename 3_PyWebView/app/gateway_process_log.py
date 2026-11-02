"""Bound gateway diagnostics while continuously draining the child process pipe."""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import BinaryIO


MAX_GATEWAY_LOG_BYTES = 8 * 1024 * 1024
GATEWAY_LOG_BACKUPS = 2
READ_CHUNK_BYTES = 64 * 1024
logger = logging.getLogger(__name__)


def configure_gateway_logging(environment: dict[str, str]) -> None:
    # ASP.NET configuration reads these keys without changing the gateway binary.
    # Explicit diagnostic overrides still use the same bounded file retention.
    for category in ("Microsoft.AspNetCore", "Yarp.ReverseProxy"):
        environment.setdefault(f"Logging__LogLevel__{category}", "Warning")


class RollingGatewayLog:
    def __init__(self, path: Path, *, max_bytes: int = MAX_GATEWAY_LOG_BYTES) -> None:
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        self.path = path
        self.max_bytes = max_bytes
        self._stream: BinaryIO | None = None
        path.parent.mkdir(parents=True, exist_ok=True)
        for index in range(GATEWAY_LOG_BACKUPS + 1):
            self._trim_existing(self._path(index))
        self._stream = path.open("ab", buffering=0)
        self._size = path.stat().st_size

    def _path(self, index: int) -> Path:
        return self.path if index == 0 else self.path.with_name(f"{self.path.name}.{index}")

    def _trim_existing(self, path: Path) -> None:
        if not path.exists() or path.stat().st_size <= self.max_bytes:
            return
        temporary = path.with_name(f"{path.name}.trim.tmp")
        try:
            with path.open("rb") as source, temporary.open("wb") as target:
                source.seek(-self.max_bytes, 2)
                while chunk := source.read(READ_CHUNK_BYTES):
                    target.write(chunk)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)

    def write(self, data: bytes) -> None:
        remaining = memoryview(data)
        while remaining:
            if self._size >= self.max_bytes:
                self._rotate()
            assert self._stream is not None
            amount = min(len(remaining), self.max_bytes - self._size)
            written = self._stream.write(remaining[:amount])
            if not written:
                raise OSError("Gateway log write made no progress")
            self._size += written
            remaining = remaining[written:]

    def _rotate(self) -> None:
        self.close()
        self._path(GATEWAY_LOG_BACKUPS).unlink(missing_ok=True)
        for index in range(GATEWAY_LOG_BACKUPS - 1, -1, -1):
            source = self._path(index)
            if source.exists():
                source.replace(self._path(index + 1))
        self._stream = self.path.open("wb", buffering=0)
        self._size = 0

    def close(self) -> None:
        if self._stream is not None:
            self._stream.close()
            self._stream = None


class GatewayProcessLog:
    def __init__(self, path: Path, *, max_bytes: int = MAX_GATEWAY_LOG_BYTES) -> None:
        self._writer = RollingGatewayLog(path, max_bytes=max_bytes)
        self._thread: threading.Thread | None = None

    def start(self, output: BinaryIO) -> None:
        self._thread = threading.Thread(
            target=self._drain, args=(output,), name="gateway-log", daemon=True,
        )
        self._thread.start()

    def _drain(self, output: BinaryIO) -> None:
        writable = True
        try:
            while chunk := output.read(READ_CHUNK_BYTES):
                if not writable:
                    continue
                try:
                    self._writer.write(chunk)
                except OSError:
                    # Disk failure must not fill stdout and stall proxy requests.
                    logger.exception("Gateway diagnostic log failed; draining output without saving.")
                    writable = False
        except OSError:
            logger.exception("Unable to read gateway diagnostic output.")
        finally:
            output.close()
            self._writer.close()

    def finish(self, timeout: float = 2.0) -> bool:
        if self._thread is None:
            self._writer.close()
            return True
        self._thread.join(timeout)
        return not self._thread.is_alive()
