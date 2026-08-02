from __future__ import annotations

import os
from pathlib import Path
from typing import BinaryIO


LIVENESS_FILENAME = "process.liveness"
LIVENESS_PROTOCOL = "exclusive_file_lock_v1"


class ProcessLivenessLock:
    def __init__(self, handle: BinaryIO) -> None:
        self._handle: BinaryIO | None = handle

    @classmethod
    def acquire(cls, path: Path) -> "ProcessLivenessLock":
        handle = path.open("a+b", buffering=0)
        try:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
            handle.seek(0)
            _lock(handle)
        except Exception:
            handle.close()
            raise
        return cls(handle)

    def release(self) -> None:
        handle = self._handle
        if handle is None:
            return
        try:
            handle.seek(0)
            _unlock(handle)
        finally:
            handle.close()
            self._handle = None


if os.name == "nt":
    import msvcrt

    def _lock(handle: BinaryIO) -> None:
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)

    def _unlock(handle: BinaryIO) -> None:
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _lock(handle: BinaryIO) -> None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock(handle: BinaryIO) -> None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
