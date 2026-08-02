from __future__ import annotations

import ctypes
import os
import time
from ctypes import wintypes
from pathlib import Path
from typing import Any, Literal, TypedDict


CF_HDROP = 15
CLIPBOARD_FILE_COUNT = 0xFFFFFFFF
GMEM_MOVEABLE = 0x0002
DROP_EFFECT_COPY = 0x00000001


class _DropFiles(ctypes.Structure):
    _fields_ = [
        ("pFiles", wintypes.DWORD),
        ("pt_x", wintypes.LONG),
        ("pt_y", wintypes.LONG),
        ("fNC", wintypes.BOOL),
        ("fWide", wintypes.BOOL),
    ]


class ClipboardPathEntry(TypedDict):
    kind: Literal["file", "folder"]
    name: str
    path: str


def read_clipboard_path_entries() -> list[ClipboardPathEntry]:
    if os.name != "nt":
        return []

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    _configure_windows_api(user32, shell32)

    if not _open_clipboard(user32):
        return []

    try:
        drop_handle = user32.GetClipboardData(CF_HDROP)
        if not drop_handle:
            return []

        count = shell32.DragQueryFileW(drop_handle, CLIPBOARD_FILE_COUNT, None, 0)
        entries: list[ClipboardPathEntry] = []
        for index in range(count):
            length = shell32.DragQueryFileW(drop_handle, index, None, 0)
            if length <= 0:
                continue
            buffer = ctypes.create_unicode_buffer(length + 1)
            if shell32.DragQueryFileW(drop_handle, index, buffer, len(buffer)) <= 0:
                continue
            path = Path(buffer.value).expanduser().resolve(strict=False)
            entries.append({
                "kind": "folder" if path.is_dir() else "file",
                "name": path.name or str(path),
                "path": str(path),
            })
        return entries
    finally:
        user32.CloseClipboard()


def write_clipboard_path_entries(paths: list[str]) -> bool:
    """Write existing files or folders as a standard Windows copy operation."""
    if os.name != "nt":
        return False

    normalized_paths = _normalize_existing_paths(paths)
    if not normalized_paths:
        return False

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _configure_clipboard_write_api(user32, kernel32)
    drop_handle = _allocate_global_bytes(kernel32, _build_drop_files_data(normalized_paths))
    if not drop_handle:
        return False

    effect_handle = _allocate_global_bytes(
        kernel32,
        int(DROP_EFFECT_COPY).to_bytes(4, byteorder="little", signed=False),
    )
    if not effect_handle:
        kernel32.GlobalFree(drop_handle)
        return False

    if not _open_clipboard(user32):
        kernel32.GlobalFree(drop_handle)
        kernel32.GlobalFree(effect_handle)
        return False

    owns_drop_handle = True
    owns_effect_handle = True
    try:
        if not user32.EmptyClipboard():
            return False
        if not user32.SetClipboardData(CF_HDROP, drop_handle):
            return False
        owns_drop_handle = False

        preferred_drop_effect = user32.RegisterClipboardFormatW("Preferred DropEffect")
        if preferred_drop_effect and user32.SetClipboardData(preferred_drop_effect, effect_handle):
            owns_effect_handle = False
        return True
    finally:
        user32.CloseClipboard()
        if owns_drop_handle:
            kernel32.GlobalFree(drop_handle)
        if owns_effect_handle:
            kernel32.GlobalFree(effect_handle)


def _configure_windows_api(user32: Any, shell32: Any) -> None:
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.CloseClipboard.argtypes = []
    user32.CloseClipboard.restype = wintypes.BOOL
    user32.GetClipboardData.argtypes = [wintypes.UINT]
    user32.GetClipboardData.restype = wintypes.HANDLE
    shell32.DragQueryFileW.argtypes = [
        wintypes.HANDLE,
        wintypes.UINT,
        wintypes.LPWSTR,
        wintypes.UINT,
    ]
    shell32.DragQueryFileW.restype = wintypes.UINT


def _configure_clipboard_write_api(user32: Any, kernel32: Any) -> None:
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.CloseClipboard.argtypes = []
    user32.CloseClipboard.restype = wintypes.BOOL
    user32.EmptyClipboard.argtypes = []
    user32.EmptyClipboard.restype = wintypes.BOOL
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user32.SetClipboardData.restype = wintypes.HANDLE
    user32.RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]
    user32.RegisterClipboardFormatW.restype = wintypes.UINT
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalFree.restype = wintypes.HGLOBAL
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalUnlock.restype = wintypes.BOOL


def _normalize_existing_paths(paths: list[str]) -> list[str]:
    if not isinstance(paths, list):
        return []

    normalized_paths: list[str] = []
    seen: set[str] = set()
    for value in paths:
        if not isinstance(value, str) or not value.strip():
            continue
        try:
            path = Path(value).expanduser().resolve(strict=True)
        except OSError:
            continue
        if not path.is_file() and not path.is_dir():
            continue
        resolved = str(path)
        key = os.path.normcase(resolved)
        if key in seen:
            continue
        seen.add(key)
        normalized_paths.append(resolved)
    return normalized_paths


def _build_drop_files_data(paths: list[str]) -> bytes:
    encoded_paths = ("\0".join(paths) + "\0\0").encode("utf-16-le")
    drop_files = _DropFiles(
        pFiles=ctypes.sizeof(_DropFiles),
        pt_x=0,
        pt_y=0,
        fNC=False,
        fWide=True,
    )
    return bytes(drop_files) + encoded_paths


def _allocate_global_bytes(kernel32: Any, data: bytes):
    handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
    if not handle:
        return None
    pointer = kernel32.GlobalLock(handle)
    if not pointer:
        kernel32.GlobalFree(handle)
        return None
    try:
        ctypes.memmove(pointer, data, len(data))
    finally:
        kernel32.GlobalUnlock(handle)
    return handle


def _open_clipboard(user32: Any) -> bool:
    for _ in range(6):
        if user32.OpenClipboard(None):
            return True
        time.sleep(0.02)
    return False
