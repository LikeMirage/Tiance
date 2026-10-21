from __future__ import annotations

from contextlib import contextmanager
import csv
import ctypes
from ctypes import wintypes
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

from tiance_runtime import run_tool

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "program/config.json"
BIN = ROOT / "dependencies/everything"
STATE = ROOT / ".Tiance/everything"
# 路径决定实例身份；复制到另一工具项目时不会连接或停止原实例。
INSTANCE = "Tiance_" + hashlib.sha256(str(ROOT).casefold().encode("utf-8")).hexdigest()[:24]


class ToolError(RuntimeError):
    def __init__(self, code, message, **details):
        super().__init__(message)
        self.code = code
        self.details = details


def config():
    values = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    page_contract = json.loads((ROOT / ".tool/input.schema.json").read_text(encoding="utf-8"))["properties"]["page_size"]
    values["default_page_size"] = page_contract["default"]
    values["max_page_size"] = page_contract["maximum"]
    for key in ("startup_timeout_seconds", "query_timeout_seconds", "lock_timeout_seconds", "poll_interval_seconds", "default_page_size", "max_page_size"):
        value = values[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ToolError("CONFIG_INVALID", f"配置 {key} 必须为正数。")
    return values


def es(args, cfg, *, timeout=None, search_text=None):
    executable = BIN / "es.exe"
    if not executable.is_file():
        raise ToolError("DEPENDENCY_MISSING", "工具缺少自带的es.exe，请恢复完整工具包。")
    # 隔离ES的用户默认配置，不能让用户原有的es.ini改变查询合同。
    env = {**os.environ, "APPDATA": str(STATE / "client-settings")}
    command = [str(executable), "-instance", INSTANCE, *args]
    if search_text is not None:
        # ES自行解析Windows命令行；list2cmdline会把含空格表达式变成字面短语。
        # -search*将余下原文全部视作查询，不再解析控制开关；shell始终关闭。
        command = subprocess.list2cmdline(command) + " -search* " + search_text
    try:
        return subprocess.run(
            command,
            capture_output=True, timeout=timeout or cfg["query_timeout_seconds"],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), env=env,
        )
    except subprocess.TimeoutExpired as exc:
        # subprocess.run超时时会结束并回收ES；Everything 1.4.1.838起会取消
        # 已退出IPC客户端的查询。不能另开一个ES发空查询：它不是同一个客户端。
        code = "SEARCH_TIMEOUT" if search_text is not None else "COMMAND_TIMEOUT"
        message = "Everything查询超时，请缩小目录、类型或大小范围后重试；未返回部分结果。" if search_text is not None else "Everything控制命令超时。"
        raise ToolError(code, message, timeout_seconds=exc.timeout) from exc


def checked(cp):
    if cp.returncode:
        # 不把失败的命令当成零结果，不依赖本地化错误文案作分支。
        raise ToolError("EVERYTHING_COMMAND_FAILED", "Everything命令执行失败。", exit_code=cp.returncode)
    return cp


def running(cfg):
    cp = es(["-get-everything-version"], cfg)
    if cp.returncode == 8:  # ES正式错误码：未找到该命名实例的IPC窗口。
        return False
    checked(cp)
    return True


def database_loaded(*, timeout_seconds=1.0):
    # 官方Everything_IPC.h：WM_USER / EVERYTHING_IPC_IS_DB_LOADED。
    # 直接读取命名实例状态，不发搜索、不启动进程；SendMessageTimeout防止挂起。
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    user32.FindWindowW.restype = wintypes.HWND
    user32.SendMessageTimeoutW.argtypes = [
        wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
        wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t),
    ]
    user32.SendMessageTimeoutW.restype = wintypes.LPARAM
    hwnd = user32.FindWindowW(f"EVERYTHING_TASKBAR_NOTIFICATION_({INSTANCE})", None)
    if not hwnd:
        raise ToolError("INSTANCE_UNAVAILABLE", "本工具Everything实例已退出，请重新搜索。")
    value = ctypes.c_size_t()
    ctypes.set_last_error(0)
    if not user32.SendMessageTimeoutW(
        hwnd, 0x0400, 401, 0, 0x0002 | 0x0020,
        max(1, math.ceil(timeout_seconds * 1000)), ctypes.byref(value),
    ):
        raise ToolError("IPC_UNRESPONSIVE", "Everything未响应索引状态查询。", windows_error=ctypes.get_last_error())
    return bool(value.value)


def wait_for_index(cfg):
    deadline = time.monotonic() + cfg["startup_timeout_seconds"]
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ToolError("INDEX_NOT_READY", "Everything索引尚未就绪，请稍后通过status检查；未执行搜索。")
        if database_loaded(timeout_seconds=min(1.0, remaining)):
            return
        time.sleep(min(cfg["poll_interval_seconds"], max(0, deadline - time.monotonic())))


