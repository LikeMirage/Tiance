"""Transfer foreground permission from a user-activated shell to its backend."""

import ctypes
from ctypes import wintypes
import os
import sys


def allow_backend_foreground(process_id: int | None) -> bool:
    if sys.platform != "win32" or not process_id or process_id <= 0:
        return False
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetForegroundWindow.argtypes = []
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.AllowSetForegroundWindow.argtypes = [wintypes.DWORD]
    user32.AllowSetForegroundWindow.restype = wintypes.BOOL
    foreground_pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), ctypes.byref(foreground_pid))
    if foreground_pid.value != os.getpid():
        return False
    return bool(user32.AllowSetForegroundWindow(process_id))
