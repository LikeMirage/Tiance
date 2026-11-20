"""Windows file associations and activation. Standard library only; no host imports."""
from __future__ import annotations

from contextlib import contextmanager
from collections import Counter
import ctypes as C
from ctypes import wintypes as W
import hashlib
import os
from pathlib import Path
import subprocess
from uuid import UUID


HRESULT = C.c_int32
PTR = C.c_void_p


class SHELLEXECUTEINFO(C.Structure):
    _fields_ = [("cbSize", W.DWORD), ("fMask", W.ULONG), ("hwnd", W.HWND),
                ("lpVerb", W.LPCWSTR), ("lpFile", W.LPCWSTR), ("lpParameters", W.LPCWSTR),
                ("lpDirectory", W.LPCWSTR), ("nShow", C.c_int), ("hInstApp", W.HINSTANCE),
                ("lpIDList", PTR), ("lpClass", W.LPCWSTR), ("hkeyClass", W.HKEY),
                ("dwHotKey", W.DWORD), ("hIcon", W.HANDLE), ("hProcess", W.HANDLE)]


class GUID(C.Structure):
    _fields_ = [("data", C.c_ubyte * 16)]

    def __init__(self, value):
        super().__init__()
        self.data[:] = UUID(value).bytes_le


IID_SHELL_ITEM = GUID("43826d1e-e718-42ee-bc55-a1e261c37bfe")
IID_DATA_OBJECT = GUID("0000010e-0000-0000-c000-000000000046")
BHID_DATA_OBJECT = GUID("b8c0bd9f-ed24-455c-83e6-d5390c4fe8c4")
IID_OBJECT_WITH_PROGID = GUID("71e806fb-8dee-46fc-bf8c-7748a8a1ae13")


class ShellError(Exception):
    def __init__(self, code, message, **details):
        super().__init__(message)
        self.code, self.details = code, details


def checked(hr, operation):
    if hr < 0:
        raise ShellError("WINDOWS_API_ERROR", operation, hresult=f"0x{hr & 0xffffffff:08X}")
    return hr


def com_call(pointer, index, types=(), args=()):
    table = C.cast(pointer, C.POINTER(C.POINTER(PTR))).contents
    method = C.WINFUNCTYPE(HRESULT, PTR, *types)(table[index])
    return method(pointer, *args)


def release(pointer):
    if pointer:
        com_call(pointer, 2)


def application_id(extension, name, progid):
    value = "\0".join((extension.lower(), name.casefold(), (progid or "").casefold()))
    return "windows:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def default_match(app, default):
    if not default["registered"]:
        return False
    if app["progid"] and default["progid"]:
        return app["progid"].casefold() == default["progid"].casefold()
    if default["app_user_model_id"] and app["handler_name"]:
        if app["handler_name"].casefold() == default["app_user_model_id"].casefold():
            return True
    if app["executable_path"] and default["executable_path"]:
        return os.path.normcase(app["executable_path"]) == os.path.normcase(default["executable_path"])
    return None  # Do not guess from a translated display name.


def clean_application_environment():
    return {key: value for key, value in os.environ.items()
            if not key.upper().startswith(("TIANCE_", "PYTHON", "VIRTUAL_ENV", "CONDA_"))}


@contextmanager
def application_environment():
    # This tool is a one-call subprocess. Shell activation can inherit its env.
    clean = clean_application_environment()
    removed = {key: value for key, value in os.environ.items() if key not in clean}
    for key in removed:
        del os.environ[key]
    try:
        yield
    finally:
        os.environ.update(removed)


