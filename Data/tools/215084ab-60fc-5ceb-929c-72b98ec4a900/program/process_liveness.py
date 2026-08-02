from __future__ import annotations

import errno
import os
from pathlib import Path
from typing import BinaryIO, Literal


LIVENESS_FILENAME = "process.liveness"
LIVENESS_PROTOCOL = "exclusive_file_lock_v1"
LivenessStatus = Literal["held", "released", "unsupported", "unavailable"]
PidStatus = Literal["present", "absent", "unknown"]


def probe_liveness_lock(path: Path, protocol: str | None) -> LivenessStatus:
    if protocol != LIVENESS_PROTOCOL:
        return "unsupported"
    try:
        handle = path.open("r+b", buffering=0)
    except FileNotFoundError:
        return "unavailable"
    except PermissionError:
        return "held"
    except OSError:
        return "unavailable"

    try:
        handle.seek(0)
        try:
            _lock(handle)
        except (BlockingIOError, PermissionError):
            return "held"
        except OSError as exc:
            if exc.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                return "held"
            return "unavailable"
        try:
            return "released"
        finally:
            handle.seek(0)
            _unlock(handle)
    finally:
        handle.close()


def probe_pid(pid: object) -> PidStatus:
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        return "unknown"
    if os.name == "nt":
        return _probe_windows_pid(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return "absent"
    except PermissionError:
        return "present"
    except OSError:
        return "unknown"
    return "present"


if os.name == "nt":
    import ctypes
    from ctypes import wintypes

    _PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    _ERROR_ACCESS_DENIED = 5
    _ERROR_INVALID_PARAMETER = 87
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    _kernel32.CloseHandle.restype = wintypes.BOOL

    def _probe_windows_pid(pid: int) -> PidStatus:
        handle = _kernel32.OpenProcess(
            _PROCESS_QUERY_LIMITED_INFORMATION,
            False,
            pid,
        )
        if handle:
            _kernel32.CloseHandle(handle)
            return "present"
        error = ctypes.get_last_error()
        if error == _ERROR_INVALID_PARAMETER:
            return "absent"
        if error == _ERROR_ACCESS_DENIED:
            return "present"
        return "unknown"

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
