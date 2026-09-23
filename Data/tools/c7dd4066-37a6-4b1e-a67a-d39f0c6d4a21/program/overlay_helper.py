from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import hashlib
import math
import os
from pathlib import Path
import re
import shutil
import socket
import select
import subprocess
import urllib.request
import sys
import threading
import time
from typing import Any
from uuid import uuid4

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageGrab


user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
kernel32 = ctypes.windll.kernel32
dwmapi = getattr(ctypes.windll, "dwmapi", None)

LRESULT = ctypes.c_ssize_t
WPARAM = ctypes.c_size_t
LPARAM = ctypes.c_ssize_t
ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, WPARAM, LPARAM)
HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, WPARAM, LPARAM)


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
        ("hIconSm", wintypes.HICON),
    ]


class PAINTSTRUCT(ctypes.Structure):
    _fields_ = [
        ("hdc", wintypes.HDC),
        ("fErase", wintypes.BOOL),
        ("rcPaint", wintypes.RECT),
        ("fRestore", wintypes.BOOL),
        ("fIncUpdate", wintypes.BOOL),
        ("rgbReserved", ctypes.c_byte * 32),
    ]


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD), ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG), ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 1)]


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [("BlendOp", wintypes.BYTE), ("BlendFlags", wintypes.BYTE),
                ("SourceConstantAlpha", wintypes.BYTE), ("AlphaFormat", wintypes.BYTE)]


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", POINT),
        ("mouseData", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]


class INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", INPUTUNION)]


class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    ]


user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, WPARAM, LPARAM]
user32.DefWindowProcW.restype = LRESULT
user32.CreateWindowExW.argtypes = [
    wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, ctypes.c_void_p,
]
user32.CreateWindowExW.restype = wintypes.HWND
user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
user32.SetWindowsHookExW.restype = wintypes.HHOOK
user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, WPARAM, LPARAM]
user32.CallNextHookEx.restype = LRESULT
user32.GetForegroundWindow.restype = wintypes.HWND
user32.WindowFromPoint.argtypes = [POINT]
user32.WindowFromPoint.restype = wintypes.HWND
user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetAncestor.restype = wintypes.HWND
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.BringWindowToTop.argtypes = [wintypes.HWND]
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.IsWindow.argtypes = [wintypes.HWND]
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsIconic.argtypes = [wintypes.HWND]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.DestroyWindow.argtypes = [wintypes.HWND]
user32.UpdateLayeredWindow.argtypes = [wintypes.HWND, wintypes.HDC, ctypes.POINTER(POINT),
    ctypes.POINTER(wintypes.SIZE), wintypes.HDC, ctypes.POINTER(POINT), wintypes.COLORREF,
    ctypes.POINTER(BLENDFUNCTION), wintypes.DWORD]
user32.UpdateLayeredWindow.restype = wintypes.BOOL
user32.SetLayeredWindowAttributes.argtypes = [wintypes.HWND, wintypes.COLORREF, wintypes.BYTE, wintypes.DWORD]
user32.SetLayeredWindowAttributes.restype = wintypes.BOOL
user32.GetDpiForWindow.argtypes = [wintypes.HWND]
user32.GetDpiForWindow.restype = wintypes.UINT
gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.DeleteDC.argtypes = [wintypes.HDC]
gdi32.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.POINTER(BITMAPINFO), wintypes.UINT,
                                  ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD]
gdi32.CreateDIBSection.restype = wintypes.HBITMAP
user32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
user32.SetWindowDisplayAffinity.restype = wintypes.BOOL
user32.GetWindowDisplayAffinity.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowDisplayAffinity.restype = wintypes.BOOL
user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, WPARAM, LPARAM]
user32.LoadCursorW.argtypes = [wintypes.HINSTANCE, ctypes.c_void_p]
user32.LoadCursorW.restype = wintypes.HANDLE
user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = wintypes.UINT
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE
kernel32.GetCurrentThreadId.restype = wintypes.DWORD

# HWND/HDC/HGDIOBJ是指针宽度，ctypes默认的int会在64位Windows截断句柄。
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
user32.SetWindowPos.restype = wintypes.BOOL
user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MONITORINFO)]
user32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
user32.BeginPaint.argtypes = [wintypes.HWND, ctypes.POINTER(PAINTSTRUCT)]
user32.BeginPaint.restype = wintypes.HDC
user32.EndPaint.argtypes = [wintypes.HWND, ctypes.POINTER(PAINTSTRUCT)]
user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.FillRect.argtypes = [wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.HBRUSH]
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
gdi32.CreateSolidBrush.argtypes = [wintypes.COLORREF]
gdi32.CreateSolidBrush.restype = wintypes.HBRUSH
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HANDLE]
gdi32.SelectObject.restype = wintypes.HANDLE
gdi32.DeleteObject.argtypes = [wintypes.HANDLE]
gdi32.GetStockObject.argtypes = [ctypes.c_int]
gdi32.GetStockObject.restype = wintypes.HANDLE


WM_PAINT = 0x000F
WM_DESTROY = 0x0002
WM_NCHITTEST = 0x0084
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYUP = 0x0105
WM_QUIT = 0x0012
WM_APP_STOP = 0x8001
HTTRANSPARENT = -1
WH_KEYBOARD_LL = 13
WH_MOUSE_LL = 14
WS_POPUP = 0x80000000
WS_CHILD = 0x40000000
WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_NOACTIVATE = 0x08000000
GWL_EXSTYLE = -20
GWL_STYLE = -16
LWA_COLORKEY = 0x00000001
ULW_ALPHA = 0x00000002
AC_SRC_ALPHA = 0x01
SW_SHOWNOACTIVATE = 4
HWND_TOPMOST = -1
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020
WDA_EXCLUDEFROMCAPTURE = 0x00000011
INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_HWHEEL = 0x1000
MOUSEEVENTF_VIRTUALDESK = 0x4000
MOUSEEVENTF_ABSOLUTE = 0x8000
WHEEL_DELTA = 120
SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79
PIXEL_CHANNEL_DELTA_THRESHOLD = 16
DEFAULT_SCREENSHOT_DELAY_SECONDS = 1.0
DEFAULT_CLICK_HOLD_MS = 80
COORDINATE_PREVIEW_COLOR = (255, 45, 138)
COORDINATE_PREVIEW_COLOR_HEX = "#FF2D8A"
DEFAULT_ZOOM_SCALE_PERCENT = 400
POINTER_VERIFY_TIMEOUT_MS = 250
MOUSE_ACTION_DEFAULTS = {
    "screenshot_delay_seconds": DEFAULT_SCREENSHOT_DELAY_SECONDS,
    "button": "left", "clicks": 1, "click_hold_ms": DEFAULT_CLICK_HOLD_MS,
    "modifiers": [], "duration_ms": 0, "direction": "down", "notches": 3,
    "interval_ms": 120, "change_check_scope": "target_cell", "change_threshold_percent": 0.5,
}
MOUSE_ACTIONS = {"move", "click", "drag", "scroll", "mouse_down", "mouse_up"}
MOUSE_ACTION_OPTIONS = {
    "move": ("duration_ms",),
    "click": ("button", "clicks", "click_hold_ms", "modifiers", "interval_ms"),
    "drag": ("button", "duration_ms", "modifiers"),
    "scroll": ("direction", "notches", "interval_ms", "modifiers"),
    "mouse_down": ("button",), "mouse_up": ("button",),
}
PREVIEW_ID_PATTERN = re.compile(r"^preview_([a-f0-9]{32})_([a-f0-9]{32})$")

MOUSE_BUTTON_FLAGS = {
    "left": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
    "right": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
    "middle": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
}

KEY_ALIASES = {
    "return": "enter", "escape": "esc", "control": "ctrl", "windows": "win",
    "super": "win", "cmd": "win", "pgup": "pageup", "pgdn": "pagedown",
    "del": "delete", "ins": "insert", "bksp": "backspace",
}
VK_CODES = {
    "backspace": 0x08, "tab": 0x09, "enter": 0x0D, "shift": 0x10,
    "ctrl": 0x11, "alt": 0x12, "pause": 0x13, "capslock": 0x14,
    "esc": 0x1B, "space": 0x20, "pageup": 0x21, "pagedown": 0x22,
    "end": 0x23, "home": 0x24, "left": 0x25, "up": 0x26,
    "right": 0x27, "down": 0x28, "printscreen": 0x2C, "insert": 0x2D,
    "delete": 0x2E, "win": 0x5B, "apps": 0x5D, "numlock": 0x90,
    "scrolllock": 0x91,
}
EXTENDED_KEYS = {
    "pageup", "pagedown", "end", "home", "left", "up", "right", "down",
    "printscreen", "insert", "delete", "win", "apps",
}

SERVICE: "GuiService | None" = None


class GuiError(RuntimeError):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


@contextmanager
def physical_coordinates():
    """截图、窗口矩形及输入线程共同使用每显示器物理像素。"""
    setter = getattr(user32, "SetThreadDpiAwarenessContext", None)
    if setter is None:
        raise GuiError("DPI_CONTEXT_UNAVAILABLE", "GUI工具需要支持每显示器DPI感知的Windows 10或更新版本。")
    setter.argtypes = [ctypes.c_void_p]
    setter.restype = ctypes.c_void_p
    previous = setter(ctypes.c_void_p(-4))  # PER_MONITOR_AWARE_V2
    if not previous:
        raise GuiError("DPI_CONTEXT_UNAVAILABLE", "无法启用物理像素坐标，未执行GUI操作。")
    try:
        yield
    finally:
        setter(previous)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)
    except BaseException:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass  # Preserve the original access error; never remove the destination.
        raise


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise GuiError("GUI_STATE_INVALID", f"无法读取GUI状态：{path}") from exc
    if not isinstance(payload, dict):
        raise GuiError("GUI_STATE_INVALID", "GUI状态不是对象。")
    return payload


def colorref(red: int, green: int, blue: int) -> int:
    return red | (green << 8) | (blue << 16)


def image_difference_percent(before: Image.Image, after: Image.Image) -> float:
    before_rgb = before.convert("RGB")
    after_rgb = after.convert("RGB")
    if before_rgb.size != after_rgb.size:
        return 100.0
    red, green, blue = ImageChops.difference(before_rgb, after_rgb).split()
    maximum_channel_delta = ImageChops.lighter(ImageChops.lighter(red, green), blue)
    histogram = maximum_channel_delta.histogram()
    changed = sum(histogram[PIXEL_CHANNEL_DELTA_THRESHOLD:])
    total = max(1, maximum_channel_delta.width * maximum_channel_delta.height)
    return round(changed * 100.0 / total, 4)


def virtual_rect() -> dict[str, int]:
    left = int(user32.GetSystemMetrics(SM_XVIRTUALSCREEN))
    top = int(user32.GetSystemMetrics(SM_YVIRTUALSCREEN))
    width = int(user32.GetSystemMetrics(SM_CXVIRTUALSCREEN))
    height = int(user32.GetSystemMetrics(SM_CYVIRTUALSCREEN))
    return {"left": left, "top": top, "width": width, "height": height}


def monitor_rects() -> list[dict[str, int]]:
    rows: list[dict[str, int]] = []
    callback_type = ctypes.WINFUNCTYPE(
        wintypes.BOOL,
        wintypes.HMONITOR,
        wintypes.HDC,
        ctypes.POINTER(wintypes.RECT),
        wintypes.LPARAM,
    )

    @callback_type
    def collect(monitor: int, _dc: int, _rect: Any, _data: int) -> bool:
        info = MONITORINFO(cbSize=ctypes.sizeof(MONITORINFO))
        if user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            rect = info.rcMonitor
            rows.append({
                "left": int(rect.left), "top": int(rect.top),
                "width": int(rect.right - rect.left), "height": int(rect.bottom - rect.top),
                "primary": bool(info.dwFlags & 1),
            })
        return True

    user32.EnumDisplayMonitors(0, None, collect, 0)
    rows.sort(key=lambda item: (not item["primary"], item["left"], item["top"]))
    return rows


def rect_ltrb(rect: dict[str, int]) -> tuple[int, int, int, int]:
    return (
        int(rect["left"]), int(rect["top"]),
        int(rect["left"] + rect["width"]), int(rect["top"] + rect["height"]),
    )


def window_rect(hwnd: int) -> dict[str, int]:
    native = wintypes.RECT()
    if not user32.IsWindow(hwnd) or not user32.IsWindowVisible(hwnd):
        raise GuiError("WINDOW_NOT_AVAILABLE", "目标窗口已不存在或不可见。")
    if user32.IsIconic(hwnd):
        raise GuiError("WINDOW_MINIMIZED", "目标窗口已最小化。")
    if not user32.GetWindowRect(hwnd, ctypes.byref(native)):
        raise GuiError("WINDOW_NOT_AVAILABLE", "无法读取目标窗口位置。")
    return {
        "left": int(native.left), "top": int(native.top),
        "width": int(native.right - native.left), "height": int(native.bottom - native.top),
    }


def visible_windows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @callback_type
    def collect(hwnd: int, _data: int) -> bool:
        if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
            return True
        length = int(user32.GetWindowTextLengthW(hwnd))
        if length <= 0:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        title = buffer.value.strip()
        if not title:
            return True
        try:
            rect = window_rect(int(hwnd))
        except GuiError:
            return True
        if rect["width"] < 2 or rect["height"] < 2:
            return True
        rows.append({"hwnd": int(hwnd), "title": title, "rect": rect})
        return True

    user32.EnumWindows(collect, 0)
    return rows


def drag_window_snapshot(excluded: list[int]) -> list[dict[str, Any]]:
    """Capture top-level windows in Z order, including untitled popup occluders.

    Rectangles conservatively identify the window visible at a captured point;
    native hit testing must corroborate it before any drag is allowed.
    """
    rows: list[dict[str, Any]] = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @callback_type
    def collect(hwnd: int, _data: int) -> bool:
        if int(hwnd) in excluded or not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
            return True
        if dwmapi is not None:
            cloaked = wintypes.DWORD()
            if dwmapi.DwmGetWindowAttribute(wintypes.HWND(hwnd), 14, ctypes.byref(cloaked), ctypes.sizeof(cloaked)) == 0 and cloaked.value:
                return True
        try:
            rect = window_rect(int(hwnd))
        except GuiError:
            return True  # A window destroyed during enumeration cannot own this snapshot.
        pid = wintypes.DWORD()
        thread_id = int(user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid)))
        rows.append({"hwnd": int(hwnd), "pid": int(pid.value), "thread_id": thread_id, "rect": rect})
        return True

    if not user32.EnumWindows(collect, 0):
        raise GuiError("WINDOW_SNAPSHOT_FAILED", "无法记录截图对应的窗口，请重新查看界面。")
    return rows


def window_at_point(windows: list[dict[str, Any]], x: int, y: int) -> dict[str, Any] | None:
    for window in windows:
        left, top, right, bottom = rect_ltrb(window["rect"])
        if left <= x < right and top <= y < bottom:
            return window
    return None


def resolve_window(hwnd: int | None, title: str | None) -> dict[str, Any]:
    rows = visible_windows()
    if hwnd:
        match = next((item for item in rows if item["hwnd"] == int(hwnd)), None)
        if match is None:
            raise GuiError("WINDOW_NOT_AVAILABLE", f"没有找到窗口句柄 {hwnd}。")
        return match
    requested = str(title or "").strip()
    if requested:
        exact = next((item for item in rows if item["title"].casefold() == requested.casefold()), None)
        if exact is not None:
            return exact
        partial = next((item for item in rows if requested.casefold() in item["title"].casefold()), None)
        if partial is not None:
            return partial
        raise GuiError("WINDOW_NOT_AVAILABLE", f"没有找到标题包含“{requested}”的窗口。")
    foreground = int(user32.GetForegroundWindow() or 0)
    match = next((item for item in rows if item["hwnd"] == foreground), None)
    if match is None:
        raise GuiError("WINDOW_NOT_AVAILABLE", "当前没有可用的前台窗口。")
    return match