class WindowsShell:
    def __enter__(self):
        self.ole = C.WinDLL("ole32")
        self.shell = C.WinDLL("shell32", use_last_error=True)
        self.assoc = C.WinDLL("shlwapi")
        self.ole.CoInitializeEx.argtypes = [PTR, W.DWORD]
        self.ole.CoInitializeEx.restype = HRESULT
        self.ole.CoUninitialize.argtypes = []
        self.ole.CoUninitialize.restype = None
        self.ole.CoTaskMemFree.argtypes = [PTR]
        self.ole.CoTaskMemFree.restype = None
        hr = self.ole.CoInitializeEx(None, 2)
        self.initialized = hr >= 0
        if (hr & 0xffffffff) != 0x80010106:  # RPC_E_CHANGED_MODE
            checked(hr, "无法初始化 Windows 文件关联接口。")
        self.shell.SHAssocEnumHandlers.argtypes = [W.LPCWSTR, W.DWORD, C.POINTER(PTR)]
        self.shell.SHAssocEnumHandlers.restype = HRESULT
        self.shell.SHCreateItemFromParsingName.argtypes = [W.LPCWSTR, PTR, C.POINTER(GUID), C.POINTER(PTR)]
        self.shell.SHCreateItemFromParsingName.restype = HRESULT
        self.assoc.AssocQueryStringW.argtypes = [W.DWORD, W.DWORD, W.LPCWSTR, W.LPCWSTR,
                                               W.LPWSTR, C.POINTER(W.DWORD)]
        self.assoc.AssocQueryStringW.restype = HRESULT
        return self

    def __exit__(self, *_):
        if self.initialized:
            self.ole.CoUninitialize()

    def _string(self, pointer, method, *, optional=False):
        value = PTR()
        try:
            hr = com_call(pointer, method, (C.POINTER(PTR),), (C.byref(value),))
            if hr < 0 and optional:
                return None
            checked(hr, "无法读取应用关联信息。")
            return C.wstring_at(value) if value else None
        finally:
            if value:
                self.ole.CoTaskMemFree(value)

    def _progid(self, handler):
        obj = PTR()
        hr = com_call(handler, 0, (C.POINTER(GUID), C.POINTER(PTR)),
                      (C.byref(IID_OBJECT_WITH_PROGID), C.byref(obj)))
        if hr < 0:
            return None
        try:
            return self._string(obj, 4, optional=True)
        finally:
            release(obj)

    def _association_string(self, extension, kind):
        if not extension:
            return None
        size = W.DWORD()
        hr = self.assoc.AssocQueryStringW(0, kind, extension, "open", None, C.byref(size))
        # No association / optional property missing. Other failures stay visible.
        missing = {0x80070483, 0x80070002, 0x80004005, 0x80070490}
        if (hr & 0xffffffff) in missing:
            return None
        if not size.value:
            checked(hr, "无法查询默认应用。")
            return None
        while True:
            value = C.create_unicode_buffer(size.value)
            capacity = size.value
            hr = self.assoc.AssocQueryStringW(0, kind, extension, "open", value, C.byref(size))
            if size.value > capacity:  # Association changed between queries.
                continue
            if (hr & 0xffffffff) in missing:
                return None
            checked(hr, "无法查询默认应用。")
            return value.value or None

    def default_app(self, extension):
        values = {"app_name": self._association_string(extension, 4),
                  "executable_path": self._association_string(extension, 2),
                  "progid": self._association_string(extension, 20),
                  "app_user_model_id": self._association_string(extension, 21)}
        return {"registered": any(values.values()), **values}

    @contextmanager
    def handlers(self, extension):
        items, warnings = [], []
        skipped = Counter()
        enumerator = PTR()
        try:
            if not extension:
                warnings.append("文件没有扩展名，无法按扩展名枚举应用；可通过 application_path 指定程序。")
            else:
                hr = self.shell.SHAssocEnumHandlers(extension, 0, C.byref(enumerator))
                if (hr & 0xffffffff) != 0x80070483:
                    checked(hr, "无法枚举此文件类型的打开方式。")
                while enumerator:
                    pointer, fetched = PTR(), W.ULONG()
                    hr = com_call(enumerator, 3, (W.ULONG, C.POINTER(PTR), C.POINTER(W.ULONG)),
                                  (1, C.byref(pointer), C.byref(fetched)))
                    if hr < 0:
                        release(pointer)
                        checked(hr, "枚举应用列表失败。")
                    if not fetched.value:
                        release(pointer)
                        break
                    try:
                        name = self._string(pointer, 3)
                        if not name:
                            raise ShellError("HANDLER_NAME_MISSING", "应用未返回可调用的标识。")
                        label = self._string(pointer, 4, optional=True) or name
                        progid = self._progid(pointer)
                        item = {"application_id": application_id(extension, name, progid),
                                "name": label, "handler_name": name, "progid": progid,
                                "executable_path": name if Path(name).is_absolute() else None,
                                "recommended": com_call(pointer, 6) == 0}
                        items.append((item, pointer))
                    except ShellError as exc:
                        release(pointer)
                        skipped[exc.details.get("hresult", exc.code)] += 1
            if skipped:
                warnings.append(f"跳过 {sum(skipped.values())} 个系统无法读取的关联项：{dict(skipped)}。")
            yield items, warnings
        finally:
            for _, pointer in items:
                release(pointer)
            release(enumerator)

    def list_apps(self, extension):
        default = self.default_app(extension)
        with self.handlers(extension) as (items, warnings):
            unique = {item["application_id"]: dict(item, is_default=default_match(item, default))
                      for item, _ in items}
        apps = sorted(unique.values(), key=lambda item: (item["is_default"] is not True,
                                                        not item["recommended"], item["name"].casefold()))
        return {"default_app": default, "applications": apps,
                "enumeration_complete": not warnings}, warnings

    def open_with_handler(self, path, identifier):
        with self.handlers(path.suffix.lower()) as (items, warnings):
            match = next(((item, pointer) for item, pointer in items
                          if item["application_id"] == identifier), None)
            if match is None:
                raise ShellError("APPLICATION_NOT_AVAILABLE", "该应用标识不再适用于此文件类型，请重新 list_apps。",
                                 warnings=warnings)
            item, handler = match
            shell_item, data = PTR(), PTR()
            try:
                checked(self.shell.SHCreateItemFromParsingName(str(path), None, C.byref(IID_SHELL_ITEM),
                                                               C.byref(shell_item)), "无法创建文件对象。")
                checked(com_call(shell_item, 3, (PTR, C.POINTER(GUID), C.POINTER(GUID), C.POINTER(PTR)),
                                 (None, C.byref(BHID_DATA_OBJECT), C.byref(IID_DATA_OBJECT), C.byref(data))),
                        "无法为指定应用创建文件选择对象。")
                with application_environment():
                    checked(com_call(handler, 8, (PTR,), (data,)), "指定应用未接受打开请求。")
                return item
            finally:
                release(data)
                release(shell_item)

    def open_default(self, path):
        self.shell.ShellExecuteExW.argtypes = [C.POINTER(SHELLEXECUTEINFO)]
        self.shell.ShellExecuteExW.restype = W.BOOL
        info = SHELLEXECUTEINFO()
        info.cbSize = C.sizeof(info)
        info.fMask = 0x400 | 0x100  # FLAG_NO_UI | NOASYNC: complete shell dispatch before COM teardown.
        info.lpVerb, info.lpFile, info.nShow = "open", str(path), 1
        with application_environment():
            if not self.shell.ShellExecuteExW(C.byref(info)):
                raise C.WinError(C.get_last_error())

    def open_with_executable(self, path, executable):
        process = subprocess.Popen([str(executable), str(path)], cwd=str(path.parent),
                                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   close_fds=True, env=clean_application_environment(),
                                   creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS)
        return {"name": executable.stem, "executable_path": str(executable), "process_id": process.pid}

    def reveal(self, path):
        if path.is_dir():
            self.open_default(path)
            return
        self.shell.SHParseDisplayName.argtypes = [W.LPCWSTR, PTR, C.POINTER(PTR), W.DWORD, C.POINTER(W.DWORD)]
        self.shell.SHParseDisplayName.restype = HRESULT
        self.shell.SHOpenFolderAndSelectItems.argtypes = [PTR, W.UINT, C.POINTER(PTR), W.DWORD]
        self.shell.SHOpenFolderAndSelectItems.restype = HRESULT
        pidl = PTR()
        try:
            checked(self.shell.SHParseDisplayName(str(path), None, C.byref(pidl), 0, None), "无法定位文件。")
            with application_environment():
                checked(self.shell.SHOpenFolderAndSelectItems(pidl, 0, None, 0), "无法在文件夹中选中文件。")
        finally:
            if pidl:
                self.ole.CoTaskMemFree(pidl)
