from __future__ import annotations

import ctypes
from ctypes import wintypes
from pathlib import Path
import threading

from watchfiles import Change


_FILE_LIST_DIRECTORY = 0x0001
_FILE_SHARE_READ = 0x00000001
_FILE_SHARE_WRITE = 0x00000002
_FILE_SHARE_DELETE = 0x00000004
_OPEN_EXISTING = 3
_FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
_NOTIFY_FILTER = (
    0x00000001  # FILE_NOTIFY_CHANGE_FILE_NAME
    | 0x00000002  # FILE_NOTIFY_CHANGE_DIR_NAME
    | 0x00000004  # FILE_NOTIFY_CHANGE_ATTRIBUTES
    | 0x00000008  # FILE_NOTIFY_CHANGE_SIZE
    | 0x00000010  # FILE_NOTIFY_CHANGE_LAST_WRITE
    | 0x00000040  # FILE_NOTIFY_CHANGE_CREATION
)
_BUFFER_SIZE = 64 * 1024
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

_ACTION_TO_CHANGE = {
    1: Change.added,
    2: Change.deleted,
    3: Change.modified,
    4: Change.deleted,
    5: Change.added,
}


class WindowsDirectoryChangeReader:
    """Read one Windows directory subtree without walking directory links."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._closed = False
        self._close_lock = threading.Lock()
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._configure_api()
        self._handle = self._kernel32.CreateFileW(
            str(root),
            _FILE_LIST_DIRECTORY,
            _FILE_SHARE_READ | _FILE_SHARE_WRITE | _FILE_SHARE_DELETE,
            None,
            _OPEN_EXISTING,
            _FILE_FLAG_BACKUP_SEMANTICS,
            None,
        )
        if self._handle == _INVALID_HANDLE_VALUE:
            raise ctypes.WinError(ctypes.get_last_error())

    def read(self) -> set[tuple[Change, str]]:
        buffer = ctypes.create_string_buffer(_BUFFER_SIZE)
        bytes_returned = wintypes.DWORD()
        success = self._kernel32.ReadDirectoryChangesW(
            self._handle,
            buffer,
            len(buffer),
            True,
            _NOTIFY_FILTER,
            ctypes.byref(bytes_returned),
            None,
            None,
        )
        if not success:
            error = ctypes.get_last_error()
            if self._closed:
                return set()
            raise ctypes.WinError(error)
        if bytes_returned.value == 0:
            return {
                (Change.modified, str(entry))
                for entry in self._root.iterdir()
            }
        return self._parse_changes(buffer.raw[: bytes_returned.value])

    def close(self) -> None:
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
            handle = self._handle
            self._kernel32.CancelIoEx(handle, None)
            self._kernel32.CloseHandle(handle)

    def _parse_changes(self, data: bytes) -> set[tuple[Change, str]]:
        changes: set[tuple[Change, str]] = set()
        offset = 0
        while offset + 12 <= len(data):
            next_offset = int.from_bytes(data[offset : offset + 4], "little")
            action = int.from_bytes(data[offset + 4 : offset + 8], "little")
            name_length = int.from_bytes(data[offset + 8 : offset + 12], "little")
            name_end = offset + 12 + name_length
            if name_end > len(data):
                break
            relative_name = data[offset + 12 : name_end].decode("utf-16-le", errors="replace")
            change = _ACTION_TO_CHANGE.get(action, Change.modified)
            changes.add((change, str(self._root / relative_name)))
            if next_offset == 0:
                break
            offset += next_offset
        return changes

    def _configure_api(self) -> None:
        self._kernel32.CreateFileW.argtypes = (
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        )
        self._kernel32.CreateFileW.restype = wintypes.HANDLE
        self._kernel32.ReadDirectoryChangesW.argtypes = (
            wintypes.HANDLE,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.BOOL,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            wintypes.LPVOID,
            wintypes.LPVOID,
        )
        self._kernel32.ReadDirectoryChangesW.restype = wintypes.BOOL
        self._kernel32.CancelIoEx.argtypes = (wintypes.HANDLE, wintypes.LPVOID)
        self._kernel32.CancelIoEx.restype = wintypes.BOOL
        self._kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        self._kernel32.CloseHandle.restype = wintypes.BOOL
