from __future__ import annotations

import os
from pathlib import Path
from typing import Callable


def acquire_installation_lock(root: Path) -> Callable[[], None]:
    """Keep the running installation directory undeletable on Windows."""
    if os.name != "nt":
        return lambda: None

    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create_file.restype = wintypes.HANDLE
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL

    invalid_handle = wintypes.HANDLE(-1).value
    lock_path = root / ".tiance-running.lock"
    handle = create_file(
        str(lock_path),
        0x80000000,  # GENERIC_READ
        0x00000001 | 0x00000002,  # FILE_SHARE_READ | FILE_SHARE_WRITE
        None,
        4,  # OPEN_ALWAYS
        0x00000002,  # FILE_ATTRIBUTE_HIDDEN
        None,
    )
    if handle == invalid_handle:
        error = ctypes.get_last_error()
        raise OSError(error, f"无法锁定安装目录：{root}")

    released = False

    def release() -> None:
        nonlocal released
        if released:
            return
        released = True
        close_handle(handle)
        try:
            lock_path.unlink()
        except OSError:
            pass

    return release