def activate_window(hwnd: int) -> bool:
    if not user32.IsWindow(hwnd):
        return False
    foreground = int(user32.GetForegroundWindow() or 0)
    foreground_thread = int(user32.GetWindowThreadProcessId(foreground, None) or 0)
    current_thread = int(kernel32.GetCurrentThreadId())
    attached = False
    if foreground_thread and foreground_thread != current_thread:
        attached = bool(user32.AttachThreadInput(current_thread, foreground_thread, True))
    try:
        user32.ShowWindow(hwnd, 9)
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
    finally:
        if attached:
            user32.AttachThreadInput(current_thread, foreground_thread, False)
    time.sleep(0.06)
    return int(user32.GetForegroundWindow() or 0) == int(hwnd)


def choose_grid(width: int, height: int, mode: str, target: int, rows: int | None, cols: int | None) -> tuple[int, int]:
    if mode == "fixed":
        if not rows or not cols:
            raise GuiError("INVALID_ARGUMENT", "fixed网格必须同时提供grid_rows和grid_cols。")
        return max(1, min(int(rows), 16)), max(1, min(int(cols), 16))
    target = max(4, min(int(target or 16), 64))
    aspect = max(0.1, width / max(1, height))
    cols_value = max(1, round(math.sqrt(target * aspect)))
    rows_value = max(1, math.ceil(target / cols_value))
    return min(rows_value, 16), min(cols_value, 16)


def build_cells(rect: dict[str, int], rows: int, cols: int) -> list[dict[str, Any]]:
    if rows > rect["height"] or cols > rect["width"]:
        raise GuiError("GRID_TOO_FINE", "网格细于原始屏幕像素，请减少行列数或使用上一级View。")
    cells: list[dict[str, Any]] = []
    for row in range(rows):
        top = rect["top"] + round(row * rect["height"] / rows)
        bottom = rect["top"] + round((row + 1) * rect["height"] / rows)
        for col in range(cols):
            left = rect["left"] + round(col * rect["width"] / cols)
            right = rect["left"] + round((col + 1) * rect["width"] / cols)
            cells.append({
                "cell_id": row * cols + col + 1,
                "row": row + 1,
                "column": col + 1,
                "rect_absolute": {"left": left, "top": top, "width": right - left, "height": bottom - top},
            })
    return cells


OVERLAY_MODES = ("labels+lines", "lines", "none")
DEFAULT_OVERLAY = "labels+lines"
# Display-only limits: labels occupy at most 45% of cell width / 30% of height.
# If even 9px text cannot fit, omit all labels and report that explicitly.
LABEL_MIN_FONT = 9
LABEL_MAX_FONT = 16
LABEL_WIDTH_FRACTION = 0.45
LABEL_HEIGHT_FRACTION = 0.30


def overlay_image(raw: Image.Image, cells: list[dict[str, Any]], source_rect: dict[str, int],
                  mode: str = DEFAULT_OVERLAY) -> Image.Image:
    if mode not in OVERLAY_MODES:
        raise GuiError("INVALID_ARGUMENT", "overlay必须是labels+lines、lines或none。")
    image = raw.convert("RGB").copy()
    draw = ImageDraw.Draw(image, "RGBA")
    rectangles = []
    for cell in cells:
        rect = cell["rect_absolute"]
        left = round((rect["left"] - source_rect["left"]) * image.width / source_rect["width"])
        top = round((rect["top"] - source_rect["top"]) * image.height / source_rect["height"])
        right = round((rect["left"] - source_rect["left"] + rect["width"]) * image.width / source_rect["width"])
        bottom = round((rect["top"] - source_rect["top"] + rect["height"]) * image.height / source_rect["height"])
        rectangles.append((left, top, right, bottom))
    if mode != "none":
        # Each boundary is drawn once, at one final-output pixel, never per-cell twice.
        xs = {min(image.width - 1, edge) for rect in rectangles for edge in (rect[0], rect[2])}
        ys = {min(image.height - 1, edge) for rect in rectangles for edge in (rect[1], rect[3])}
        for x in sorted(xs):
            draw.line((x, 0, x, image.height - 1), fill=(0, 230, 255, 210), width=1)
        for y in sorted(ys):
            draw.line((0, y, image.width - 1, y), fill=(0, 230, 255, 210), width=1)
    font = None
    font_size = 0
    pad = 1
    boxes = []
    if mode == "labels+lines":
        font_path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "segoeuib.ttf"
        for size in range(LABEL_MAX_FONT, LABEL_MIN_FONT - 1, -1):
            try:
                candidate = ImageFont.truetype(str(font_path), size)
            except OSError as exc:
                raise GuiError("OVERLAY_FONT_UNAVAILABLE", "无法加载网格字体；可显式选择overlay=lines或none。") from exc
            boxes = [draw.textbbox((0, 0), str(cell["cell_id"]), font=candidate) for cell in cells]
            if all(box[2] - box[0] + 2 * pad <= (rect[2] - rect[0]) * LABEL_WIDTH_FRACTION
                   and box[3] - box[1] + 2 * pad <= (rect[3] - rect[1]) * LABEL_HEIGHT_FRACTION
                   for rect, box in zip(rectangles, boxes)):
                font, font_size = candidate, size
                break
    if font is not None:
        for cell, rect, box in zip(cells, rectangles, boxes):
            left, top = rect[0] + 2, rect[1] + 2
            width, height = box[2] - box[0] + 2 * pad, box[3] - box[1] + 2 * pad
            draw.rectangle((left, top, left + width - 1, top + height - 1), fill=(0, 22, 34, 210))
            draw.text((left + pad - box[0], top + pad - box[1]), str(cell["cell_id"]),
                      font=font, fill=(235, 255, 255, 255))
    image.info["overlay"] = {
        "requested": mode,
        "effective": "lines" if mode == "labels+lines" and font is None else mode,
        "labels_visible": font is not None,
        "labels_hidden_reason": "cells_too_small" if mode == "labels+lines" and font is None else None,
        "font_size_px": font_size, "line_width_px": 0 if mode == "none" else 1,
        "numbering": "row_major_top_left_1_based",
    }
    return image


def safe_session_id(value: str) -> str:
    normalized = str(value or "").strip()
    if not re.fullmatch(r"gui_[a-f0-9]{32}", normalized):
        raise GuiError("GUI_SESSION_INVALID", "GUI Session ID无效。")
    return normalized