def status(cfg):
    cp = es(["-get-everything-version"], cfg, timeout=min(2.0, cfg["query_timeout_seconds"]))
    active = cp.returncode != 8
    if active:
        checked(cp)
    ready = database_loaded() if active else False
    version = cp.stdout.decode("utf-8-sig").strip() if active else None
    return {
        "ok": True,
        "summary": "Everything正在运行，索引已就绪。" if ready else ("Everything正在运行，索引尚未就绪。" if active else "Everything尚未运行。"),
        "data": {
            "active": active, "index_ready": ready, "instance": INSTANCE,
            "everything_version": version, "state_directory": str(STATE),
            "search_scope": "everything_index", "content_search": "on_demand",
        },
        "warnings": ["索引就绪不代表全盘覆盖；结果只包含本实例已索引位置，内容搜索还取决于文件可读性及系统文本提取组件。"],
    }


@contextmanager
def instance_lock(cfg):
    import msvcrt
    STATE.mkdir(parents=True, exist_ok=True)
    with (STATE / "instance.lock").open("a+b") as handle:
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        deadline = time.monotonic() + cfg["lock_timeout_seconds"]
        while True:
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise ToolError("INSTANCE_BUSY", "另一个调用正在操作Everything，请稍后重试。")
                time.sleep(cfg["poll_interval_seconds"])
        try:
            yield
        finally:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def launch_elevated():
    executable = BIN / "Everything.exe"
    if not executable.is_file():
        raise ToolError("DEPENDENCY_MISSING", "工具缺少自带的Everything.exe，请恢复完整工具包。")
    ini = STATE / "Everything.ini"
    if not ini.exists():
        shutil.copyfile(ROOT / "program/everything.ini", ini)
    parameters = subprocess.list2cmdline([
        "-instance", INSTANCE, "-config", str(ini), "-db", str(STATE / "Everything.db"),
        "-startup", "-is-run-as",
    ])
    # 只提权这个固定EXE；用户查询绝不进入管理员启动命令。
    class ExecuteInfo(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD), ("fMask", wintypes.ULONG), ("hwnd", wintypes.HWND),
            ("lpVerb", wintypes.LPCWSTR), ("lpFile", wintypes.LPCWSTR),
            ("lpParameters", wintypes.LPCWSTR), ("lpDirectory", wintypes.LPCWSTR),
            ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE),
            ("lpIDList", ctypes.c_void_p), ("lpClass", wintypes.LPCWSTR),
            ("hkeyClass", wintypes.HKEY), ("dwHotKey", wintypes.DWORD),
            ("hIcon", wintypes.HANDLE), ("hProcess", wintypes.HANDLE),
        ]
    shell = ctypes.WinDLL("shell32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    shell.ShellExecuteExW.argtypes = [ctypes.POINTER(ExecuteInfo)]
    shell.ShellExecuteExW.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    info = ExecuteInfo()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = 0x40 | 0x400  # NOCLOSEPROCESS | FLAG_NO_UI（仍显示系统UAC）
    info.lpVerb = "runas"
    info.lpFile = str(executable)
    info.lpParameters = parameters
    info.lpDirectory = str(BIN)
    info.nShow = 0
    if not shell.ShellExecuteExW(ctypes.byref(info)):
        code = ctypes.get_last_error()
        if code == 1223:
            raise ToolError("ELEVATION_DECLINED", "Windows管理员授权被取消；未启动Everything。")
        raise ToolError("ELEVATION_FAILED", "无法以管理员权限启动Everything。", windows_error=code)
    if info.hProcess:
        kernel.CloseHandle(info.hProcess)


def ensure_running(cfg):
    if running(cfg):
        return False
    launch_elevated()
    deadline = time.monotonic() + cfg["startup_timeout_seconds"]
    while time.monotonic() < deadline:
        if running(cfg):
            return True
        time.sleep(cfg["poll_interval_seconds"])
    raise ToolError("STARTUP_TIMEOUT", "授权后Everything未及时就绪。后台可能仍在启动，请先检查status；不会回退到其他实例。")


def integer(value, name, minimum, maximum=None):
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum or (maximum is not None and value > maximum):
        raise ToolError("INVALID_ARGUMENT", f"{name}超出允许的整数范围。")
    return value


def search_arguments(payload, cfg):
    query = payload.get("query")
    if not isinstance(query, str) or not query.strip() or "\0" in query:
        raise ToolError("INVALID_ARGUMENT", "query必须是非空搜索表达式。")
    size = integer(payload.get("page_size", cfg["default_page_size"]), "page_size", 1, cfg["max_page_size"])
    offset = integer(payload.get("offset", 0), "offset", 0)
    # ES计数使用DWORD，明确拒绝溢出，不能回绕或静默截断。
    if offset + size + 1 > 0xFFFFFFFF:
        raise ToolError("INVALID_ARGUMENT", "offset与page_size合计超出Everything单次查询的32位计数范围。")
    base = payload.get("base_path")
    if base is not None:
        if not isinstance(base, str) or not base.strip() or not Path(base).is_absolute() or "\0" in base:
            raise ToolError("INVALID_ARGUMENT", "base_path必须是绝对目录路径。")
        base = str(Path(base).resolve())
        if not Path(base).is_dir():
            raise ToolError("DIRECTORY_NOT_FOUND", "base_path目录不存在或当前用户无法访问。")
    return query, size, offset, base


def search(payload, cfg):
    query, size, offset, base = search_arguments(payload, cfg)
    started = ensure_running(cfg)
    wait_for_index(cfg)
    # 多取一条判断下一页，不假装这一页等于全部匹配；临时CSV只做传输解码。
    with tempfile.TemporaryDirectory(prefix="query_", dir=STATE) as folder:
        output = Path(folder) / "results.csv"
        args = [
            # 索引等待已单独完成；若此时又开始重建，失败而非返回假空结果。
            "-ipc2", "-timeout", "1",
            "-n", str(offset + size + 1), "-viewport-offset", str(offset),
            "-viewport-count", str(size + 1), "-s",
            "-full-path-and-name", "-size", "-size-format", "1",
            "-no-digit-grouping", "-no-folder-append-path-separator",
            "-export-csv", str(output), "-utf8-bom",
        ]
        if base is not None:
            args.extend(["-path", base])
        checked(es(args, cfg, timeout=cfg["query_timeout_seconds"], search_text=query))
        if not output.is_file():
            raise ToolError("INVALID_RESPONSE", "Everything未生成查询结果。")
        with output.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if not reader.fieldnames or not {"Filename", "Size"}.issubset(reader.fieldnames):
                raise ToolError("INVALID_RESPONSE", "Everything返回的CSV列不符合文件路径和大小合同。")
            rows = list(reader)
        if len(rows) > size + 1:
            raise ToolError("INVALID_RESPONSE", "Everything未遵守分页参数，未静默截断结果。")
    more = len(rows) > size
    items = []
    for row in rows[:size]:
        # Size为空表示目录，使用索引元数据，不逐个访问受权限保护的文件。
        file_size = int(row["Size"]) if row["Size"] else None
        items.append({"path": row["Filename"], "type": "directory" if file_size is None else "file", "size_bytes": file_size})
    return {
        "ok": True, "summary": f"找到本页{len(items)}项" + ("，还有下一页。" if more else "，已到结果末尾。"),
        "data": {
            "query": query, "base_path": base, "offset": offset, "page_size": size,
            "count": len(items), "has_more": more, "next_offset": offset + len(items) if more else None,
            "pagination_consistency": "live_index", "sort": "full_path_ascending",
            "started": started, "items": items,
        },
        "warnings": ["分页基于实时索引；翻页期间文件变化可能造成位置移动。搜索结果仅覆盖Everything已索引位置。"],
    }


def run(payload):
    try:
        if os.name != "nt":
            raise ToolError("PLATFORM_UNSUPPORTED", "此工具仅支持Windows。")
        cfg = config()
        action = payload.get("action")
        if action not in {"search", "status", "stop"}:
            raise ToolError("INVALID_ARGUMENT", "action必须为search、status或stop。")
        if action == "status":
            return status(cfg)
        if action == "search":
            search_arguments(payload, cfg)  # 参数错误时不创建状态、不启动提权。
        elif not running(cfg):
            return {"ok": True, "summary": "本工具Everything实例未运行，无需停止。", "data": {"active": False}, "warnings": []}
        with instance_lock(cfg):
            if action == "search":
                return search(payload, cfg)
            if running(cfg):
                checked(es(["-exit"], cfg))
            return {"ok": True, "summary": "已停止本工具Everything实例，索引保留。", "data": {"active": False}, "warnings": []}
    except ToolError as exc:
        return {"ok": False, "error": str(exc), "error_info": {"code": exc.code, "message": str(exc), "details": exc.details}, "warnings": []}
    except (OSError, ValueError, KeyError, csv.Error) as exc:
        return {"ok": False, "error": str(exc), "error_info": {"code": "TOOL_DATA_ERROR", "message": str(exc)}, "warnings": []}


if __name__ == "__main__":
    run_tool(run)
