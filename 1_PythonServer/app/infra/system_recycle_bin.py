"""Windows Shell recycling, without a private trash or permanent-delete fallback.

Uses IFileOperation and its progress sink via the standard-library ctypes so the
bundled backend needs no additional native runtime. COM stays on the calling
worker thread; project/catalog policy belongs to ProjectStorage/ProjectService.
"""
from __future__ import annotations

import ctypes as C
import os
from pathlib import Path
from uuid import UUID


HRESULT = C.c_int32
DWORD = C.c_uint32
PTR = C.c_void_p
CALLBACK = getattr(C, "WINFUNCTYPE", C.CFUNCTYPE)
E_ABORT = -2147467260
E_NOINTERFACE = -2147467262
TSF_DELETE_RECYCLE_IF_POSSIBLE = 0x80
# Silent Shell operation, stop on error, recycle rather than destroy, add Undo.
RECYCLE_FLAGS = 0x4 | 0x10 | 0x400 | 0x100000 | 0x80000 | 0x20000000


class GUID(C.Structure):
    _fields_ = [("data", C.c_ubyte * 16)]

    @classmethod
    def parse(cls, value: str) -> GUID:
        return cls.from_buffer_copy(UUID(value).bytes_le)


CLSID_FILE_OPERATION = GUID.parse("3ad05575-8857-4850-9277-11b85bdb8e09")
IID_FILE_OPERATION = GUID.parse("947aab5f-0a5c-4c13-b4d6-4bf7836fc9f8")
IID_SHELL_ITEM = GUID.parse("43826d1e-e718-42ee-bc55-a1e261c37bfe")
IID_PROGRESS_SINK = GUID.parse("04b0f1a7-9490-44bc-96e1-4296a31252e2")
IID_UNKNOWN = GUID.parse("00000000-0000-0000-c000-000000000046")


class _Interface(C.Structure):
    _fields_ = [("vtable", C.POINTER(PTR))]


class _RecycleProgress:
    """Refuse Shell's permanent-delete fallback and observe actual completion."""

    def __init__(self) -> None:
        self.error: str | None = None
        self.recycled = False
        self.references = 1
        # IFileOperationProgressSink's ABI, in declared vtable order.
        contracts = [
            (HRESULT, (C.POINTER(GUID), C.POINTER(PTR)), self._query),
            (DWORD, (), self._add_ref),
            (DWORD, (), self._release),
            (HRESULT, (), self._ok),                         # StartOperations
            (HRESULT, (HRESULT,), self._finish),
            (HRESULT, (DWORD, PTR, PTR), self._ok),          # PreRenameItem
            (HRESULT, (DWORD, PTR, PTR, HRESULT, PTR), self._ok),
            (HRESULT, (DWORD, PTR, PTR, PTR), self._ok),     # PreMoveItem
            (HRESULT, (DWORD, PTR, PTR, PTR, HRESULT, PTR), self._ok),
            (HRESULT, (DWORD, PTR, PTR, PTR), self._ok),     # PreCopyItem
            (HRESULT, (DWORD, PTR, PTR, PTR, HRESULT, PTR), self._ok),
            (HRESULT, (DWORD, PTR), self._pre_delete),
            (HRESULT, (DWORD, PTR, HRESULT, PTR), self._post_delete),
            (HRESULT, (DWORD, PTR, PTR), self._ok),          # PreNewItem
            (HRESULT, (DWORD, PTR, PTR, PTR, DWORD, HRESULT, PTR), self._ok),
            (HRESULT, (DWORD, DWORD), self._ok),             # UpdateProgress
            (HRESULT, (), self._ok),                        # ResetTimer
            (HRESULT, (), self._ok),                        # PauseTimer
            (HRESULT, (), self._ok),                        # ResumeTimer
        ]
        # Keep every callback alive until the Shell object has released the sink.
        self.callbacks = [CALLBACK(result, PTR, *args)(method) for result, args, method in contracts]
        self.vtable = (PTR * len(self.callbacks))(*(C.cast(fn, PTR) for fn in self.callbacks))
        self.interface = _Interface(self.vtable)

    @property
    def pointer(self) -> PTR:
        return C.cast(C.pointer(self.interface), PTR)

    def _query(self, _this, iid, result):
        if bytes(iid.contents) not in (bytes(IID_UNKNOWN), bytes(IID_PROGRESS_SINK)):
            result[0] = None
            return E_NOINTERFACE
        result[0] = self.pointer.value
        self.references += 1
        return 0

    def _add_ref(self, _this):
        self.references += 1
        return self.references

    def _release(self, _this):
        self.references -= 1
        return self.references

    def _ok(self, *_args):
        return 0

    def _pre_delete(self, _this, flags, _item):
        if not flags & TSF_DELETE_RECYCLE_IF_POSSIBLE:
            self.error = "系统无法将此目录放入回收站，已停止删除。"
            return E_ABORT
        return 0

    def _post_delete(self, _this, _flags, _item, result, recycled_item):
        if result < 0 and self.error is None:
            self.error = _error_text(result)
        elif result >= 0 and not recycled_item and self.error is None:
            self.error = "系统未确认文件已进入回收站。"
        elif result >= 0 and recycled_item:
            self.recycled = True
        return 0

    def _finish(self, _this, result):
        if result < 0 and self.error is None:
            self.error = _error_text(result)
        return 0


