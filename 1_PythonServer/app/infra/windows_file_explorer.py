"""Windows Explorer activation for an explicit reveal action."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
from pathlib import Path


def reveal_in_windows_explorer(target: Path) -> None:
    # The desktop shell grants this backend foreground permission immediately
    # before the HTTP request. Pass it to the shell that owns Explorer windows.
    # Browser clients/older desktop shells still open the path if permission is
    # unavailable; never change the user's system-wide focus settings.
    _allow_explorer_foreground()
    if target.is_dir():
        os.startfile(str(target))
        return
    _select_file(target)


def _allow_explorer_foreground() -> bool:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetShellWindow.argtypes = []
    user32.GetShellWindow.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.AllowSetForegroundWindow.argtypes = [wintypes.DWORD]
    user32.AllowSetForegroundWindow.restype = wintypes.BOOL
    hwnd = user32.GetShellWindow()
    if not hwnd:
        return False
    process_id = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
    return bool(process_id.value and user32.AllowSetForegroundWindow(process_id.value))


def _select_file(target: Path) -> None:
    ole32 = ctypes.OleDLL("ole32")
    shell32 = ctypes.OleDLL("shell32")
    ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    ole32.CoInitializeEx.restype = ctypes.c_long
    ole32.CoUninitialize.argtypes = []
    ole32.CoUninitialize.restype = None
    ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    ole32.CoTaskMemFree.restype = None
    shell32.SHParseDisplayName.argtypes = [
        wintypes.LPCWSTR, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p),
        wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
    ]
    shell32.SHParseDisplayName.restype = ctypes.c_long
    shell32.SHOpenFolderAndSelectItems.argtypes = [
        ctypes.c_void_p, wintypes.UINT, ctypes.POINTER(ctypes.c_void_p), wintypes.DWORD,
    ]
    shell32.SHOpenFolderAndSelectItems.restype = ctypes.c_long

    # API routes run on worker threads; initialize COM for this operation only.
    initialized = False
    item_id = ctypes.c_void_p()
    try:
        try:
            ole32.CoInitializeEx(None, 2)  # COINIT_APARTMENTTHREADED
            initialized = True
        except OSError as exc:
            if getattr(exc, "winerror", None) != -2147417850:  # RPC_E_CHANGED_MODE
                raise
        shell32.SHParseDisplayName(str(target), None, ctypes.byref(item_id), 0, None)
        # With zero children, the absolute PIDL identifies the item to select.
        shell32.SHOpenFolderAndSelectItems(item_id, 0, None, 0)
    finally:
        if item_id.value:
            ole32.CoTaskMemFree(item_id)
        if initialized:
            ole32.CoUninitialize()