def render_lock_overlay(width: int, height: int, dpi: int) -> Image.Image:
    """Only the edge glow and top notice have alpha; the working area stays untouched."""
    if width <= 0 or height <= 0 or dpi <= 0:
        raise GuiError("OVERLAY_GEOMETRY_INVALID", "无法取得界面提示层的尺寸或缩放比例。")
    scale = dpi / 96
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    glow_width = min(round(28 * scale), min(width, height) // 2)
    for inset in range(glow_width):
        alpha = round(125 * math.exp(-inset / (6 * scale)))
        draw.rectangle((inset, inset, width - 1 - inset, height - 1 - inset),
                       outline=(90, 184, 244, alpha))
    draw.rectangle((0, 0, width - 1, height - 1), outline=(160, 220, 255, 180),
                   width=max(1, round(scale)))

    # Render just the notice at 2x for smooth type/rounded edges, not the whole monitor.
    density = 2
    font_path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "msyh.ttc"
    title_font = ImageFont.truetype(str(font_path), 14 * density)
    detail_font = ImageFont.truetype(str(font_path), 13 * density)
    title, detail = "天策正在操作", "鼠标与键盘已锁定"
    title_width = math.ceil(title_font.getlength(title))
    detail_width = math.ceil(detail_font.getlength(detail))
    card_width = title_width + detail_width + 174 * density
    card_height, margin = 42 * density, 12 * density
    card = Image.new("RGBA", (card_width + margin * 2, card_height + margin * 2))
    bounds = (margin, margin, margin + card_width, margin + card_height)
    shadow = ImageDraw.Draw(card)
    shadow.rounded_rectangle(bounds, radius=21 * density, fill=(0, 0, 0, 90))
    card = card.filter(ImageFilter.GaussianBlur(6 * density))
    ink = ImageDraw.Draw(card)
    ink.rounded_rectangle(bounds, radius=21 * density, fill=(17, 25, 36, 235),
                          outline=(157, 208, 242, 85), width=density)
    center_y = margin + card_height // 2
    x = margin + 19 * density
    ink.ellipse((x - 3 * density, center_y - 3 * density,
                 x + 3 * density, center_y + 3 * density), fill=(134, 216, 244, 255))
    x += 13 * density
    ink.text((x, center_y), title, font=title_font, anchor="lm", fill=(239, 246, 252, 255))
    x += title_width + 15 * density
    ink.line((x, center_y - 7 * density, x, center_y + 7 * density), fill=(128, 151, 175, 90), width=density)
    x += 15 * density
    ink.text((x, center_y), detail, font=detail_font, anchor="lm", fill=(184, 199, 215, 255))
    x += detail_width + 16 * density
    ink.rounded_rectangle((x, center_y - 11 * density, x + 34 * density, center_y + 11 * density),
                          radius=5 * density, fill=(51, 65, 81, 220), outline=(163, 185, 205, 90), width=density)
    ink.text((x + 17 * density, center_y), "Esc", font=detail_font, anchor="mm", fill=(230, 239, 247, 255))
    ink.text((x + 42 * density, center_y), "退出", font=detail_font, anchor="lm", fill=(209, 221, 232, 255))
    notice_scale = min(scale, width / (card.width / density), height / (card.height / density))
    card = card.resize((max(1, round(card.width * notice_scale / density)),
                        max(1, round(card.height * notice_scale / density))), Image.Resampling.LANCZOS)
    image.alpha_composite(card, ((width - card.width) // 2, 0))
    return image


class GuiService:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.workspace = Path(args.workspace).resolve()
        self.gui_root = self.workspace / ".Tiance" / "gui-temp"
        self.state_path = Path(args.state_file).resolve()
        self.lock_id = args.lock_id
        self.token = args.token
        self.marker = int(args.marker) & 0xFFFFFFFF
        self.block_user_input = True
        self.project_id = args.project_id
        self.session_id = args.session_id
        self.overlay_windows: list[int] = []
        self.window_proc = WNDPROC(self._window_proc)
        self.mouse_hook_proc = HOOKPROC(self._mouse_hook)
        self.keyboard_hook_proc = HOOKPROC(self._keyboard_hook)
        self.mouse_hook = 0
        self.keyboard_hook = 0
        self.main_thread_id = int(kernel32.GetCurrentThreadId())
        self.stop_event = threading.Event()
        self.cancel_event = threading.Event()
        self.service_lock = threading.RLock()
        self.blocked_mouse_events = 0
        self.blocked_keyboard_events = 0
        self.external_mouse_events = 0
        self.external_keyboard_events = 0
        self.input_events_sent = 0
        self.held_mouse_buttons: set[str] = set()
        self.held_keys: set[tuple[int, bool]] = set()
        self.created_gui_sessions: set[str] = set()
        self.capture_mode = "exclude_from_capture"
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.bind(("127.0.0.1", 0))
        self.server_socket.listen(8)
        self.server_socket.settimeout(0.5)
        self.port = int(self.server_socket.getsockname()[1])
        self.server_thread = threading.Thread(target=self._serve, name="gui-control-rpc", daemon=True)
        self.startup_failed = False
        self.idle_timeout_seconds = float(getattr(args, "idle_timeout_seconds", 120))
        self.last_activity = time.monotonic()
        self.owner_status_url = str(getattr(args, "owner_status_url", ""))
        self.owner_run_id: str | None = None
        self.stop_reason: str | None = None
        self.startup_confirmed = threading.Event()
        self.startup_deadline = time.monotonic() + float(getattr(args, "startup_timeout_seconds", 10))
        if not getattr(args, "require_startup_confirmation", False):
            self.startup_confirmed.set()

    def _receive_startup_confirmation(self) -> None:
        try:
            confirmed = sys.stdin.readline() == "confirm\n"
        except (OSError, ValueError):
            confirmed = False
        if confirmed:
            self.startup_confirmed.set()
        else:
            self.request_stop("startup_caller_disconnected")

    def run(self) -> int:
        try:
            self.gui_root.mkdir(parents=True, exist_ok=True)
            if not self.startup_confirmed.is_set():
                threading.Thread(target=self._receive_startup_confirmation, name="gui-startup-owner", daemon=True).start()
            # Publish and verify access before installing hooks. No ACL is changed.
            self._write_active_state("starting")
            state = read_json(self.state_path)
            if state.get("lock_id") != self.lock_id:
                raise GuiError("GUI_RUNTIME_STATE_INVALID", "启动状态归属校验失败。")
            if self.owner_status_url:
                self.owner_run_id = self._read_owner_run()
            self.capture_mode = self._detect_capture_mode()
            if self.block_user_input:
                self._create_windows()
            if self.cancel_event.is_set():
                raise GuiError("GUI_START_CANCELLED", "启动调用已退出。")
            self._install_hooks()
            if self.cancel_event.is_set():
                raise GuiError("GUI_START_CANCELLED", "启动调用已退出。")
            self._write_active_state("active")
            self.server_thread.start()
            threading.Thread(target=self._watch_lifecycle, name="gui-lifecycle", daemon=True).start()
            message = wintypes.MSG()
            while not self.stop_event.is_set():
                result = user32.GetMessageW(ctypes.byref(message), 0, 0, 0)
                if result <= 0:
                    break
                user32.TranslateMessage(ctypes.byref(message))
                user32.DispatchMessageW(ctypes.byref(message))
            return 0
        except Exception as exc:
            self.startup_failed = True
            try:
                self._write_active_state("failed", error=f"{type(exc).__name__}: {exc}")
            except OSError:
                pass  # Failure to report must not bypass hook release in finally.
            return 1
        finally:
            self.cancel_event.set()
            self.stop_event.set()
            try:
                self.server_socket.close()
            except OSError:
                pass
            # 保持主线程泵送钩子消息，等待动作线程结算按键抬起后再清理。
            while not self.service_lock.acquire(blocking=False):
                message = wintypes.MSG()
                while user32.PeekMessageW(ctypes.byref(message), 0, 0, 0, 1):
                    user32.TranslateMessage(ctypes.byref(message))
                    user32.DispatchMessageW(ctypes.byref(message))
                time.sleep(0.01)
            try:
                self._uninstall_hooks()
                self._release_held_inputs()
                self._destroy_windows()
                self._cleanup_gui_sessions()
            finally:
                self.service_lock.release()
            if not self.startup_failed:
                try:
                    self._remove_active_state()
                except (OSError, GuiError):
                    pass  # Process is exiting with hooks removed; a stale file is not a live lock.

    def _read_owner_run(self) -> str:
        # Public run-state API; no message/history reads and no private database access.
        with urllib.request.urlopen(self.owner_status_url, timeout=2) as response:
            status = json.load(response)
        if not status.get("running") or not isinstance(status.get("run_id"), str):
            raise GuiError("GUI_OWNER_STOPPED", "来源会话已停止运行。")
        return status["run_id"]

    def _check_idle(self, now: float) -> None:
        # Acquire the same execution lock: an active operation is never treated as idle.
        if self.service_lock.acquire(blocking=False):
            try:
                if now - self.last_activity >= self.idle_timeout_seconds:
                    self.request_stop("idle_timeout")
            finally:
                self.service_lock.release()

    def _watch_lifecycle(self) -> None:
        next_owner_check = 0.0
        while not self.stop_event.wait(0.25):
            now = time.monotonic()
            if not self.startup_confirmed.is_set() and now >= self.startup_deadline:
                self.request_stop("startup_confirmation_timeout")
                return
            self._check_idle(now)
            # Owner check every second, including while an action is active.
            if self.owner_status_url and now >= next_owner_check:
                next_owner_check = now + 1
                try:
                    if self._read_owner_run() != self.owner_run_id:
                        self.request_stop("owner_run_changed")
                except Exception:
                    self.request_stop("owner_stopped_or_disconnected")

    def _cleanup_gui_sessions(self) -> None:
        for gui_session_id in list(self.created_gui_sessions):
            try:
                shutil.rmtree(self._session_dir(gui_session_id))
            except FileNotFoundError:
                pass
            except OSError:
                pass
            finally:
                self.created_gui_sessions.discard(gui_session_id)

    def _write_active_state(self, status: str, *, error: str | None = None) -> None:
        payload = {
            "schema_version": 1,
            "status": status,
            "lock_id": self.lock_id,
            "pid": os.getpid(),
            "port": self.port,
            "token": self.token,
            "input_marker": self.marker,
            "project_id": self.project_id,
            "session_id": self.session_id,
            "workspace": str(self.workspace),
            "capture_mode": self.capture_mode,
            "input_mode": "blocked" if self.block_user_input else "observed",
            "created_at": now_iso(),
        }
        if error:
            payload["error"] = error
        atomic_json(self.state_path, payload)

    def _remove_active_state(self) -> None:
        try:
            current = read_json(self.state_path)
        except GuiError:
            return
        if current.get("lock_id") == self.lock_id:
            self.state_path.unlink(missing_ok=True)

    def _register_class(self, name: str) -> None:
        instance = kernel32.GetModuleHandleW(None)
        window_class = WNDCLASSEXW(
            cbSize=ctypes.sizeof(WNDCLASSEXW),
            style=0,
            lpfnWndProc=self.window_proc,
            cbClsExtra=0,
            cbWndExtra=0,
            hInstance=instance,
            hIcon=0,
            hCursor=user32.LoadCursorW(None, ctypes.c_void_p(32512)),
            hbrBackground=0,
            lpszMenuName=None,
            lpszClassName=name,
            hIconSm=0,
        )
        if not user32.RegisterClassExW(ctypes.byref(window_class)):
            error = ctypes.get_last_error()
            if error != 1410:
                raise ctypes.WinError(error)

    def _create_windows(self) -> None:
        self.overlay_class = f"TianceGuiOverlay_{os.getpid()}"
        self._register_class(self.overlay_class)
        instance = kernel32.GetModuleHandleW(None)
        monitors = monitor_rects()
        if not monitors:
            raise GuiError("DISPLAY_UNAVAILABLE", "没有检测到可用显示器。")
        for rect in monitors:
            hwnd = user32.CreateWindowExW(
                WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_LAYERED | WS_EX_NOACTIVATE | WS_EX_TRANSPARENT,
                self.overlay_class,
                "Tiance AI Control Overlay",
                WS_POPUP,
                rect["left"], rect["top"], rect["width"], rect["height"],
                0, 0, instance, None,
            )
            if not hwnd:
                raise ctypes.WinError(ctypes.get_last_error())
            self.overlay_windows.append(int(hwnd))
            # A redirected, color-keyed host supports capture exclusion; the per-pixel
            # alpha child is composed inside it and is excluded with the parent.
            if not user32.SetLayeredWindowAttributes(hwnd, 0, 255, LWA_COLORKEY):
                raise GuiError("OVERLAY_RENDER_FAILED", "无法创建透明界面提示窗口。")
            self._exclude_window_from_capture(hwnd)
            child = user32.CreateWindowExW(
                WS_EX_LAYERED | WS_EX_NOACTIVATE | WS_EX_TRANSPARENT,
                self.overlay_class, "Tiance AI Control Glow", WS_CHILD,
                0, 0, rect["width"], rect["height"], hwnd, 0, instance, None,
            )
            if not child:
                raise GuiError("OVERLAY_RENDER_FAILED", "无法创建柔光提示层。")
            self._update_overlay(int(child), {**rect, "left": 0, "top": 0})
            user32.ShowWindow(child, SW_SHOWNOACTIVATE)
            user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
            user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)

    def _destroy_windows(self) -> None:
        for hwnd in self.overlay_windows:
            if hwnd and user32.IsWindow(hwnd):
                user32.DestroyWindow(hwnd)
        self.overlay_windows.clear()

    def _window_proc(self, hwnd: int, message: int, wparam: int, lparam: int) -> int:
        if message == WM_NCHITTEST:
            return HTTRANSPARENT
        if message == WM_PAINT:
            paint = PAINTSTRUCT()
            dc = user32.BeginPaint(hwnd, ctypes.byref(paint))
            if dc and not user32.GetWindowLongPtrW(hwnd, GWL_STYLE) & WS_CHILD:
                # The host is entirely color-key transparent. Child pixels are owned
                # by UpdateLayeredWindow and must not be repainted through GDI.
                client = wintypes.RECT()
                user32.GetClientRect(hwnd, ctypes.byref(client))
                user32.FillRect(dc, ctypes.byref(client), gdi32.GetStockObject(4))  # BLACK_BRUSH
            user32.EndPaint(hwnd, ctypes.byref(paint))
            return 0
        if message == WM_APP_STOP:
            user32.PostQuitMessage(0)
            return 0
        if message == WM_DESTROY:
            return 0
        return int(user32.DefWindowProcW(hwnd, message, wparam, lparam))

    def _update_overlay(self, hwnd: int, rect: dict[str, int]) -> None:
        image = render_lock_overlay(rect["width"], rect["height"], int(user32.GetDpiForWindow(hwnd)))
        # UpdateLayeredWindow requires premultiplied BGRA, not straight-alpha RGBA.
        pixels = image.convert("RGBa").tobytes("raw", "BGRa")
        info = BITMAPINFO(bmiHeader=BITMAPINFOHEADER(
            biSize=ctypes.sizeof(BITMAPINFOHEADER), biWidth=image.width, biHeight=-image.height,
            biPlanes=1, biBitCount=32, biCompression=0, biSizeImage=len(pixels),
        ))
        dc = gdi32.CreateCompatibleDC(None)
        if not dc:
            raise GuiError("OVERLAY_RENDER_FAILED", "无法创建界面提示层绘图上下文。")
        bitmap, old_bitmap = None, None
        try:
            bits = ctypes.c_void_p()
            bitmap = gdi32.CreateDIBSection(dc, ctypes.byref(info), 0, ctypes.byref(bits), None, 0)
            if not bitmap or not bits.value:
                raise GuiError("OVERLAY_RENDER_FAILED", "无法创建界面提示层位图。")
            old_bitmap = gdi32.SelectObject(dc, bitmap)
            if not old_bitmap or old_bitmap == ctypes.c_void_p(-1).value:
                old_bitmap = None
                raise GuiError("OVERLAY_RENDER_FAILED", "无法选择界面提示层位图。")
            ctypes.memmove(bits, pixels, len(pixels))
            destination, source = POINT(rect["left"], rect["top"]), POINT(0, 0)
            size = wintypes.SIZE(image.width, image.height)
            blend = BLENDFUNCTION(0, 0, 255, AC_SRC_ALPHA)
            if not user32.UpdateLayeredWindow(hwnd, None, ctypes.byref(destination), ctypes.byref(size),
                                             dc, ctypes.byref(source), 0, ctypes.byref(blend), ULW_ALPHA):
                raise GuiError("OVERLAY_RENDER_FAILED", "无法显示透明界面提示层。")
        finally:
            if old_bitmap:
                gdi32.SelectObject(dc, old_bitmap)
            if bitmap:
                gdi32.DeleteObject(bitmap)
            gdi32.DeleteDC(dc)

    def _detect_capture_mode(self) -> str:
        # 老版本会把EXCLUDEFROMCAPTURE当成MONITOR，截图出现黑块而非真实桌面。
        # 不通过动态画面差异推断系统能力，也不隐藏覆盖层来截图。
        if sys.getwindowsversion().build < 19041:
            raise GuiError("CAPTURE_EXCLUSION_UNAVAILABLE", "无闪烁界面锁需要Windows 10 2004或更新版本。")
        enabled = wintypes.BOOL()
        if dwmapi is None or dwmapi.DwmIsCompositionEnabled(ctypes.byref(enabled)) != 0 or not enabled.value:
            raise GuiError("CAPTURE_EXCLUSION_UNAVAILABLE", "桌面合成不可用，无法保持覆盖层显示并取得干净截图。")
        return "exclude_from_capture"

    def _exclude_window_from_capture(self, hwnd: int) -> None:
        affinity = wintypes.DWORD()
        if (
            not user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE)
            or not user32.GetWindowDisplayAffinity(hwnd, ctypes.byref(affinity))
            or affinity.value != WDA_EXCLUDEFROMCAPTURE
        ):
            raise GuiError("CAPTURE_EXCLUSION_UNAVAILABLE", "Windows未能将界面锁排除出截图，已停止启动；不会切换到隐藏覆盖层的闪烁模式。")

    def _install_hooks(self) -> None:
        instance = kernel32.GetModuleHandleW(None)
        self.mouse_hook = int(user32.SetWindowsHookExW(WH_MOUSE_LL, self.mouse_hook_proc, instance, 0) or 0)
        self.keyboard_hook = int(user32.SetWindowsHookExW(WH_KEYBOARD_LL, self.keyboard_hook_proc, instance, 0) or 0)
        if not self.mouse_hook or not self.keyboard_hook:
            raise GuiError("INPUT_HOOK_UNAVAILABLE", "无法安装Windows输入监测，GUI后台运行器未启动。")

    def _uninstall_hooks(self) -> None:
        if self.mouse_hook:
            user32.UnhookWindowsHookEx(self.mouse_hook)
            self.mouse_hook = 0
        if self.keyboard_hook:
            user32.UnhookWindowsHookEx(self.keyboard_hook)
            self.keyboard_hook = 0

    def _mouse_hook(self, code: int, wparam: int, lparam: int) -> int:
        if code >= 0:
            event = ctypes.cast(lparam, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
            if int(event.dwExtraInfo) & 0xFFFFFFFF == self.marker:
                return int(user32.CallNextHookEx(self.mouse_hook, code, wparam, lparam))
            if self.block_user_input:
                self.blocked_mouse_events += 1
                return 1
            self.external_mouse_events += 1
            return int(user32.CallNextHookEx(self.mouse_hook, code, wparam, lparam))
        return int(user32.CallNextHookEx(self.mouse_hook, code, wparam, lparam))

    def _keyboard_hook(self, code: int, wparam: int, lparam: int) -> int:
        if code >= 0:
            event = ctypes.cast(lparam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            if int(event.dwExtraInfo) & 0xFFFFFFFF == self.marker:
                return int(user32.CallNextHookEx(self.keyboard_hook, code, wparam, lparam))
            if self.block_user_input:
                self.blocked_keyboard_events += 1
                if event.vkCode == VK_CODES["esc"] and int(wparam) in {WM_KEYUP, WM_SYSKEYUP}:
                    self.request_stop("user_escape")
                return 1
            self.external_keyboard_events += 1
            return int(user32.CallNextHookEx(self.keyboard_hook, code, wparam, lparam))
        return int(user32.CallNextHookEx(self.keyboard_hook, code, wparam, lparam))

    def request_stop(self, reason: str) -> None:
        self.stop_reason = reason
        self.cancel_event.set()
        self.stop_event.set()
        user32.PostThreadMessageW(self.main_thread_id, WM_APP_STOP, 0, 0)

    def _serve(self) -> None:
        while not self.stop_event.is_set():
            try:
                connection, _address = self.server_socket.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=self._handle_connection, args=(connection,), daemon=True).start()

    def _watch_connection(self, connection: socket.socket, finished: threading.Event) -> None:
        while not finished.is_set() and not self.stop_event.is_set():
            try:
                readable, _, _ = select.select([connection], [], [], 0.1)
                if readable and not finished.is_set() and not connection.recv(1, socket.MSG_PEEK):
                    self.request_stop("tool_connection_lost")
                    return
            except OSError:
                if not finished.is_set():
                    self.request_stop("tool_connection_lost")
                return

    def _handle_connection(self, connection: socket.socket) -> None:
        with connection:
            connection.settimeout(130)
            finished = threading.Event()
            try:
                request = self._receive_json(connection)
                if (request.get("token") == self.token and request.get("project_id") == self.project_id
                        and request.get("session_id") == self.session_id
                        and request.get("method") in {"inspect", "mouse", "keyboard", "batch"}):
                    threading.Thread(target=self._watch_connection, args=(connection, finished), daemon=True).start()
                with physical_coordinates():
                    response = self._dispatch(request)
            except GuiError as exc:
                response = {"ok": False, "error": exc.message, "error_info": {"code": exc.code, "details": exc.details}}
            except Exception as exc:
                response = {
                    "ok": False,
                    "error": f"{type(exc).__name__}: {exc}",
                    "error_info": {"code": "GUI_INTERNAL_ERROR"},
                }
            finally:
                finished.set()
            try:
                connection.sendall((json.dumps(response, ensure_ascii=False) + "\n").encode("utf-8"))
            except OSError:
                pass

    @staticmethod
    def _receive_json(connection: socket.socket) -> dict[str, Any]:
        data = bytearray()
        while len(data) <= 2_000_000:
            chunk = connection.recv(65536)
            if not chunk:
                break
            data.extend(chunk)
            if b"\n" in chunk:
                break
        if len(data) > 2_000_000:
            raise GuiError("INVALID_ARGUMENT", "GUI请求过大。")
        try:
            payload = json.loads(bytes(data).split(b"\n", 1)[0].decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise GuiError("INVALID_ARGUMENT", "GUI请求不是有效JSON。") from exc
        if not isinstance(payload, dict):
            raise GuiError("INVALID_ARGUMENT", "GUI请求必须是对象。")
        return payload

    def _dispatch(self, request: dict[str, Any]) -> dict[str, Any]:
        if request.get("token") != self.token:
            raise GuiError("GUI_RUNTIME_AUTH_FAILED", "GUI后台运行器连接凭证无效。")
        if request.get("project_id") != self.project_id or request.get("session_id") != self.session_id:
            raise GuiError("GUI_RUNTIME_OWNED_BY_OTHER_SESSION", "GUI后台运行器属于另一个项目或会话。")
        method = str(request.get("method") or "").strip()
        payload = request.get("payload")
        arguments = payload if isinstance(payload, dict) else {}
        if method == "status":
            return self.status()
        if method == "unlock":
            response = {"ok": True, "summary": "GUI后台运行器已退出。", "data": {"runtime_id": self.lock_id, "released": True}}
            self.cancel_event.set()  # Reject queued work before acknowledging unlock.
            threading.Timer(0.05, lambda: self.request_stop("tool_unlock")).start()
            return response
        with self.service_lock:
            if self.cancel_event.is_set():
                raise GuiError("GUI_RUNTIME_STOPPED", "GUI后台运行器已经退出。")
            if not self.block_user_input:
                raise GuiError("GUI_LOCK_REQUIRED", "请先调用gui_runtime start锁定界面。")
            if method == "inspect":
                result = self.inspect(arguments)
            elif method == "mouse":
                result = self.mouse(arguments)
            elif method == "keyboard":
                result = self.keyboard(arguments)
            elif method == "batch":
                result = self.batch(arguments)
            else:
                raise GuiError("INVALID_ARGUMENT", f"不支持的GUI方法：{method}")
            if result.get("ok"):
                self.last_activity = time.monotonic()
            return result

    def status(self) -> dict[str, Any]:
        return {
            "ok": True,
            "summary": "GUI后台运行器正在工作。",
            "data": {
                "active": bool(self.mouse_hook and self.keyboard_hook) and not self.cancel_event.is_set(),
                "hooks_installed": bool(self.mouse_hook and self.keyboard_hook),
                "pid": os.getpid(),
                "port": self.port,
                "runtime_id": self.lock_id,
                "project_id": self.project_id,
                "session_id": self.session_id,
                "capture_mode": self.capture_mode,
                "input_mode": "blocked" if self.block_user_input else "observed",
                "mouse_movement_allowed": not self.block_user_input,
                "blocked_input_counts": {"mouse": self.blocked_mouse_events, "keyboard": self.blocked_keyboard_events},
                "exit_shortcut": "Esc",
                "idle_timeout_seconds": self.idle_timeout_seconds,
                "idle_remaining_seconds": max(0, self.idle_timeout_seconds - (time.monotonic() - self.last_activity)),
                "stop_reason": self.stop_reason,
                "coordinate_space": "physical_screen_pixels",
                "external_input_counts": {
                    "mouse": self.external_mouse_events,
                    "keyboard": self.external_keyboard_events,
                },
            },
        }

    def _capture_bbox(self, rect: dict[str, int]) -> Image.Image:
        if rect["width"] < 2 or rect["height"] < 2:
            raise GuiError("CAPTURE_FAILED", "截图区域尺寸无效。")
        self._detect_capture_mode()
        return ImageGrab.grab(bbox=rect_ltrb(rect), all_screens=True).convert("RGB")

    def _target_rect(self, target: dict[str, Any]) -> dict[str, int]:
        if target["type"] == "window":
            return window_rect(int(target["hwnd"]))
        monitor = int(target.get("monitor", 0))
        if monitor == 0:
            return virtual_rect()
        monitors = monitor_rects()
        if monitor < 1 or monitor > len(monitors):
            raise GuiError("INVALID_ARGUMENT", f"显示器编号必须在1到{len(monitors)}之间，0表示全部显示器。")
        return {key: int(monitors[monitor - 1][key]) for key in ("left", "top", "width", "height")}

    def _capture_target(self, target: dict[str, Any]) -> tuple[Image.Image, dict[str, int]]:
        rect = self._target_rect(target)
        windows = drag_window_snapshot(self.overlay_windows)
        image = self._capture_bbox(rect)
        # Carry acquisition-time evidence with this image, not the later frame-save
        # time. _create_frame persists it in the frame JSON, not the PNG/context.
        image.info["drag_windows"] = windows
        return image, rect

    def _session_dir(self, gui_session_id: str) -> Path:
        session_id = safe_session_id(gui_session_id)
        target = (self.gui_root / session_id).resolve()
        if target.parent != self.gui_root.resolve():
            raise GuiError("GUI_SESSION_INVALID", "GUI Session目录无效。")
        return target

    def _load_session(self, gui_session_id: str) -> dict[str, Any]:
        folder = self._session_dir(gui_session_id)
        session = read_json(folder / "session.json")
        if session.get("lock_id") != self.lock_id:
            raise GuiError("GUI_SESSION_RUNTIME_MISMATCH", "GUI Session不属于当前后台运行器。")
        if session.get("status") != "active":
            raise GuiError("GUI_SESSION_CLOSED", "GUI Session已经关闭。")
        return session

    def _save_session(self, session: dict[str, Any]) -> None:
        atomic_json(self._session_dir(str(session["gui_session_id"])) / "session.json", session)

    def _frame(self, session: dict[str, Any], frame_id: int) -> dict[str, Any]:
        for frame in session.get("frames", []):
            if int(frame.get("frame_id", -1)) == int(frame_id):
                return frame
        raise GuiError("FRAME_NOT_FOUND", f"没有找到Frame {frame_id}。")

    @staticmethod
    def _view(frame: dict[str, Any], view_id: str) -> dict[str, Any]:
        view = (frame.get("views") or {}).get(str(view_id))
        if not isinstance(view, dict):
            available_view_ids = list(frame.get("views") or {})
            raise GuiError(
                "VIEW_NOT_FOUND",
                f"Frame {frame['frame_id']}中没有View {view_id}；可用View：{', '.join(available_view_ids)}。"
                "放大View仅属于创建它的Frame，新Frame不继承旧View；请从当前Frame的root重新zoom，"
                "并使用该Frame实际返回的view_id。",
                {"frame_id": frame["frame_id"], "requested_view_id": view_id,
                 "available_view_ids": available_view_ids},
            )
        return view

    @staticmethod
    def _cell(view: dict[str, Any], cell_id: int) -> dict[str, Any]:
        for cell in view.get("cells", []):
            if int(cell.get("cell_id", -1)) == int(cell_id):
                return cell
        raise GuiError(
            "CELL_NOT_FOUND",
            f"View {view['view_id']}的已有网格中没有Cell {cell_id}。"
            "请按该View已有网格的有效格号选择区域；zoom的grid_rows/grid_cols等只设置放大后的新网格，"
            "不改变来源格号。",
            {"view_id": view["view_id"], "requested_cell_id": cell_id,
             "grid": view["grid"], "available_cell_ids": [cell["cell_id"] for cell in view.get("cells", [])]},
        )

    def _create_view(
        self,
        *,
        folder: Path,
        frame_id: int,
        view_id: str,
        raw: Image.Image,
        source_rect: dict[str, int],
        grid_mode: str,
        grid_target_cells: int,
        grid_rows: int | None,
        grid_cols: int | None,
        zoom_scale_percent: int = 100,
        overlay: str = DEFAULT_OVERLAY,
        parent_view_id: str | None = None,
    ) -> dict[str, Any]:
        if raw.size != (source_rect["width"], source_rect["height"]):
            raise GuiError("CAPTURE_GEOMETRY_MISMATCH", "截图像素尺寸与屏幕区域不一致，未建立坐标映射。")
        rows, cols = choose_grid(raw.width, raw.height, grid_mode, grid_target_cells, grid_rows, grid_cols)
        cells = build_cells(source_rect, rows, cols)
        if not 100 <= zoom_scale_percent <= 800:
            raise GuiError("INVALID_ARGUMENT", "zoom_scale_percent必须在100到800之间。")
        display_size = (round(raw.width * zoom_scale_percent / 100), round(raw.height * zoom_scale_percent / 100))
        display = raw.resize(display_size, Image.Resampling.NEAREST) if display_size != raw.size else raw
        rendered = overlay_image(display, cells, source_rect, overlay)
        frame_folder = folder / f"frame_{frame_id:03d}"
        frame_folder.mkdir(parents=True, exist_ok=True)
        safe_view = "root" if view_id == "root" else "zoom_" + re.sub(r"[^0-9A-Za-z_-]", "_", view_id)
        raw_path = frame_folder / f"{safe_view}_raw.png"
        overlay_path = frame_folder / f"{safe_view}_overlay.png"
        raw.save(raw_path, format="PNG", optimize=True)
        rendered.save(overlay_path, format="PNG", optimize=True)
        return {
            "view_id": view_id,
            "source_rect_absolute": source_rect,
            "image_size": {"width": rendered.width, "height": rendered.height},
            "overlay": rendered.info["overlay"],
            "parent_view_id": parent_view_id,
            "zoom_scale_percent": zoom_scale_percent,
            "grid": {"rows": rows, "columns": cols},
            "cells": cells,
            "raw_image": raw_path.relative_to(folder).as_posix(),
            "overlay_image": overlay_path.relative_to(folder).as_posix(),
        }

    @staticmethod
    def _native_focus() -> int:
        class GUIThreadInfo(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD),
                        ("hwndActive", wintypes.HWND), ("hwndFocus", wintypes.HWND),
                        ("hwndCapture", wintypes.HWND), ("hwndMenuOwner", wintypes.HWND),
                        ("hwndMoveSize", wintypes.HWND), ("hwndCaret", wintypes.HWND),
                        ("rcCaret", wintypes.RECT)]
        info = GUIThreadInfo(cbSize=ctypes.sizeof(GUIThreadInfo))
        if not user32.GetGUIThreadInfo(0, ctypes.byref(info)):
            raise GuiError("GUI_FOCUS_UNAVAILABLE", "无法确认当前输入焦点。")
        return int(info.hwndFocus or 0)

    def _create_frame(
        self,
        session: dict[str, Any],
        *,
        reason: str,
        raw: Image.Image | None = None,
        source_rect: dict[str, int] | None = None,
        grid_mode: str | None = None,
        grid_target_cells: int | None = None,
        grid_rows: int | None = None,
        grid_cols: int | None = None,
        overlay: str | None = None,
    ) -> tuple[dict[str, Any], Path]:
        if raw is None or source_rect is None:
            raw, source_rect = self._capture_target(session["target"])
        frame_id = len(session.get("frames", []))
        folder = self._session_dir(session["gui_session_id"])
        grid = dict(session.get("grid_settings") or {
            "grid_mode": "auto", "grid_target_cells": 16, "grid_rows": None, "grid_cols": None,
        })
        for name, value in (("grid_mode", grid_mode), ("grid_target_cells", grid_target_cells),
                            ("grid_rows", grid_rows), ("grid_cols", grid_cols)):
            if value is not None:
                grid[name] = value
        session["grid_settings"] = grid
        if overlay is not None and overlay not in OVERLAY_MODES:
            raise GuiError("INVALID_ARGUMENT", "overlay必须是labels+lines、lines或none。")
        session["overlay_mode"] = overlay if overlay is not None else session.get("overlay_mode", DEFAULT_OVERLAY)
        root = self._create_view(
            folder=folder,
            frame_id=frame_id,
            view_id="root",
            raw=raw,
            source_rect=source_rect,
            overlay=session["overlay_mode"],
            **grid,
        )
        frame = {
            "frame_id": frame_id,
            "created_at": now_iso(),
            "reason": reason,
            "capture_rect": source_rect,
            "focus_window": self._native_focus(),
            "drag_windows": raw.info.get("drag_windows", []),
            "views": {"root": root},
        }
        session.setdefault("frames", []).append(frame)
        session["latest_frame_id"] = frame_id
        self._save_session(session)
        return frame, folder / root["overlay_image"]

    def _result_with_image(
        self,
        *,
        summary: str,
        session: dict[str, Any],
        frame: dict[str, Any],
        view: dict[str, Any],
        image_path: Path,
        interface_state: dict[str, Any] | None = None,
        performed: bool = True,
    ) -> dict[str, Any]:
        return {
            "ok": True,
            "summary": summary,
            "data": {
                "gui_session_id": session["gui_session_id"],
                "frame_id": frame["frame_id"],
                "view_id": view["view_id"],
                "parent_view_id": view["parent_view_id"],
                "available_view_ids": list(frame["views"]),
                "overlay": view["overlay"],
                "target": session["target"],
                "grid": view["grid"],
                "coordinate_space": "physical_screen_pixels",
                "coordinate_origin": "cell_bottom_left",
                "source_rect_absolute": view["source_rect_absolute"],
                "image_size": view["image_size"],
                "zoom_scale_percent": view["zoom_scale_percent"],
                "sampling": {
                    "source_pixels": {"width": view["source_rect_absolute"]["width"], "height": view["source_rect_absolute"]["height"]},
                    "display_pixels_per_screen_pixel": view["zoom_scale_percent"] / 100,
                    "adds_detail": False,
                },
                "performed": performed,
                "interface_state": interface_state or {
                    "changed_before_action": False,
                    "changed_during_action": False,
                    "difference_percent": 0.0,
                    "external_input_detected": False,
                    "external_mouse_input": False,
                    "external_keyboard_input": False,
                    "safe_to_continue": True,
                    "pixel_channel_delta_threshold": PIXEL_CHANNEL_DELTA_THRESHOLD,
                },
            },
            "image_path": str(image_path),
            "warnings": (["网格太小，已隐藏编号并保留格号映射；可减少行列数或使用祖先视图。"]
                         if view["overlay"]["labels_hidden_reason"] else [])
                        + (["当前每个屏幕像素已显示为8×8图像像素；继续递归只缩小观察区域，不增加原始细节。"]
                           if view["zoom_scale_percent"] >= 800 else []),
        }

    def inspect(self, arguments: dict[str, Any]) -> dict[str, Any]:
        action = str(arguments.get("action") or "").strip()
        if "overlay" in arguments and (arguments["overlay"] not in OVERLAY_MODES
                or action not in {"start", "zoom", "view", "refresh", "wait"}):
            raise GuiError("INVALID_ARGUMENT", "overlay仅用于start、zoom、view、refresh、wait，值为labels+lines、lines或none。")
        if action == "list_windows":
            contains = str(arguments.get("contains") or "").casefold()
            limit = max(1, min(int(arguments.get("limit", 100)), 300))
            own_windows = set(self.overlay_windows)
            items = [item for item in visible_windows() if item["hwnd"] not in own_windows]
            if contains:
                items = [item for item in items if contains in item["title"].casefold()]
            return {"ok": True, "summary": f"找到{min(len(items), limit)}个可见窗口。", "data": {"count": min(len(items), limit), "items": items[:limit]}, "warnings": []}
        if action == "start":
            target_type = str(arguments.get("target") or "screen")
            if target_type == "window":
                selected = resolve_window(arguments.get("hwnd"), arguments.get("window_title"))
                if selected["hwnd"] in set(self.overlay_windows):
                    raise GuiError("INVALID_ARGUMENT", "不能把GUI锁覆盖层作为操作目标。")
                if not activate_window(selected["hwnd"]):
                    raise GuiError("WINDOW_ACTIVATION_FAILED", "无法把目标窗口切换到前台，未创建GUI会话。")
                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(selected["hwnd"], ctypes.byref(pid))
                target = {"type": "window", "hwnd": selected["hwnd"], "title": selected["title"], "process_id": int(pid.value)}
            elif target_type == "screen":
                target = {"type": "screen", "monitor": int(arguments.get("monitor", 0))}
            else:
                raise GuiError("INVALID_ARGUMENT", "target必须是screen或window。")
            gui_session_id = f"gui_{uuid4().hex}"
            folder = self._session_dir(gui_session_id)
            folder.mkdir(parents=True, exist_ok=False)
            self.created_gui_sessions.add(gui_session_id)
            session = {
                "schema_version": 1,
                "gui_session_id": gui_session_id,
                "lock_id": self.lock_id,
                "project_id": self.project_id,
                "tiance_session_id": self.session_id,
                "status": "active",
                "created_at": now_iso(),
                "target": target,
                "latest_frame_id": -1,
                "frames": [],
            }
            self._save_session(session)
            try:
                frame, image_path = self._create_frame(
                    session,
                    reason="inspect_start",
                    grid_mode=str(arguments.get("grid_mode") or "auto"),
                    grid_target_cells=int(arguments.get("grid_target_cells", 16)),
                    grid_rows=arguments.get("grid_rows"),
                    grid_cols=arguments.get("grid_cols"),
                    overlay=arguments.get("overlay", DEFAULT_OVERLAY),
                )
            except Exception:
                shutil.rmtree(folder)
                self.created_gui_sessions.discard(gui_session_id)
                raise
            view = frame["views"]["root"]
            return self._result_with_image(summary="已查看当前界面。", session=session, frame=frame, view=view, image_path=image_path)
        gui_session_id = safe_session_id(str(arguments.get("gui_session_id") or ""))
        session = self._load_session(gui_session_id)
        if action == "view":
            frame_id = int(arguments.get("frame_id", -1))
            if frame_id != int(session.get("latest_frame_id", -1)):
                raise GuiError("STALE_FRAME", "只能查看当前最新Frame中的已有View；请使用最新截图。")
            frame = self._frame(session, frame_id)
            view = self._view(frame, str(arguments.get("view_id") or "root"))
            folder = self._session_dir(gui_session_id)
            if "overlay" in arguments:
                with Image.open(folder / view["raw_image"]) as saved:
                    raw = saved.convert("RGB")
                display = raw.resize((view["image_size"]["width"], view["image_size"]["height"]), Image.Resampling.NEAREST)
                rendered = overlay_image(display, view["cells"], view["source_rect_absolute"], arguments["overlay"])
                # Keep previously returned image paths immutable for tool history.
                raw_path = Path(view["raw_image"])
                rendered_path = raw_path.with_name(raw_path.stem.removesuffix("_raw") + "_overlay_" + arguments["overlay"].replace("+", "-") + ".png")
                rendered.save(folder / rendered_path, format="PNG", optimize=True)
                view["overlay_image"] = rendered_path.as_posix()
                view["overlay"] = rendered.info["overlay"]
                if view["view_id"] == "root":
                    session["overlay_mode"] = arguments["overlay"]
                self._save_session(session)
            return self._result_with_image(summary="已返回已有视图；未重新截图或执行输入。", session=session,
                                           frame=frame, view=view, image_path=folder / view["overlay_image"], performed=False)
        if action == "elements":
            return self._inspect_elements(session, arguments)
        if action == "activate":
            return self._activate_session_window(session)
        if action == "close":
            session["status"] = "closed"
            session["closed_at"] = now_iso()
            self._save_session(session)
            shutil.rmtree(self._session_dir(gui_session_id))
            self.created_gui_sessions.discard(gui_session_id)
            return {
                "ok": True,
                "summary": "GUI临时会话已关闭并删除中间文件。",
                "data": {
                    "gui_session_id": gui_session_id,
                    "closed": True,
                    "runtime_idle": not self.created_gui_sessions,
                },
                "warnings": [],
            }
        if action == "zoom":
            frame_id = int(arguments.get("frame_id", -1))
            if frame_id != int(session.get("latest_frame_id", -1)):
                raise GuiError("STALE_FRAME", "只能放大当前最新Frame。")
            frame = self._frame(session, frame_id)
            parent = self._view(frame, str(arguments.get("view_id") or "root"))
            ids = arguments.get("cell_ids")
            if ids is None:
                ids = [int(arguments.get("cell_id", 0))]
            if not isinstance(ids, list) or not ids or len(set(ids)) != len(ids):
                raise GuiError("INVALID_CELL_SELECTION", "请选择不重复的网格编号。")
            selected = [self._cell(parent, int(cell_id)) for cell_id in ids]
            rows = [cell["row"] for cell in selected]
            cols = [cell["column"] for cell in selected]
            if len(selected) != (max(rows) - min(rows) + 1) * (max(cols) - min(cols) + 1):
                raise GuiError("NON_RECTANGULAR_SELECTION", "所选格子必须组成连续、无缺口的完整矩形。")
            rects = [cell["rect_absolute"] for cell in selected]
            left, top = min(r["left"] for r in rects), min(r["top"] for r in rects)
            cell_rect = {"left": left, "top": top,
                         "width": max(r["left"] + r["width"] for r in rects) - left,
                         "height": max(r["top"] + r["height"] for r in rects) - top}
            folder = self._session_dir(gui_session_id)
            parent_raw = Image.open(folder / parent["raw_image"]).convert("RGB")
            parent_rect = parent["source_rect_absolute"]
            local = (
                cell_rect["left"] - parent_rect["left"],
                cell_rect["top"] - parent_rect["top"],
                cell_rect["left"] - parent_rect["left"] + cell_rect["width"],
                cell_rect["top"] - parent_rect["top"] + cell_rect["height"],
            )
            cropped = parent_raw.crop(local)
            selection_id = "-".join(str(value) for value in sorted(ids))
            view_id = selection_id if parent["view_id"] == "root" else f"{parent['view_id']}/{selection_id}"
            if view_id in frame["views"]:
                raise GuiError("VIEW_ALREADY_EXISTS", "该区域已经放大过，请直接使用已有View。")
            view = self._create_view(
                folder=folder,
                frame_id=frame_id,
                view_id=view_id,
                raw=cropped,
                source_rect=cell_rect,
                grid_mode=str(arguments.get("grid_mode") or "auto"),
                grid_target_cells=int(arguments.get("grid_target_cells", 16)),
                grid_rows=arguments.get("grid_rows"),
                grid_cols=arguments.get("grid_cols"),
                zoom_scale_percent=int(arguments.get("zoom_scale_percent", DEFAULT_ZOOM_SCALE_PERCENT)),
                overlay=arguments.get("overlay", parent["overlay"]["requested"]),
                parent_view_id=parent["view_id"],
            )
            frame["views"][view_id] = view
            self._save_session(session)
            return self._result_with_image(summary="已放大指定界面区域。", session=session, frame=frame, view=view, image_path=folder / view["overlay_image"])
        if action in {"refresh", "wait"}:
            previous = self._frame(session, int(session["latest_frame_id"]))
            previous_root = previous["views"]["root"]
            previous_raw = Image.open(self._session_dir(gui_session_id) / previous_root["raw_image"]).convert("RGB")
            if action == "wait":
                mode = str(arguments.get("mode") or "stable")
                threshold = float(arguments.get("change_threshold_percent", 0.5))
                timeout_ms = max(100, min(int(arguments.get("timeout_ms", 5000)), 30000))
                interval_ms = max(50, min(int(arguments.get("interval_ms", 250)), 2000))
                stable_checks = max(1, min(int(arguments.get("stable_checks", 2)), 10))
                deadline = time.monotonic() + timeout_ms / 1000
                matched = False
                samples = 0
                stable_count = 0
                reference = previous_raw
                raw, rect = self._capture_target(session["target"])
                difference = image_difference_percent(reference, raw)
                while time.monotonic() < deadline:
                    samples += 1
                    if mode == "change" and difference >= threshold:
                        matched = True
                        break
                    if mode == "stable":
                        stable_count = stable_count + 1 if difference < threshold else 0
                        if stable_count >= stable_checks:
                            matched = True
                            break
                    reference = raw
                    self._interruptible_sleep(interval_ms / 1000)
                    raw, rect = self._capture_target(session["target"])
                    difference = image_difference_percent(reference, raw)
                reason = f"wait_{mode}_{'matched' if matched else 'timeout'}"
            else:
                raw, rect = self._capture_target(session["target"])
                difference = image_difference_percent(previous_raw, raw)
                matched = True
                samples = 1
                reason = "inspect_refresh"
            frame, image_path = self._create_frame(session, reason=reason, raw=raw, source_rect=rect,
                                                   **{key: arguments[key] for key in ("grid_mode", "grid_target_cells", "grid_rows", "grid_cols", "overlay") if key in arguments})
            view = frame["views"]["root"]
            result = self._result_with_image(summary="已返回最新界面。", session=session, frame=frame, view=view, image_path=image_path)
            result["data"]["difference_from_previous_percent"] = difference
            result["data"]["wait_matched"] = matched
            result["data"]["samples"] = samples
            return result
        raise GuiError("INVALID_ARGUMENT", f"不支持的查看操作：{action}")


    def _activate_session_window(self, session: dict[str, Any]) -> dict[str, Any]:
        target = session["target"]
        if target.get("type") != "window":
            raise GuiError("WINDOW_TARGET_REQUIRED", "activate只用于窗口目标；请先用start指定目标窗口。")
        hwnd = int(target["hwnd"])
        pid = wintypes.DWORD()
        if not user32.IsWindow(hwnd) or not user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid)):
            raise GuiError("WINDOW_NOT_AVAILABLE", "原目标窗口已关闭，请重新选择窗口。")
        if not target.get("process_id") or int(pid.value) != target["process_id"]:
            raise GuiError("WINDOW_IDENTITY_CHANGED", "原窗口进程已变化或缺少身份依据，请重新start查看窗口。")
        if not activate_window(hwnd):
            raise GuiError("WINDOW_ACTIVATION_FAILED", "无法把原目标窗口切到前台，未继续操作。")
        raw, rect = self._capture_target(target)
        if self.cancel_event.is_set():
            raise GuiError("GUI_RUNTIME_STOPPED", "界面锁已退出，未继续操作。")
        if int(user32.GetForegroundWindow() or 0) != hwnd:
            raise GuiError("TARGET_NOT_FOREGROUND", "截图时目标窗口再次失去前台焦点，请重新观察。")
        frame, path = self._create_frame(session, reason="target_window_activated", raw=raw, source_rect=rect)
        return self._result_with_image(summary="已激活原目标窗口并返回新Frame；请依据新图操作，旧坐标和预览已失效。",
                                       session=session, frame=frame, view=frame["views"]["root"], image_path=path)

    def _uia_query(self, hwnd: int, runtime_ids: list[str] | None = None, **options: Any) -> list[dict[str, Any]]:
        script = Path(__file__).with_name("uia_bridge.ps1")
        request = {"hwnd": hwnd, "runtime_ids": runtime_ids or [], "operation": "inspect", **options}
        process = subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", creationflags=0x08000000,
        )
        deadline = time.monotonic() + 10  # UIA query/action time budget, exposed in tool documentation.
        first = True
        try:
            while True:
                if self.cancel_event.is_set():
                    raise GuiError("GUI_RUNTIME_STOPPED", "GUI操作已取消。")
                try:
                    output, _error = process.communicate(json.dumps(request) if first else None, timeout=0.1)
                    break
                except subprocess.TimeoutExpired:
                    first = False
                    if time.monotonic() >= deadline:
                        raise GuiError("UIA_TIMEOUT", "读取或操作控件超过10秒，未返回不完整控件列表。")
            try:
                result = json.loads(output.lstrip("\ufeff"))
            except ValueError as exc:
                raise GuiError("UIA_UNAVAILABLE", "Windows UIAutomation 未返回有效结果。") from exc
            if not result.get("ok"):
                raise GuiError("UIA_UNAVAILABLE", "控件读取或操作失败，请重新查看目标窗口。")
            return result["elements"]
        finally:
            if process.poll() is None:
                process.kill()
            process.communicate()

    def _require_frame(self, session: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
        if arguments.get("frame_id") != session["latest_frame_id"]:
            raise GuiError("STALE_FRAME", "必须提供AI实际查看过的最新frame_id，请重新查看界面。")
        return self._frame(session, int(arguments["frame_id"]))

    def _uia_element(self, session: dict[str, Any], element_id: str, *,
                     expected: dict[str, Any] | None = None, require_focus: bool = False) -> dict[str, Any]:
        frame = self._frame(session, session["latest_frame_id"])
        saved = frame.get("elements", {}).get(element_id)
        if saved is None:
            raise GuiError("UIA_ELEMENT_UNKNOWN", "此控件不属于当前Frame，请先读取控件列表。")
        hwnd = int(saved["hwnd"])
        if int(user32.GetForegroundWindow() or 0) != hwnd:
            raise GuiError("TARGET_NOT_FOREGROUND", "控件所属窗口已失去前台焦点。")
        matches = self._uia_query(hwnd, [saved["runtime_id"]])
        if len(matches) != 1:
            raise GuiError("UIA_ELEMENT_STALE", "原控件已经不存在，请重新查看。")
        live = matches[0]
        for key in ("runtime_id", "process_id", "hwnd", "name", "automation_id", "control_type", "class_name"):
            if live.get(key) != saved.get(key):
                raise GuiError("UIA_ELEMENT_CHANGED", "控件身份或名称发生变化，请重新查看。")
        if not live["enabled"] or live["offscreen"]:
            raise GuiError("UIA_ELEMENT_UNAVAILABLE", "目标控件不可用或不在可见区域。")
        if require_focus and not live["focused"]:
            raise GuiError("UIA_FOCUS_CHANGED", "焦点不在指定输入控件，本次未输入。")
        for key, value in (expected or {}).items():
            if key != "element_id" and live.get(key) != value:
                raise GuiError("UIA_CONDITION_FAILED", f"控件的{key}不符合预期，本次未继续。")
        return live

    def _check_conditions(self, session: dict[str, Any], conditions: list[dict[str, Any]]) -> None:
        for condition in conditions:
            self._uia_element(session, str(condition["element_id"]), expected=condition)

    def _inspect_elements(self, session: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
        frame = self._require_frame(session, arguments)
        hwnd = int(session["target"].get("hwnd") or user32.GetForegroundWindow())
        if int(user32.GetForegroundWindow() or 0) != hwnd:
            raise GuiError("TARGET_NOT_FOREGROUND", "请先查看并激活目标窗口。")
        if "element_inventory" not in frame:
            frame["element_inventory"] = self._uia_query(hwnd)
            frame["element_window"] = hwnd
        if frame["element_window"] != hwnd:
            raise GuiError("UIA_ELEMENT_CHANGED", "控件列表所属窗口发生变化，请刷新Frame。")
        records = frame["element_inventory"]  # Stable snapshot across pages; actions revalidate live controls.
        query = str(arguments.get("contains") or "").casefold()
        matches = [r for r in records if query in str(r["name"]).casefold()]
        offset, limit = int(arguments.get("offset", 0)), int(arguments.get("limit", 100))
        if offset < 0 or limit < 1:
            raise GuiError("INVALID_ARGUMENT", "offset不得为负，limit必须大于0。")
        page = matches[offset:offset + limit]  # Explicit presentation page; reports total/next_offset.
        saved = frame.setdefault("elements", {})
        output = []
        for record in page:
            identity = json.dumps([record["hwnd"], record["process_id"], record["runtime_id"]])
            element_id = "uia_" + hashlib.sha256(identity.encode()).hexdigest()[:24]
            if element_id in saved and any(saved[element_id].get(k) != record.get(k) for k in ("name", "automation_id", "control_type", "class_name")):
                raise GuiError("UIA_ELEMENT_CHANGED", "分页期间控件发生变化，请刷新Frame后重读。")
            saved.setdefault(element_id, record)
            output.append({"element_id": element_id, **record})
        self._save_session(session)
        next_offset = offset + len(page)
        return {"ok": True, "summary": f"返回{len(page)}个控件，共{len(matches)}个匹配项。",
                "data": {"gui_session_id": session["gui_session_id"], "frame_id": frame["frame_id"],
                         "elements": output, "total": len(matches),
                         "complete": next_offset >= len(matches),
                         "next_offset": next_offset if next_offset < len(matches) else None}, "warnings": []}

    def _resolve_point(self, session: dict[str, Any], arguments: dict[str, Any]) -> tuple[dict[str, Any], int, int]:
        frame_id = int(arguments.get("frame_id", -1))
        if frame_id != int(session.get("latest_frame_id", -1)):
            raise GuiError("STALE_FRAME", "GUI操作必须使用最新Frame。")
        frame = self._frame(session, frame_id)
        if arguments.get("element_id"):
            element = self._uia_element(session, str(arguments["element_id"]))
            rect = element["rect"]
            if rect["width"] <= 0 or rect["height"] <= 0:
                raise GuiError("UIA_ELEMENT_UNAVAILABLE", "控件没有可点击区域。")
            return frame, round(rect["left"] + rect["width"] / 2), round(rect["top"] + rect["height"] / 2)
        view = self._view(frame, str(arguments.get("view_id") or "root"))
        cell = self._cell(view, int(arguments.get("cell_id", 0)))
        x_ratio = float(arguments.get("x", 0.5))
        y_ratio = float(arguments.get("y", 0.5))
        if not 0 <= x_ratio <= 1 or not 0 <= y_ratio <= 1:
            raise GuiError("INVALID_ARGUMENT", "x和y必须在0到1之间。")
        rect = cell["rect_absolute"]
        x = int(rect["left"] + round(x_ratio * max(0, rect["width"] - 1)))
        y = int(rect["top"] + round((1 - y_ratio) * max(0, rect["height"] - 1)))
        if session["target"]["type"] == "window":
            current = self._target_rect(session["target"])
            captured = frame["capture_rect"]
            if current["width"] != captured["width"] or current["height"] != captured["height"]:
                raise GuiError("WINDOW_GEOMETRY_CHANGED", "目标窗口尺寸已经变化，请刷新界面后重试。")
            x += current["left"] - captured["left"]
            y += current["top"] - captured["top"]
        return frame, x, y

    def _preflight(self, session: dict[str, Any], points: list[dict[str, Any]] | None = None, *, compare_pixels: bool = True) -> tuple[dict[str, Any], Image.Image, dict[str, int], float]:
        target = session["target"]
        if target["type"] == "window" and int(user32.GetForegroundWindow() or 0) != int(target["hwnd"]):
            raise GuiError("TARGET_NOT_FOREGROUND", "目标窗口已失去前台焦点，本次未执行；请重新查看目标窗口。")
        frame = self._frame(session, int(session["latest_frame_id"]))
        current, rect = self._capture_target(session["target"])
        captured = frame["capture_rect"]
        if rect["width"] != captured["width"] or rect["height"] != captured["height"] or (target["type"] == "screen" and rect != captured):
            raise GuiError("TARGET_GEOMETRY_CHANGED", "屏幕或目标窗口尺寸已经变化，请刷新界面后重试。")
        if not compare_pixels:
            return frame, current, rect, 0.0
        root = frame["views"]["root"]
        previous = Image.open(self._session_dir(session["gui_session_id"]) / root["raw_image"]).convert("RGB")
        if points:
            differences = []
            for point in points:
                view = self._view(frame, str(point.get("view_id") or "root"))
                cell = self._cell(view, int(point.get("cell_id", 0)))["rect_absolute"]
                left, top = cell["left"] - captured["left"], cell["top"] - captured["top"]
                box = (left, top, left + cell["width"], top + cell["height"])
                differences.append(image_difference_percent(previous.crop(box), current.crop(box)))
            difference = max(differences)
        else:
            difference = image_difference_percent(previous, current)
        return frame, current, rect, difference

    def _check_drag_origin(self, frame: dict[str, Any], x: int, y: int) -> dict[str, Any]:
        if self.cancel_event.is_set():
            raise GuiError("GUI_RUNTIME_STOPPED", "GUI后台运行器已经退出。")
        expected = window_at_point(frame.get("drag_windows", []), x, y)
        if expected is None or not expected["pid"] or not expected["thread_id"]:
            raise GuiError("DRAG_ORIGIN_UNCONFIRMED", "截图中没有可确认的拖动起点窗口，请刷新后重新定位。")
        current = drag_window_snapshot(self.overlay_windows)
        actual = next((window for window in current if window["hwnd"] == expected["hwnd"]), None)
        if actual is None or any(actual[key] != expected[key] for key in ("pid", "thread_id", "rect")):
            raise GuiError("DRAG_ORIGIN_CHANGED", "拖动起点窗口已关闭、移动、缩放或身份变化，本次未拖动；请刷新后重新定位。")
        if window_at_point(current, x, y) != actual:
            raise GuiError("DRAG_ORIGIN_OCCLUDED", "拖动起点已被其他窗口遮挡，本次未拖动；请刷新后重新定位。")
        hit = user32.WindowFromPoint(POINT(x, y))
        root = int(user32.GetAncestor(hit, 2) or 0) if hit else 0  # GA_ROOT
        if root != expected["hwnd"]:
            raise GuiError("DRAG_ORIGIN_UNCONFIRMED", "起点实际命中的窗口与截图依据不一致，本次未拖动；请刷新后重新定位。")
        return expected

    def _preview_coordinate(
        self,
        *,
        session: dict[str, Any],
        frame: dict[str, Any],
        arguments: dict[str, Any],
        screen_x: int,
        screen_y: int,
        difference: float,
        mouse_before: int,
        keyboard_before: int,
        end_point: tuple[int, int] | None = None,
    ) -> dict[str, Any]:
        view = self._view(frame, str(arguments.get("view_id") or "root"))
        if end_point is not None and arguments["to"].get("view_id", "root") != view["view_id"]:
            view = frame["views"]["root"]
        source_rect = view["source_rect_absolute"]
        captured_x, captured_y = screen_x, screen_y
        if session["target"]["type"] == "window":
            current_rect = self._target_rect(session["target"])
            captured_rect = frame["capture_rect"]
            captured_x -= current_rect["left"] - captured_rect["left"]
            captured_y -= current_rect["top"] - captured_rect["top"]
        source_x = captured_x - int(source_rect["left"])
        source_y = captured_y - int(source_rect["top"])
        folder = self._session_dir(session["gui_session_id"])
        image = Image.open(folder / view["overlay_image"]).convert("RGB")
        if not 0 <= source_x < source_rect["width"] or not 0 <= source_y < source_rect["height"]:
            raise GuiError("COORDINATE_PREVIEW_FAILED", "选定坐标不在当前View内，未生成预览图。")
        # 标在屏幕源像素对应的显示像素中心，不将显示放大倍数带回点击坐标。
        local_x = min(image.width - 1, int((source_x + 0.5) * image.width / source_rect["width"]))
        local_y = min(image.height - 1, int((source_y + 0.5) * image.height / source_rect["height"]))
        preview = image.copy()
        draw = ImageDraw.Draw(preview)
        radius = max(6, min(14, round(min(preview.size) / 100)))
        outline = max(2, radius // 3)
        draw.ellipse(
            (local_x - radius - outline, local_y - radius - outline, local_x + radius + outline, local_y + radius + outline),
            fill=(255, 255, 255),
        )
        draw.ellipse(
            (local_x - radius, local_y - radius, local_x + radius, local_y + radius),
            fill=COORDINATE_PREVIEW_COLOR,
        )
        end_marker = None
        if end_point is not None:
            # 两端使用同一图片坐标空间；不同放大区域的拖动回到root展示完整路径。
            end_source_x = source_x + end_point[0] - screen_x
            end_source_y = source_y + end_point[1] - screen_y
            end_local_x = min(image.width - 1, int((end_source_x + 0.5) * image.width / source_rect["width"]))
            end_local_y = min(image.height - 1, int((end_source_y + 0.5) * image.height / source_rect["height"]))
            draw.line((local_x, local_y, end_local_x, end_local_y), fill="#FFE66D", width=3)
            draw.ellipse((end_local_x - radius, end_local_y - radius, end_local_x + radius, end_local_y + radius), fill="#00DCFF", outline="white", width=2)
            draw.text((local_x + radius, local_y), "START", fill="white", stroke_width=1, stroke_fill="black")
            draw.text((end_local_x + radius, end_local_y), "END", fill="white", stroke_width=1, stroke_fill="black")
            end_marker = {"color": "#00DCFF", "center_x": end_local_x, "center_y": end_local_y}
        elif arguments.get("action") == "scroll":
            dx, dy = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}[arguments["direction"]]
            arrow_x = max(4, min(image.width - 5, local_x + dx * radius * 4))
            arrow_y = max(4, min(image.height - 5, local_y + dy * radius * 4))
            draw.line((local_x, local_y, arrow_x, arrow_y), fill="#FFE66D", width=3)
            draw.polygon([(arrow_x, arrow_y), (arrow_x - dx * 8 + dy * 5, arrow_y - dy * 8 - dx * 5), (arrow_x - dx * 8 - dy * 5, arrow_y - dy * 8 + dx * 5)], fill="#FFE66D")
        if end_point is not None or arguments.get("action") == "scroll":
            draw.ellipse((local_x - radius, local_y - radius, local_x + radius, local_y + radius), fill=COORDINATE_PREVIEW_COLOR, outline="white", width=2)
        safe_view = "root" if view["view_id"] == "root" else "zoom_" + re.sub(r"[^0-9A-Za-z_-]", "_", view["view_id"])
        preview_path = folder / f"frame_{int(frame['frame_id']):03d}" / f"{safe_view}_point_{uuid4().hex[:8]}.png"
        preview.save(preview_path, format="PNG", optimize=True)
        external_mouse = self.external_mouse_events > mouse_before
        external_keyboard = self.external_keyboard_events > keyboard_before
        state = {
            "changed_before_action": False,
            "changed_during_action": False,
            "difference_percent": difference,
            "external_input_detected": external_mouse or external_keyboard,
            "external_mouse_input": external_mouse,
            "external_keyboard_input": external_keyboard,
            "safe_to_continue": not (external_mouse or external_keyboard or self.cancel_event.is_set()),
            "change_source": "external_input_detected" if external_mouse or external_keyboard else "none",
            "pixel_channel_delta_threshold": PIXEL_CHANNEL_DELTA_THRESHOLD,
        }
        result = self._result_with_image(
            summary="已预览选定坐标，未移动鼠标或执行点击。",
            session=session,
            frame=frame,
            view=view,
            image_path=preview_path,
            interface_state=state,
            performed=False,
        )
        result["data"].update({
            "previewed": True,
            "selected_coordinate": {
                "cell_id": int(arguments.get("cell_id", 0)),
                "x": float(arguments.get("x", 0.5)),
                "y": float(arguments.get("y", 0.5)),
                "screen_x": screen_x,
                "screen_y": screen_y,
                "coordinate_origin": "cell_bottom_left",
            },
            "marker": {"color": COORDINATE_PREVIEW_COLOR_HEX, "center_x": local_x, "center_y": local_y},
        })
        if end_marker is not None:
            result["data"]["end_marker"] = end_marker
            result["data"]["selected_end_coordinate"] = {"screen_x": end_point[0], "screen_y": end_point[1]}
        return result

    def _mouse_arguments(self, arguments: dict[str, Any], action: str) -> dict[str, Any]:
        if action not in MOUSE_ACTIONS:
            raise GuiError("INVALID_ARGUMENT", "preview必须明确提供preview_action鼠标动作。")
        required = (("gui_session_id", "frame_id", "element_id") if arguments.get("element_id")
                    else ("gui_session_id", "frame_id", "view_id", "cell_id", "x", "y"))
        if any(key not in arguments for key in required) or (action == "drag" and not isinstance(arguments.get("to"), dict)):
            raise GuiError("INVALID_ARGUMENT", "鼠标操作缺少坐标，或拖动缺少to终点。")
        resolved = {key: arguments[key] for key in required}
        resolved["action"] = action
        resolved["expected_elements"] = arguments.get("expected_elements", [])
        for key in (*MOUSE_ACTION_OPTIONS[action], "change_check_scope", "change_threshold_percent"):
            resolved[key] = arguments.get(key, MOUSE_ACTION_DEFAULTS[key])
        if action == "drag":
            resolved["to"] = arguments["to"]
        resolved["screenshot_delay_seconds"] = self._screenshot_delay(arguments)
        # 保存有效参数与已解析默认值，后续执行不接受参数覆盖。
        return json.loads(json.dumps(resolved))

    def _save_mouse_preview(self, session: dict[str, Any], arguments: dict[str, Any], result: dict[str, Any], rect: dict[str, int], point: tuple[int, int], end_point: tuple[int, int] | None) -> dict[str, Any]:
        if not result["data"]["interface_state"]["safe_to_continue"]:
            raise GuiError("PREVIEW_INTERRUPTED", "预览期间检测到外部输入或解锁，未建立可执行预览。")
        preview_id = f"preview_{session['gui_session_id'][4:]}_{uuid4().hex}"
        operation = str(arguments["action"])
        labels = {"move": "移动", "click": "点击", "drag": "拖动", "scroll": "滚动", "mouse_down": "按下鼠标", "mouse_up": "抬起鼠标"}
        detail = ""
        if operation == "click":
            detail = f"（{arguments['button']}，{arguments['clicks']}次，每次按住{arguments['click_hold_ms']}毫秒）"
        elif operation == "scroll":
            detail = f"（{arguments['direction']}，{arguments['notches']}格）"
        elif operation == "drag":
            detail = "（粉色起点、蓝色终点、黄色路径）"
        result["summary"] = f"已预览{labels[operation]}{detail}，尚未执行。确认后用execute_preview和preview_id执行。"
        result["data"].update({"preview_id": preview_id, "preview_status": "pending", "operation": arguments})
        record = {
            "preview_id": preview_id, "lock_id": self.lock_id, "status": "pending", "created_at": now_iso(),
            "arguments": arguments, "capture_rect": rect, "screen_point": list(point),
            "end_screen_point": list(end_point) if end_point is not None else None,
        }
        atomic_json(self._session_dir(session["gui_session_id"]) / "previews" / f"{preview_id}.json", record)
        return result

    def _execute_preview(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if set(arguments) != {"action", "preview_id"}:
            raise GuiError("INVALID_ARGUMENT", "execute_preview只接受action和preview_id，不允许覆盖已预览的操作参数。")
        preview_id = str(arguments.get("preview_id") or "")
        match = PREVIEW_ID_PATTERN.fullmatch(preview_id)
        if not match:
            raise GuiError("PREVIEW_NOT_FOUND", "预览编号无效。")
        session = self._load_session(f"gui_{match[1]}")
        path = self._session_dir(session["gui_session_id"]) / "previews" / f"{preview_id}.json"
        if not path.is_file():
            raise GuiError("PREVIEW_NOT_FOUND", "预览不存在或已随GUI会话清理。")
        record = read_json(path)
        if record.get("preview_id") != preview_id or record.get("lock_id") != self.lock_id or record["arguments"]["gui_session_id"] != session["gui_session_id"]:
            raise GuiError("PREVIEW_NOT_FOUND", "预览不属于当前界面锁和GUI会话。")
        if record["status"] != "pending":
            if isinstance(record.get("result"), dict):
                result = record["result"]
                result["data"]["preview_reused"] = True
                return result
            raise GuiError("PREVIEW_ALREADY_CLAIMED", "该编号已开始执行但未留下完整结果，不会再次执行；请查看当前界面。", {"preview_id": preview_id, "execution_status": "unknown"})
        # RPC service_lock覆盖领取、执行和结算；先落盘领取，失败或连接重试均不能重复输入。
        record.update({"status": "executing", "started_at": now_iso(), "input_completed": False})
        atomic_json(path, record)
        sent_before = self.input_events_sent
        try:
            result = self.mouse(record["arguments"], preview_record=record)
            status = "executed" if result["data"]["performed"] else "expired"
        except Exception as exc:
            sent = self.input_events_sent - sent_before
            execution_status = "completed" if record["input_completed"] else "partial" if sent else "not_started"
            code = exc.code if isinstance(exc, GuiError) else "GUI_INTERNAL_ERROR"
            details = dict(exc.details) if isinstance(exc, GuiError) else {}
            details.update({"execution_status": execution_status, "input_events_sent": sent})
            result = {"ok": False, "error": str(exc), "error_info": {"code": code, "message": str(exc), "details": details}, "warnings": [], "data": {"gui_session_id": session["gui_session_id"], "performed": bool(sent)}}
            # 失败也尽可能返回当前画面，但用户已退出时不再抓屏。
            if not self.cancel_event.is_set():
                try:
                    current_session = self._load_session(session["gui_session_id"])
                    frame, image_path = self._create_frame(current_session, reason="preview_execution_failed")
                    latest = self._result_with_image(summary="", session=current_session, frame=frame, view=frame["views"]["root"], image_path=image_path, performed=bool(sent))
                    result["data"] = latest["data"]
                    result["data"]["interface_state"]["safe_to_continue"] = False
                    result["image_path"] = latest["image_path"]
                except Exception as capture_error:
                    result["warnings"].append(f"未取得操作后的截图：{capture_error}")
            else:
                result["warnings"].append("界面锁已退出，未继续截图。")
            if not self.cancel_event.is_set():
                result["warnings"].append("请调用gui_inspect refresh核对当前界面后再决定下一步；同一预览编号不会再次执行。")
            result["data"].update(details)
            status = "expired" if not sent else "failed"
        result["data"].update({"preview_id": preview_id, "preview_status": status, "preview_reused": False})
        result["data"].setdefault("execution_status", "completed" if record["input_completed"] else "not_started")
        record.update({"status": status, "finished_at": now_iso(), "result": result})
        atomic_json(path, record)
        return result

    def _blocked_changed_result(self, session: dict[str, Any], raw: Image.Image, rect: dict[str, int], difference: float, scope: str = "frame") -> dict[str, Any]:
        frame, image_path = self._create_frame(session, reason="interface_changed_before_action", raw=raw, source_rect=rect)
        view = frame["views"]["root"]
        state = {
            "changed_before_action": True,
            "changed_during_action": False,
            "difference_percent": difference,
            "change_check_scope": scope,
            "external_input_detected": False,
            "external_mouse_input": False,
            "external_keyboard_input": False,
            "safe_to_continue": False,
            "change_source": "application_user_or_unknown",
            "pixel_channel_delta_threshold": PIXEL_CHANNEL_DELTA_THRESHOLD,
        }
        return self._result_with_image(
            summary="操作前界面已经变化，本次未执行；已返回最新界面。",
            session=session,
            frame=frame,
            view=view,
            image_path=image_path,
            interface_state=state,
            performed=False,
        )

    @contextmanager
    def _ai_input(self):
        if self.cancel_event.is_set():
            raise GuiError("GUI_RUNTIME_STOPPED", "GUI后台运行器已经退出。")
        mouse_before = self.external_mouse_events
        keyboard_before = self.external_keyboard_events
        try:
            yield mouse_before, keyboard_before
        finally:
            if self.cancel_event.is_set():
                self._release_held_inputs()

    @staticmethod
    def _screenshot_delay(arguments: dict[str, Any]) -> float:
        value = arguments.get("screenshot_delay_seconds", DEFAULT_SCREENSHOT_DELAY_SECONDS)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 30:
            raise GuiError("INVALID_ARGUMENT", "screenshot_delay_seconds必须是0到30秒之间的数字。")
        return float(value)

    def _finish_action(
        self,
        *,
        session: dict[str, Any],
        before_raw: Image.Image,
        mouse_before: int,
        keyboard_before: int,
        action_name: str,
        action_data: dict[str, Any],
        screenshot_delay_seconds: float,
    ) -> dict[str, Any]:
        self._interruptible_sleep(screenshot_delay_seconds)
        raw, rect = self._capture_target(session["target"])
        difference = image_difference_percent(before_raw, raw)
        external_mouse = self.external_mouse_events > mouse_before
        external_keyboard = self.external_keyboard_events > keyboard_before
        frame, image_path = self._create_frame(session, reason=f"after_{action_name}", raw=raw, source_rect=rect)
        view = frame["views"]["root"]
        state = {
            "changed_before_action": False,
            "changed_during_action": difference > 0,
            "difference_percent": difference,
            "external_input_detected": external_mouse or external_keyboard,
            "external_mouse_input": external_mouse,
            "external_keyboard_input": external_keyboard,
            "safe_to_continue": not (external_mouse or external_keyboard or self.cancel_event.is_set()),
            "change_source": "external_input_detected" if external_mouse or external_keyboard else "tool_application_or_unknown",
            "pixel_channel_delta_threshold": PIXEL_CHANNEL_DELTA_THRESHOLD,
        }
        result = self._result_with_image(
            summary=f"GUI {action_name}操作已执行并返回最新界面。",
            session=session,
            frame=frame,
            view=view,
            image_path=image_path,
            interface_state=state,
        )
        result["data"]["screenshot_delay_seconds"] = screenshot_delay_seconds
        result["data"]["action"] = action_data
        return result

    def mouse(self, arguments: dict[str, Any], *, preview_record: dict[str, Any] | None = None) -> dict[str, Any]:
        requested_action = str(arguments.get("action") or "").strip()
        if requested_action == "execute_preview":
            return self._execute_preview(arguments)
        action = str(arguments.get("preview_action") or "") if requested_action == "preview" else requested_action
        arguments = self._mouse_arguments(arguments, action)
        session = self._load_session(str(arguments["gui_session_id"]))
        self._check_conditions(session, arguments.get("expected_elements", []))
        mouse_at_start = self.external_mouse_events
        keyboard_at_start = self.external_keyboard_events
        threshold = float(arguments.get("change_threshold_percent", 0.5))
        scope = str(arguments.get("change_check_scope", "target_cell"))
        if scope not in {"target_cell", "frame"}:
            raise GuiError("INVALID_ARGUMENT", "change_check_scope必须是target_cell或frame。")
        frame, x, y = self._resolve_point(session, arguments)
        end_point = None
        if action == "drag":
            _target_frame, end_x, end_y = self._resolve_point(session, {**arguments["to"], "frame_id": frame["frame_id"]})
            end_point = (end_x, end_y)
        check_scope = "origin_window" if action == "drag" else scope
        _frame, before_raw, rect, difference = self._preflight(session, [arguments] if check_scope == "target_cell" and not arguments.get("element_id") else None, compare_pixels=action != "drag")
        if action == "drag":
            self._check_drag_origin(frame, x, y)
        if preview_record is not None and (
            preview_record["capture_rect"] != rect
            or preview_record["screen_point"] != [x, y]
            or preview_record["end_screen_point"] != (list(end_point) if end_point is not None else None)
        ):
            raise GuiError("PREVIEW_EXPIRED", "预览后窗口位置或坐标映射发生变化，未执行；请重新预览。")
        if action != "drag" and difference >= threshold and not arguments.get("element_id"):
            return self._blocked_changed_result(session, before_raw, rect, difference, check_scope)
        if requested_action == "preview":
            result = self._preview_coordinate(
                session=session,
                frame=frame,
                arguments=arguments,
                screen_x=x,
                screen_y=y,
                difference=difference,
                mouse_before=mouse_at_start,
                keyboard_before=keyboard_at_start,
                end_point=end_point,
            )
            return self._save_mouse_preview(session, arguments, result, rect, (x, y), end_point)
        action_data: dict[str, Any] = {"type": action, "screen_point": {"x": x, "y": y}, "change_check_scope": check_scope}
        with self._ai_input() as counters:
            if action == "move":
                self._mouse_move(x, y, int(arguments.get("duration_ms", 0)))
            elif action == "click":
                modifiers = self._normalize_modifiers(arguments.get("modifiers"))
                click_hold_ms = max(0, min(int(arguments.get("click_hold_ms", DEFAULT_CLICK_HOLD_MS)), 2000))
                with self._hold_modifiers(modifiers):
                    self._mouse_click(x, y, str(arguments.get("button") or "left"), int(arguments.get("clicks", 1)), int(arguments.get("interval_ms", 120)), click_hold_ms)
                action_data.update({"button": str(arguments.get("button") or "left"), "clicks": int(arguments.get("clicks", 1)), "click_hold_ms": click_hold_ms, "modifiers": modifiers})
            elif action == "drag":
                modifiers = self._normalize_modifiers(arguments.get("modifiers"))
                with self._hold_modifiers(modifiers):
                    self._mouse_drag(x, y, end_x, end_y, str(arguments.get("button") or "left"), int(arguments.get("duration_ms", 0)), origin_frame=frame)
                action_data.update({"to": {"x": end_x, "y": end_y}, "button": str(arguments.get("button") or "left"), "modifiers": modifiers})
            elif action == "scroll":
                modifiers = self._normalize_modifiers(arguments.get("modifiers"))
                with self._hold_modifiers(modifiers):
                    self._mouse_scroll(x, y, str(arguments.get("direction") or "down"), int(arguments.get("notches", 3)), int(arguments.get("interval_ms", 120)))
                action_data.update({"direction": str(arguments.get("direction") or "down"), "notches": int(arguments.get("notches", 3)), "modifiers": modifiers})
            elif action == "mouse_down":
                self._mouse_move(x, y, 0)
                button = self._button(arguments.get("button"))
                self._mouse_flag(MOUSE_BUTTON_FLAGS[button][0], button=button)
                action_data["warning"] = "PAIR_WITH_MOUSE_UP"
            elif action == "mouse_up":
                self._mouse_move(x, y, 0)
                button = self._button(arguments.get("button"))
                self._mouse_flag(MOUSE_BUTTON_FLAGS[button][1], button=button)
            else:
                raise GuiError("INVALID_ARGUMENT", f"不支持的鼠标操作：{action}")
        if preview_record is not None:
            preview_record["input_completed"] = True
        return self._finish_action(
            session=session,
            before_raw=before_raw,
            mouse_before=counters[0],
            keyboard_before=counters[1],
            action_name=action,
            action_data=action_data,
            screenshot_delay_seconds=arguments["screenshot_delay_seconds"],
        )

    def _check_keyboard_target(self, session: dict[str, Any], arguments: dict[str, Any], focus: int) -> None:
        self._check_conditions(session, arguments.get("expected_elements", []))
        if arguments.get("element_id"):
            self._uia_element(session, str(arguments["element_id"]),
                              require_focus=arguments.get("action", arguments.get("type")) != "set_value")
        elif self._native_focus() != focus:
            raise GuiError("GUI_FOCUS_CHANGED", "输入焦点与已观察状态不一致，未执行键盘操作。")

    def _set_element_value(self, session: dict[str, Any], arguments: dict[str, Any]) -> None:
        if not arguments.get("element_id"):
            raise GuiError("INVALID_ARGUMENT", "set_value必须指定element_id。")
        target = self._uia_element(session, str(arguments["element_id"]))
        value = str(arguments.get("text", ""))
        try:
            result = self._uia_query(int(target["hwnd"]), [target["runtime_id"]], operation="set_value",
                                     value=value, expected_name=target["name"], expected_process_id=target["process_id"])
        except GuiError as exc:
            exc.details["execution_status"] = "unknown"
            raise
        if len(result) != 1 or not result[0].get("performed"):
            raise GuiError("UIA_VALUE_NOT_SET", "目标控件未执行赋值，请重新查看。")
        # ValuePattern invocation is an external input, and must count for partial execution.
        self.input_events_sent += 1
        self._uia_element(session, str(arguments["element_id"]), expected={"value": value})

    def keyboard(self, arguments: dict[str, Any]) -> dict[str, Any]:
        delay = self._screenshot_delay(arguments)
        session = self._load_session(str(arguments.get("gui_session_id") or ""))
        frame = self._require_frame(session, arguments)
        self._check_keyboard_target(session, arguments, int(frame["focus_window"]))
        threshold = float(arguments.get("change_threshold_percent", 0.5))
        _frame, before_raw, rect, difference = self._preflight(session)
        if difference >= threshold and not arguments.get("element_id"):
            return self._blocked_changed_result(session, before_raw, rect, difference)
        action = str(arguments.get("action") or "").strip()
        action_data: dict[str, Any] = {"type": action}
        with self._ai_input() as counters:
            if action == "set_value":
                self._set_element_value(session, arguments)
                action_data["character_count"] = len(str(arguments.get("text", "")))
            elif action == "type_text":
                text = str(arguments.get("text") or "")
                self._type_text(text, int(arguments.get("interval_ms", 20)))
                action_data["character_count"] = len(text)
            elif action == "press_key":
                key = str(arguments.get("key") or "")
                presses = int(arguments.get("presses", 1))
                self._press_key(key, presses, int(arguments.get("interval_ms", 20)))
                action_data.update({"key": key, "presses": presses})
            elif action == "hotkey":
                keys = arguments.get("keys")
                if not isinstance(keys, list):
                    raise GuiError("INVALID_ARGUMENT", "hotkey必须提供keys数组。")
                self._hotkey([str(item) for item in keys], int(arguments.get("hold_ms", 0)))
                action_data["keys"] = keys
            else:
                raise GuiError("INVALID_ARGUMENT", f"不支持的键盘操作：{action}")
        return self._finish_action(
            session=session,
            before_raw=before_raw,
            mouse_before=counters[0],
            keyboard_before=counters[1],
            action_name=action,
            action_data=action_data,
            screenshot_delay_seconds=delay,
        )

    def batch(self, arguments: dict[str, Any]) -> dict[str, Any]:
        delay = self._screenshot_delay(arguments)
        session = self._load_session(str(arguments.get("gui_session_id") or ""))
        frame = self._require_frame(session, arguments)
        threshold = float(arguments.get("change_threshold_percent", 0.5))
        actions = arguments.get("actions")
        if not isinstance(actions, list) or not 1 <= len(actions) <= 50:
            raise GuiError("INVALID_ARGUMENT", "actions必须包含1到50个动作。")
        if any(not isinstance(item, dict) for item in actions):
            raise GuiError("INVALID_ARGUMENT", "所有批量动作必须为对象。")
        needs_pixels = any(not item.get("element_id") for item in actions if item.get("type") not in {"wait", "drag"})
        _frame, before_raw, rect, difference = self._preflight(session, compare_pixels=needs_pixels)
        # Coordinate scripts still require the initial observed pixels. UIA-only scripts
        # validate element identity and explicit conditions instead of unrelated animation.
        if difference >= threshold and needs_pixels:
            return self._blocked_changed_result(session, before_raw, rect, difference)
        results: list[dict[str, Any]] = []
        focus = int(frame["focus_window"])
        with self._ai_input() as counters:
            for index, item in enumerate(actions):
                inputs_before = self.input_events_sent
                try:
                    if self.cancel_event.is_set():
                        raise GuiError("GUI_RUNTIME_STOPPED", "GUI后台运行器已经退出。")
                    self._check_conditions(session, item.get("expected_elements", []))
                    kind = str(item.get("type") or "")
                    if kind in {"type_text", "press_key", "hotkey", "set_value"}:
                        self._check_keyboard_target(session, item, focus)
                    elif kind != "wait":
                        self._require_frame(session, item)
                        if kind == "drag":
                            self._preflight(session, compare_pixels=False)
                        elif item.get("element_id"):
                            self._uia_element(session, str(item["element_id"]))
                        else:
                            _, raw_now, rect_now, changed = self._preflight(session, [item])
                            if changed >= threshold:
                                raise GuiError("GUI_BATCH_TARGET_CHANGED", "后续坐标目标区域已变化，请重新查看后再操作。")
                    result = self._execute_batch_item(session, item)
                    self._check_conditions(session, item.get("postconditions", []))
                    results.append(result)
                    focus = self._native_focus()
                except Exception as error:
                    exc = error if isinstance(error, GuiError) else GuiError("GUI_BATCH_FAILED", "批量操作失败，后续动作已停止。")
                    exc.details.update({"completed_actions": len(results), "failed_action_index": index,
                                        "execution_status": exc.details.get("execution_status", "partial" if results or self.input_events_sent > inputs_before else "not_started"),
                                        "action_results": results})
                    raise exc
        return self._finish_action(
            session=session, before_raw=before_raw, mouse_before=counters[0], keyboard_before=counters[1],
            action_name="batch", action_data={"type": "batch", "actions": results}, screenshot_delay_seconds=delay,
        )

    def _execute_batch_item(self, session: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
        action = str(item.get("type") or "")
        if action in {"move", "click", "scroll", "mouse_down", "mouse_up"}:
            _frame, x, y = self._resolve_point(session, item)
            if action == "move":
                self._mouse_move(x, y, int(item.get("duration_ms", 0)))
            elif action == "click":
                click_hold_ms = max(0, min(int(item.get("click_hold_ms", DEFAULT_CLICK_HOLD_MS)), 2000))
                with self._hold_modifiers(self._normalize_modifiers(item.get("modifiers"))):
                    self._mouse_click(x, y, str(item.get("button") or "left"), int(item.get("clicks", 1)), int(item.get("interval_ms", 20)), click_hold_ms)
            elif action == "scroll":
                with self._hold_modifiers(self._normalize_modifiers(item.get("modifiers"))):
                    self._mouse_scroll(x, y, str(item.get("direction") or "down"), int(item.get("notches", 3)), int(item.get("interval_ms", 20)))
            elif action == "mouse_down":
                self._mouse_move(x, y, 0)
                button = self._button(item.get("button"))
                self._mouse_flag(MOUSE_BUTTON_FLAGS[button][0], button=button)
            else:
                self._mouse_move(x, y, 0)
                button = self._button(item.get("button"))
                self._mouse_flag(MOUSE_BUTTON_FLAGS[button][1], button=button)
            result = {"type": action, "screen_point": {"x": x, "y": y}}
            if action == "click":
                result["click_hold_ms"] = click_hold_ms
            return result
        if action == "drag":
            _frame, x, y = self._resolve_point(session, item)
            target = item.get("to")
            if not isinstance(target, dict):
                raise GuiError("INVALID_ARGUMENT", "批量drag缺少to。")
            _target_frame, end_x, end_y = self._resolve_point(session, {"frame_id": item.get("frame_id"), **target})
            self._check_drag_origin(_frame, x, y)
            with self._hold_modifiers(self._normalize_modifiers(item.get("modifiers"))):
                self._mouse_drag(x, y, end_x, end_y, str(item.get("button") or "left"), int(item.get("duration_ms", 0)), origin_frame=_frame)
            return {"type": action, "from": {"x": x, "y": y}, "to": {"x": end_x, "y": end_y}, "change_check_scope": "origin_window"}
        if action == "set_value":
            self._set_element_value(session, item)
            return {"type": action, "character_count": len(str(item.get("text", "")))}
        if action == "type_text":
            text = str(item.get("text") or "")
            self._type_text(text, int(item.get("interval_ms", 20)))
            return {"type": action, "character_count": len(text)}
        if action == "press_key":
            self._press_key(str(item.get("key") or ""), int(item.get("presses", 1)), int(item.get("interval_ms", 20)))
            return {"type": action, "key": str(item.get("key") or "")}
        if action == "hotkey":
            keys = item.get("keys")
            if not isinstance(keys, list):
                raise GuiError("INVALID_ARGUMENT", "批量hotkey缺少keys。")
            self._hotkey([str(key) for key in keys], int(item.get("hold_ms", 0)))
            return {"type": action, "keys": keys}
        if action == "wait":
            milliseconds = max(0, min(int(item.get("duration_ms", 300)), 10000))
            self._interruptible_sleep(milliseconds / 1000)
            return {"type": action, "duration_ms": milliseconds}
        raise GuiError("INVALID_ARGUMENT", f"不支持的批量动作：{action}")

    def _virtual_metrics(self) -> tuple[int, int, int, int]:
        rect = virtual_rect()
        return rect["left"], rect["top"], rect["width"], rect["height"]

    def _send_input(self, item: INPUT, *, allow_cancelled: bool = False) -> None:
        if self.cancel_event.is_set() and not allow_cancelled:
            raise GuiError("GUI_RUNTIME_STOPPED", "GUI后台运行器已经退出。")
        if user32.SendInput(1, ctypes.byref(item), ctypes.sizeof(INPUT)) != 1:
            raise GuiError("INPUT_DESKTOP_UNAVAILABLE", "Windows拒绝了输入，桌面可能已锁定或不可交互。")
        self.input_events_sent = getattr(self, "input_events_sent", 0) + 1

    def _mouse_move_event(self, x: int, y: int) -> None:
        left, top, width, height = self._virtual_metrics()
        if not left <= x < left + width or not top <= y < top + height:
            raise GuiError("POINT_OUTSIDE_DESKTOP", "目标坐标已不在当前屏幕范围内，请刷新界面。")
        normalized_x = min(65535, int((x - left + 0.5) * 65536 / width))
        normalized_y = min(65535, int((y - top + 0.5) * 65536 / height))
        flags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK
        self._send_input(INPUT(type=INPUT_MOUSE, mi=MOUSEINPUT(normalized_x, normalized_y, 0, flags, 0, self.marker)))

    def _mouse_move(self, x: int, y: int, duration_ms: int) -> None:
        duration = max(0, min(int(duration_ms), 10000))
        point = POINT()
        user32.GetCursorPos(ctypes.byref(point))
        if duration <= 0:
            self._mouse_move_event(x, y)
            self._verify_mouse_position(x, y)
            return
        steps = max(2, min(120, math.ceil(duration / 15)))
        for step in range(1, steps + 1):
            ratio = step / steps
            self._mouse_move_event(round(point.x + (x - point.x) * ratio), round(point.y + (y - point.y) * ratio))
            if step < steps:
                self._interruptible_sleep(duration / steps / 1000)
        self._verify_mouse_position(x, y)

    def _verify_mouse_position(self, x: int, y: int) -> None:
        point = POINT()
        deadline = time.monotonic() + POINTER_VERIFY_TIMEOUT_MS / 1000
        while user32.GetCursorPos(ctypes.byref(point)):
            if (int(point.x), int(point.y)) == (x, y):
                return
            if time.monotonic() >= deadline:
                break
            self._interruptible_sleep(0.005)
        raise GuiError("POINTER_POSITION_MISMATCH", "鼠标实际位置与预览落点不一致，未继续点击。", {"expected": {"x": x, "y": y}, "actual": {"x": int(point.x), "y": int(point.y)}, "verification_timeout_ms": POINTER_VERIFY_TIMEOUT_MS})

    def _mouse_flag(
        self,
        flag: int,
        data: int = 0,
        *,
        button: str | None = None,
        allow_cancelled: bool = False,
    ) -> None:
        self._send_input(
            INPUT(type=INPUT_MOUSE, mi=MOUSEINPUT(0, 0, data & 0xFFFFFFFF, flag, 0, self.marker)),
            allow_cancelled=allow_cancelled,
        )
        if button is not None:
            down, up = MOUSE_BUTTON_FLAGS[button]
            if flag == down:
                self.held_mouse_buttons.add(button)
            elif flag == up:
                self.held_mouse_buttons.discard(button)

    @staticmethod
    def _button(value: Any) -> str:
        button = str(value or "left").lower()
        if button not in MOUSE_BUTTON_FLAGS:
            raise GuiError("INVALID_ARGUMENT", "button必须是left、right或middle。")
        return button

    def _mouse_click(self, x: int, y: int, button: str, clicks: int, interval_ms: int, click_hold_ms: int = DEFAULT_CLICK_HOLD_MS) -> None:
        chosen = self._button(button)
        count = int(clicks)
        if count not in {1, 2}:
            raise GuiError("INVALID_ARGUMENT", "clicks必须是1或2。")
        hold_seconds = max(0, min(int(click_hold_ms), 2000)) / 1000
        self._mouse_move(x, y, 0)
        down, up = MOUSE_BUTTON_FLAGS[chosen]
        for index in range(count):
            pressed = False
            try:
                self._mouse_flag(down, button=chosen)
                pressed = True
                if hold_seconds > 0:
                    self._interruptible_sleep(hold_seconds)
            finally:
                if pressed:
                    self._mouse_flag(up, button=chosen, allow_cancelled=True)
            if index + 1 < count:
                self._interruptible_sleep(max(0, min(interval_ms, 1000)) / 1000)

    def _mouse_drag(self, x: int, y: int, end_x: int, end_y: int, button: str, duration_ms: int, *, origin_frame: dict[str, Any]) -> None:
        chosen = self._button(button)
        self._mouse_move(x, y, 0)
        # Pointer movement can open a popup; recheck immediately before pressing.
        self._check_drag_origin(origin_frame, x, y)
        down, up = MOUSE_BUTTON_FLAGS[chosen]
        pressed = False
        try:
            self._mouse_flag(down, button=chosen)
            pressed = True
            duration = max(0, min(duration_ms, 10000))
            if duration <= 0:
                self._mouse_move_event(end_x, end_y)
            else:
                steps = max(2, min(120, math.ceil(duration / 15)))
                for step in range(1, steps + 1):
                    ratio = step / steps
                    self._mouse_move_event(round(x + (end_x - x) * ratio), round(y + (end_y - y) * ratio))
                    if step < steps:
                        self._interruptible_sleep(duration / steps / 1000)
        finally:
            if pressed:
                self._mouse_flag(up, button=chosen, allow_cancelled=True)

    def _mouse_scroll(self, x: int, y: int, direction: str, notches: int, interval_ms: int) -> None:
        chosen = str(direction).lower()
        if chosen not in {"up", "down", "left", "right"}:
            raise GuiError("INVALID_ARGUMENT", "direction必须是up、down、left或right。")
        count = max(1, min(int(notches), 100))
        self._mouse_move(x, y, 0)
        flag = MOUSEEVENTF_HWHEEL if chosen in {"left", "right"} else MOUSEEVENTF_WHEEL
        delta = WHEEL_DELTA if chosen in {"up", "right"} else -WHEEL_DELTA
        for index in range(count):
            self._mouse_flag(flag, delta)
            if index + 1 < count:
                self._interruptible_sleep(max(0, min(interval_ms, 2000)) / 1000)

    @staticmethod
    def _key_name(value: str) -> str:
        name = str(value or "").strip().lower().replace("_", "").replace("-", "")
        return KEY_ALIASES.get(name, name)

    def _key_vk(self, value: str) -> tuple[int, bool]:
        name = self._key_name(value)
        if name in VK_CODES:
            return VK_CODES[name], name in EXTENDED_KEYS
        if len(name) == 1 and "a" <= name <= "z":
            return ord(name.upper()), False
        if len(name) == 1 and "0" <= name <= "9":
            return ord(name), False
        if name.startswith("f") and name[1:].isdigit() and 1 <= int(name[1:]) <= 24:
            return 0x70 + int(name[1:]) - 1, False
        raise GuiError("INVALID_ARGUMENT", f"不支持的按键：{value}")

    def _key_event(
        self,
        vk: int,
        key_up: bool,
        extended: bool = False,
        *,
        allow_cancelled: bool = False,
    ) -> None:
        flags = (KEYEVENTF_EXTENDEDKEY if extended else 0) | (KEYEVENTF_KEYUP if key_up else 0)
        self._send_input(
            INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(vk, 0, flags, 0, self.marker)),
            allow_cancelled=allow_cancelled,
        )
        key = (vk, extended)
        if key_up:
            self.held_keys.discard(key)
        else:
            self.held_keys.add(key)

    def _press_key(self, key: str, presses: int, interval_ms: int) -> None:
        count = max(1, min(int(presses), 20))
        vk, extended = self._key_vk(key)
        for index in range(count):
            self._key_event(vk, False, extended)
            self._key_event(vk, True, extended, allow_cancelled=True)
            if index + 1 < count:
                self._interruptible_sleep(max(0, min(interval_ms, 2000)) / 1000)

    def _hotkey(self, keys: list[str], hold_ms: int) -> None:
        if not 2 <= len(keys) <= 8:
            raise GuiError("INVALID_ARGUMENT", "keys必须包含2到8个按键。")
        resolved = [self._key_vk(key) for key in keys]
        held: list[tuple[int, bool]] = []
        try:
            for vk, extended in resolved:
                self._key_event(vk, False, extended)
                held.append((vk, extended))
            self._interruptible_sleep(max(0, min(hold_ms, 2000)) / 1000)
        finally:
            for vk, extended in reversed(held):
                self._key_event(vk, True, extended, allow_cancelled=True)

    def _type_text(self, text: str, interval_ms: int) -> None:
        if len(text) > 100000:
            raise GuiError("INVALID_ARGUMENT", "text最多100000个字符。")
        encoded = text.encode("utf-16-le", errors="surrogatepass")
        units = [int.from_bytes(encoded[index:index + 2], "little") for index in range(0, len(encoded), 2)]
        for index, unit in enumerate(units):
            self._send_input(INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(0, unit, KEYEVENTF_UNICODE, 0, self.marker)))
            self._send_input(
                INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(0, unit, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0, self.marker)),
                allow_cancelled=True,
            )
            if index + 1 < len(units):
                self._interruptible_sleep(max(0, min(interval_ms, 2000)) / 1000)

    def _normalize_modifiers(self, value: Any) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list) or len(value) > 4:
            raise GuiError("INVALID_ARGUMENT", "modifiers必须是最多4项的数组。")
        result: list[str] = []
        for item in value:
            name = self._key_name(str(item))
            if name not in {"ctrl", "shift", "alt", "win"}:
                raise GuiError("INVALID_ARGUMENT", "modifiers只支持ctrl、shift、alt、win。")
            if name not in result:
                result.append(name)
        return result

    @contextmanager
    def _hold_modifiers(self, modifiers: list[str]):
        held: list[tuple[int, bool]] = []
        try:
            for name in modifiers:
                vk, extended = self._key_vk(name)
                self._key_event(vk, False, extended)
                held.append((vk, extended))
            yield
        finally:
            for vk, extended in reversed(held):
                self._key_event(vk, True, extended, allow_cancelled=True)

    def _release_held_inputs(self) -> None:
        for button in list(self.held_mouse_buttons):
            try:
                self._mouse_flag(
                    MOUSE_BUTTON_FLAGS[button][1],
                    button=button,
                    allow_cancelled=True,
                )
            except Exception:
                self.held_mouse_buttons.discard(button)
        for vk, extended in list(self.held_keys):
            try:
                self._key_event(vk, True, extended, allow_cancelled=True)
            except Exception:
                self.held_keys.discard((vk, extended))

    def _interruptible_sleep(self, seconds: float) -> None:
        deadline = time.monotonic() + max(0.0, seconds)
        while True:
            if self.cancel_event.is_set():
                raise GuiError("GUI_RUNTIME_STOPPED", "GUI后台运行器已经退出。")
            if time.monotonic() >= deadline:
                return
            time.sleep(min(0.02, max(0.0, deadline - time.monotonic())))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-file", required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--lock-id", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--marker", required=True, type=int)
    parser.add_argument("--idle-timeout-seconds", type=float, default=120)
    parser.add_argument("--owner-status-url", default="")
    parser.add_argument("--require-startup-confirmation", action="store_true")
    parser.add_argument("--startup-timeout-seconds", type=float, default=10)
    return parser.parse_args()


def main() -> int:
    global SERVICE
    if os.name != "nt":
        return 2
    with physical_coordinates():
        SERVICE = GuiService(parse_args())
        return SERVICE.run()


if __name__ == "__main__":
    raise SystemExit(main())