def _method(pointer: PTR, index: int, *argtypes):
    vtable = C.cast(pointer, C.POINTER(C.POINTER(PTR))).contents
    return CALLBACK(HRESULT, PTR, *argtypes)(vtable[index])


def _error_text(result: int) -> str:
    return f"系统回收失败（0x{result & 0xffffffff:08X}）。"


def _check(result: int) -> None:
    if result < 0:
        raise OSError(_error_text(result))


def recycle_path(path: Path) -> None:
    """Recycle an absolute path on the backend machine, or report failure."""
    if os.name != "nt":
        raise OSError("当前系统尚未接入系统回收站，未执行删除。")
    if not path.is_absolute() or path == path.parent:
        raise ValueError("回收目标必须是明确的文件或文件夹，不能是磁盘根目录。")

    ole32 = C.WinDLL("ole32")
    shell32 = C.WinDLL("shell32")
    ole32.CoInitializeEx.argtypes = [PTR, DWORD]
    ole32.CoInitializeEx.restype = HRESULT
    ole32.CoUninitialize.argtypes = []
    ole32.CoUninitialize.restype = None
    ole32.CoCreateInstance.argtypes = [C.POINTER(GUID), PTR, DWORD, C.POINTER(GUID), C.POINTER(PTR)]
    ole32.CoCreateInstance.restype = HRESULT
    shell32.SHCreateItemFromParsingName.argtypes = [C.c_wchar_p, PTR, C.POINTER(GUID), C.POINTER(PTR)]
    shell32.SHCreateItemFromParsingName.restype = HRESULT
    # STA is required by Shell. A failed initialization does not require Uninit.
    _check(ole32.CoInitializeEx(None, 2))
    operation, item = PTR(), PTR()
    progress = _RecycleProgress()
    try:
        _check(ole32.CoCreateInstance(C.byref(CLSID_FILE_OPERATION), None, 1,
            C.byref(IID_FILE_OPERATION), C.byref(operation)))
        _check(_method(operation, 5, DWORD)(operation, RECYCLE_FLAGS))
        _check(shell32.SHCreateItemFromParsingName(str(path), None, C.byref(IID_SHELL_ITEM), C.byref(item)))
        _check(_method(operation, 18, PTR, PTR)(operation, item, progress.pointer))
        result = _method(operation, 21)(operation)  # PerformOperations
        aborted = C.c_int32()
        _check(_method(operation, 22, C.POINTER(C.c_int32))(operation, C.byref(aborted)))
        if progress.error:
            raise OSError(progress.error)
        _check(result)
        if aborted.value or not progress.recycled:
            raise OSError("系统回收操作未完成，已停止删除。")
    finally:
        if item:
            _method(item, 2)(item)
        if operation:
            _method(operation, 2)(operation)
        ole32.CoUninitialize()
