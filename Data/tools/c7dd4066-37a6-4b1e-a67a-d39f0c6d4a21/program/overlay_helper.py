from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import shutil
import socket
import threading
import time
from typing import Any
from uuid import uuid4

from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageGrab


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
user32.SetLayeredWindowAttributes.argtypes = [wintypes.HWND, wintypes.COLORREF, wintypes.BYTE, wintypes.DWORD]
user32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, WPARAM, LPARAM]
user32.LoadCursorW.argtypes = [wintypes.HINSTANCE, ctypes.c_void_p]
user32.LoadCursorW.restype = wintypes.HANDLE
user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = wintypes.UINT
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE
kernel32.GetCurrentThreadId.restype = wintypes.DWORD


WM_PAINT = 0x000F
WM_DESTROY = 0x0002
WM_NCHITTEST = 0x0084
WM_LBUTTONUP = 0x0202
WM_QUIT = 0x0012
WM_APP_STOP = 0x8001
HTTRANSPARENT = -1
WH_KEYBOARD_LL = 13
WH_MOUSE_LL = 14
WS_POPUP = 0x80000000
WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_NOACTIVATE = 0x08000000
GWL_EXSTYLE = -20
LWA_ALPHA = 0x00000002
SW_HIDE = 0
SW_SHOWNOACTIVATE = 4
HWND_TOPMOST = -1
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020
DT_CENTER = 0x0001
DT_VCENTER = 0x0004
DT_SINGLELINE = 0x0020
TRANSPARENT = 1
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
DEFAULT_CLICK_HOLD_MS = 80
COORDINATE_PREVIEW_COLOR = (255, 45, 138)
COORDINATE_PREVIEW_COLOR_HEX = "#FF2D8A"

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


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


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


def overlay_image(raw: Image.Image, cells: list[dict[str, Any]], source_rect: dict[str, int]) -> Image.Image:
    image = raw.convert("RGB").copy()
    draw = ImageDraw.Draw(image, "RGBA")
    try:
        font_path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "segoeuib.ttf"
        font = ImageFont.truetype(str(font_path), max(14, min(28, round(min(image.size) / 32))))
    except OSError:
        font = ImageFont.load_default()
    line_width = max(1, round(min(image.size) / 500))
    for cell in cells:
        rect = cell["rect_absolute"]
        left = rect["left"] - source_rect["left"]
        top = rect["top"] - source_rect["top"]
        right = left + rect["width"]
        bottom = top + rect["height"]
        draw.rectangle((left, top, right - 1, bottom - 1), outline=(0, 230, 255, 210), width=line_width)
        label = str(cell["cell_id"])
        label_box = draw.textbbox((0, 0), label, font=font, stroke_width=2)
        label_width = label_box[2] - label_box[0]
        label_height = label_box[3] - label_box[1]
        pad = 4
        draw.rounded_rectangle(
            (left + 4, top + 4, left + 4 + label_width + pad * 2, top + 4 + label_height + pad * 2),
            radius=4,
            fill=(0, 22, 34, 210),
            outline=(0, 230, 255, 240),
        )
        draw.text(
            (left + 4 + pad, top + 4 + pad - label_box[1]),
            label,
            font=font,
            fill=(235, 255, 255, 255),
            stroke_width=2,
            stroke_fill=(0, 20, 30, 255),
        )
    return image


def safe_session_id(value: str) -> str:
    normalized = str(value or "").strip()
    if not re.fullmatch(r"gui_[a-f0-9]{32}", normalized):
        raise GuiError("GUI_SESSION_INVALID", "GUI Session ID无效。")
    return normalized


class GuiService:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.workspace = Path(args.workspace).resolve()
        self.gui_root = self.workspace / ".Tiance" / "gui-temp"
        self.state_path = Path(args.state_file).resolve()
        self.lock_id = args.lock_id
        self.token = args.token
        self.marker = int(args.marker) & 0xFFFFFFFF
        self.block_user_input = bool(args.block_user_input)
        self.project_id = args.project_id
        self.session_id = args.session_id
        self.overlay_windows: list[int] = []
        self.exit_window: int = 0
        self.exit_rect = {"left": 0, "top": 0, "width": 0, "height": 0}
        self.window_proc = WNDPROC(self._window_proc)
        self.mouse_hook_proc = HOOKPROC(self._mouse_hook)
        self.keyboard_hook_proc = HOOKPROC(self._keyboard_hook)
        self.mouse_hook = 0
        self.keyboard_hook = 0
        self.main_thread_id = int(kernel32.GetCurrentThreadId())
        self.stop_event = threading.Event()
        self.cancel_event = threading.Event()
        self.service_lock = threading.RLock()
        self.passthrough = False
        self.external_mouse_events = 0
        self.external_keyboard_events = 0
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

    def run(self) -> int:
        self.gui_root.mkdir(parents=True, exist_ok=True)
        try:
            if self.block_user_input:
                self._create_windows()
            self._install_hooks()
            self.capture_mode = self._detect_capture_mode() if self.block_user_input else "no_overlay"
            self._write_active_state("active")
            self.server_thread.start()
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
            self._write_active_state("failed", error=f"{type(exc).__name__}: {exc}")
            return 1
        finally:
            self.stop_event.set()
            try:
                self.server_socket.close()
            except OSError:
                pass
            self._release_held_inputs()
            self._uninstall_hooks()
            self._destroy_windows()
            self._cleanup_gui_sessions()
            if not self.startup_failed:
                self._remove_active_state()

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
            hbrBackground=gdi32.CreateSolidBrush(colorref(5, 14, 24)),
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
        self.exit_class = f"TianceGuiExit_{os.getpid()}"
        self._register_class(self.overlay_class)
        self._register_class(self.exit_class)
        instance = kernel32.GetModuleHandleW(None)
        monitors = monitor_rects()
        if not monitors:
            raise GuiError("DISPLAY_UNAVAILABLE", "没有检测到可用显示器。")
        for rect in monitors:
            hwnd = user32.CreateWindowExW(
                WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_LAYERED | WS_EX_NOACTIVATE,
                self.overlay_class,
                "Tiance AI Control Overlay",
                WS_POPUP,
                rect["left"], rect["top"], rect["width"], rect["height"],
                0, 0, instance, None,
            )
            if not hwnd:
                raise ctypes.WinError(ctypes.get_last_error())
            self.overlay_windows.append(int(hwnd))
            user32.SetLayeredWindowAttributes(hwnd, 0, 205, LWA_ALPHA)
            user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE)
            user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
            user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)

        primary = next((item for item in monitors if item["primary"]), monitors[0])
        button_width, button_height = 220, 58
        button_left = primary["left"] + (primary["width"] - button_width) // 2
        button_top = primary["top"] + primary["height"] // 2 + 105
        self.exit_rect = {
            "left": button_left, "top": button_top,
            "width": button_width, "height": button_height,
        }
        hwnd = user32.CreateWindowExW(
            WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_LAYERED | WS_EX_NOACTIVATE,
            self.exit_class,
            "退出AI操控",
            WS_POPUP,
            button_left, button_top, button_width, button_height,
            0, 0, instance, None,
        )
        if not hwnd:
            raise ctypes.WinError(ctypes.get_last_error())
        self.exit_window = int(hwnd)
        user32.SetLayeredWindowAttributes(hwnd, 0, 242, LWA_ALPHA)
        user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE)
        user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
        user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)

    def _destroy_windows(self) -> None:
        for hwnd in [self.exit_window, *self.overlay_windows]:
            if hwnd and user32.IsWindow(hwnd):
                user32.DestroyWindow(hwnd)
        self.exit_window = 0
        self.overlay_windows.clear()

    def _window_proc(self, hwnd: int, message: int, wparam: int, lparam: int) -> int:
        if message == WM_NCHITTEST and self.passthrough:
            return HTTRANSPARENT
        if message == WM_PAINT:
            self._paint_window(int(hwnd))
            return 0
        if message == WM_LBUTTONUP and int(hwnd) == self.exit_window:
            self.request_stop("user_exit")
            return 0
        if message == WM_APP_STOP:
            user32.PostQuitMessage(0)
            return 0
        if message == WM_DESTROY:
            return 0
        return int(user32.DefWindowProcW(hwnd, message, wparam, lparam))

    def _paint_window(self, hwnd: int) -> None:
        paint = PAINTSTRUCT()
        dc = user32.BeginPaint(hwnd, ctypes.byref(paint))
        if not dc:
            return
        try:
            client = wintypes.RECT()
            user32.GetClientRect(hwnd, ctypes.byref(client))
            width, height = int(client.right), int(client.bottom)
            if hwnd == self.exit_window:
                brush = gdi32.CreateSolidBrush(colorref(8, 44, 61))
                user32.FillRect(dc, ctypes.byref(client), brush)
                gdi32.DeleteObject(brush)
                pen = gdi32.CreatePen(0, 2, colorref(0, 220, 255))
                old_pen = gdi32.SelectObject(dc, pen)
                gdi32.MoveToEx(dc, 1, 1, None)
                gdi32.LineTo(dc, width - 2, 1)
                gdi32.LineTo(dc, width - 2, height - 2)
                gdi32.LineTo(dc, 1, height - 2)
                gdi32.LineTo(dc, 1, 1)
                gdi32.SelectObject(dc, old_pen)
                gdi32.DeleteObject(pen)
                self._draw_text(dc, "退出 AI 操控", client, 20, colorref(235, 255, 255))
                return
            background = gdi32.CreateSolidBrush(colorref(3, 12, 20))
            user32.FillRect(dc, ctypes.byref(client), background)
            gdi32.DeleteObject(background)
            pen = gdi32.CreatePen(0, 1, colorref(0, 88, 110))
            old_pen = gdi32.SelectObject(dc, pen)
            spacing = max(72, min(width, height) // 10)
            for x in range(0, width, spacing):
                gdi32.MoveToEx(dc, x, 0, None)
                gdi32.LineTo(dc, x, height)
            for y in range(0, height, spacing):
                gdi32.MoveToEx(dc, 0, y, None)
                gdi32.LineTo(dc, width, y)
            gdi32.SelectObject(dc, old_pen)
            gdi32.DeleteObject(pen)
            title = wintypes.RECT(0, height // 2 - 66, width, height // 2 + 6)
            subtitle = wintypes.RECT(0, height // 2 + 10, width, height // 2 + 54)
            self._draw_text(dc, "AI 操控中", title, 46, colorref(225, 253, 255))
            self._draw_text(dc, "界面已锁定，请等待操作完成", subtitle, 19, colorref(0, 220, 255))
        finally:
            user32.EndPaint(hwnd, ctypes.byref(paint))

    def _draw_text(self, dc: int, text: str, rect: wintypes.RECT, size: int, color: int) -> None:
        font = gdi32.CreateFontW(
            -size, 0, 0, 0, 600, 0, 0, 0, 134, 0, 0, 5, 0, "Microsoft YaHei UI"
        )
        old_font = gdi32.SelectObject(dc, font)
        gdi32.SetBkMode(dc, TRANSPARENT)
        gdi32.SetTextColor(dc, color)
        user32.DrawTextW(dc, text, -1, ctypes.byref(rect), DT_CENTER | DT_VCENTER | DT_SINGLELINE)
        gdi32.SelectObject(dc, old_font)
        gdi32.DeleteObject(font)

    def _set_passthrough(self, enabled: bool) -> None:
        self.passthrough = bool(enabled)
        for hwnd in [*self.overlay_windows, self.exit_window]:
            if not hwnd or not user32.IsWindow(hwnd):
                continue
            style = int(user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE))
            updated = style | WS_EX_TRANSPARENT if enabled else style & ~WS_EX_TRANSPARENT
            user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, updated)
            user32.SetWindowPos(
                hwnd,
                HWND_TOPMOST,
                0,
                0,
                0,
                0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_FRAMECHANGED,
            )

    def _show_overlays(self, visible: bool) -> None:
        command = SW_SHOWNOACTIVATE if visible else SW_HIDE
        for hwnd in [*self.overlay_windows, self.exit_window]:
            if hwnd and user32.IsWindow(hwnd):
                user32.ShowWindow(hwnd, command)
                if visible:
                    user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)

    def _detect_capture_mode(self) -> str:
        primary = next((item for item in monitor_rects() if item["primary"]), monitor_rects()[0])
        try:
            time.sleep(0.04)
            shown = ImageGrab.grab(bbox=rect_ltrb(primary), all_screens=True).convert("RGB")
            self._show_overlays(False)
            time.sleep(0.05)
            hidden = ImageGrab.grab(bbox=rect_ltrb(primary), all_screens=True).convert("RGB")
            return "exclude_from_capture" if image_difference_percent(shown, hidden) < 0.2 else "hide_during_capture"
        except Exception:
            return "hide_during_capture"
        finally:
            self._show_overlays(True)

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
            if int(event.dwExtraInfo) == self.marker:
                return int(user32.CallNextHookEx(self.mouse_hook, code, wparam, lparam))
            self.external_mouse_events += 1
            if self.block_user_input and int(wparam) == WM_LBUTTONUP:
                left = self.exit_rect["left"]
                top = self.exit_rect["top"]
                if (
                    left <= int(event.pt.x) < left + self.exit_rect["width"]
                    and top <= int(event.pt.y) < top + self.exit_rect["height"]
                ):
                    self.request_stop("user_exit")
            if self.block_user_input:
                return 1
            return int(user32.CallNextHookEx(self.mouse_hook, code, wparam, lparam))
        return int(user32.CallNextHookEx(self.mouse_hook, code, wparam, lparam))

    def _keyboard_hook(self, code: int, wparam: int, lparam: int) -> int:
        if code >= 0:
            event = ctypes.cast(lparam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            if int(event.dwExtraInfo) == self.marker:
                return int(user32.CallNextHookEx(self.keyboard_hook, code, wparam, lparam))
            self.external_keyboard_events += 1
            if self.block_user_input:
                return 1
            return int(user32.CallNextHookEx(self.keyboard_hook, code, wparam, lparam))
        return int(user32.CallNextHookEx(self.keyboard_hook, code, wparam, lparam))

    def request_stop(self, reason: str) -> None:
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

    def _handle_connection(self, connection: socket.socket) -> None:
        with connection:
            connection.settimeout(130)
            try:
                request = self._receive_json(connection)
                response = self._dispatch(request)
            except GuiError as exc:
                response = {"ok": False, "error": exc.message, "error_info": {"code": exc.code, "details": exc.details}}
            except Exception as exc:
                response = {
                    "ok": False,
                    "error": f"{type(exc).__name__}: {exc}",
                    "error_info": {"code": "GUI_INTERNAL_ERROR"},
                }
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
            threading.Timer(0.05, lambda: self.request_stop("tool_unlock")).start()
            return response
        with self.service_lock:
            if self.cancel_event.is_set():
                raise GuiError("GUI_RUNTIME_STOPPED", "GUI后台运行器已经退出。")
            if method == "inspect":
                return self.inspect(arguments)
            if method == "mouse":
                return self.mouse(arguments)
            if method == "keyboard":
                return self.keyboard(arguments)
            if method == "batch":
                return self.batch(arguments)
        raise GuiError("INVALID_ARGUMENT", f"不支持的GUI方法：{method}")

    def status(self) -> dict[str, Any]:
        return {
            "ok": True,
            "summary": "GUI后台运行器正在工作。",
            "data": {
                "active": True,
                "runtime_id": self.lock_id,
                "project_id": self.project_id,
                "session_id": self.session_id,
                "capture_mode": self.capture_mode,
                "input_mode": "blocked" if self.block_user_input else "observed",
                "external_input_counts": {
                    "mouse": self.external_mouse_events,
                    "keyboard": self.external_keyboard_events,
                },
            },
        }

    def _capture_bbox(self, rect: dict[str, int]) -> Image.Image:
        if rect["width"] < 2 or rect["height"] < 2:
            raise GuiError("CAPTURE_FAILED", "截图区域尺寸无效。")
        if self.capture_mode in {"exclude_from_capture", "no_overlay"}:
            return ImageGrab.grab(bbox=rect_ltrb(rect), all_screens=True).convert("RGB")
        self._show_overlays(False)
        try:
            if dwmapi is not None:
                try:
                    dwmapi.DwmFlush()
                except OSError:
                    pass
            time.sleep(0.04)
            return ImageGrab.grab(bbox=rect_ltrb(rect), all_screens=True).convert("RGB")
        finally:
            self._show_overlays(True)

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
        return self._capture_bbox(rect), rect

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
            raise GuiError("VIEW_NOT_FOUND", f"没有找到View {view_id}。")
        return view

    @staticmethod
    def _cell(view: dict[str, Any], cell_id: int) -> dict[str, Any]:
        for cell in view.get("cells", []):
            if int(cell.get("cell_id", -1)) == int(cell_id):
                return cell
        raise GuiError("CELL_NOT_FOUND", f"没有找到Cell {cell_id}。")

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
    ) -> dict[str, Any]:
        rows, cols = choose_grid(raw.width, raw.height, grid_mode, grid_target_cells, grid_rows, grid_cols)
        cells = build_cells(source_rect, rows, cols)
        overlay = overlay_image(raw, cells, source_rect)
        frame_folder = folder / f"frame_{frame_id:03d}"
        frame_folder.mkdir(parents=True, exist_ok=True)
        safe_view = "root" if view_id == "root" else "zoom_" + re.sub(r"[^0-9A-Za-z_-]", "_", view_id)
        raw_path = frame_folder / f"{safe_view}_raw.png"
        overlay_path = frame_folder / f"{safe_view}_overlay.png"
        raw.save(raw_path, format="PNG", optimize=True)
        overlay.save(overlay_path, format="PNG", optimize=True)
        return {
            "view_id": view_id,
            "source_rect_absolute": source_rect,
            "grid": {"rows": rows, "columns": cols},
            "cells": cells,
            "raw_image": raw_path.relative_to(folder).as_posix(),
            "overlay_image": overlay_path.relative_to(folder).as_posix(),
        }

    def _create_frame(
        self,
        session: dict[str, Any],
        *,
        reason: str,
        raw: Image.Image | None = None,
        source_rect: dict[str, int] | None = None,
        grid_mode: str = "auto",
        grid_target_cells: int = 16,
        grid_rows: int | None = None,
        grid_cols: int | None = None,
    ) -> tuple[dict[str, Any], Path]:
        if raw is None or source_rect is None:
            raw, source_rect = self._capture_target(session["target"])
        frame_id = len(session.get("frames", []))
        folder = self._session_dir(session["gui_session_id"])
        root = self._create_view(
            folder=folder,
            frame_id=frame_id,
            view_id="root",
            raw=raw,
            source_rect=source_rect,
            grid_mode=grid_mode,
            grid_target_cells=grid_target_cells,
            grid_rows=grid_rows,
            grid_cols=grid_cols,
        )
        frame = {
            "frame_id": frame_id,
            "created_at": now_iso(),
            "reason": reason,
            "capture_rect": source_rect,
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
                "target": session["target"],
                "grid": view["grid"],
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
            "warnings": [],
        }

    def inspect(self, arguments: dict[str, Any]) -> dict[str, Any]:
        action = str(arguments.get("action") or "").strip()
        if action == "list_windows":
            contains = str(arguments.get("contains") or "").casefold()
            limit = max(1, min(int(arguments.get("limit", 100)), 300))
            own_windows = {self.exit_window, *self.overlay_windows}
            items = [item for item in visible_windows() if item["hwnd"] not in own_windows]
            if contains:
                items = [item for item in items if contains in item["title"].casefold()]
            return {"ok": True, "summary": f"找到{min(len(items), limit)}个可见窗口。", "data": {"count": min(len(items), limit), "items": items[:limit]}, "warnings": []}
        if action == "start":
            target_type = str(arguments.get("target") or "screen")
            if target_type == "window":
                selected = resolve_window(arguments.get("hwnd"), arguments.get("window_title"))
                if selected["hwnd"] in {self.exit_window, *self.overlay_windows}:
                    raise GuiError("INVALID_ARGUMENT", "不能把GUI锁覆盖层作为操作目标。")
                if not activate_window(selected["hwnd"]):
                    raise GuiError("WINDOW_ACTIVATION_FAILED", "无法把目标窗口切换到前台，未创建GUI会话。")
                target = {"type": "window", "hwnd": selected["hwnd"], "title": selected["title"]}
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
            frame, image_path = self._create_frame(
                session,
                reason="inspect_start",
                grid_mode=str(arguments.get("grid_mode") or "auto"),
                grid_target_cells=int(arguments.get("grid_target_cells", 16)),
                grid_rows=arguments.get("grid_rows"),
                grid_cols=arguments.get("grid_cols"),
            )
            view = frame["views"]["root"]
            return self._result_with_image(summary="已查看当前界面。", session=session, frame=frame, view=view, image_path=image_path)
        gui_session_id = safe_session_id(str(arguments.get("gui_session_id") or ""))
        session = self._load_session(gui_session_id)
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
            cell = self._cell(parent, int(arguments.get("cell_id", 0)))
            folder = self._session_dir(gui_session_id)
            parent_raw = Image.open(folder / parent["raw_image"]).convert("RGB")
            parent_rect = parent["source_rect_absolute"]
            cell_rect = cell["rect_absolute"]
            local = (
                cell_rect["left"] - parent_rect["left"],
                cell_rect["top"] - parent_rect["top"],
                cell_rect["left"] - parent_rect["left"] + cell_rect["width"],
                cell_rect["top"] - parent_rect["top"] + cell_rect["height"],
            )
            cropped = parent_raw.crop(local)
            view_id = str(cell["cell_id"]) if parent["view_id"] == "root" else f"{parent['view_id']}/{cell['cell_id']}"
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
                    time.sleep(interval_ms / 1000)
                    raw, rect = self._capture_target(session["target"])
                    difference = image_difference_percent(reference, raw)
                reason = f"wait_{mode}_{'matched' if matched else 'timeout'}"
            else:
                raw, rect = self._capture_target(session["target"])
                difference = image_difference_percent(previous_raw, raw)
                matched = True
                samples = 1
                reason = "inspect_refresh"
            frame, image_path = self._create_frame(session, reason=reason, raw=raw, source_rect=rect)
            view = frame["views"]["root"]
            result = self._result_with_image(summary="已返回最新界面。", session=session, frame=frame, view=view, image_path=image_path)
            result["data"]["difference_from_previous_percent"] = difference
            result["data"]["wait_matched"] = matched
            result["data"]["samples"] = samples
            return result
        raise GuiError("INVALID_ARGUMENT", f"不支持的查看操作：{action}")

    def _resolve_point(self, session: dict[str, Any], arguments: dict[str, Any]) -> tuple[dict[str, Any], int, int]:
        frame_id = int(arguments.get("frame_id", -1))
        if frame_id != int(session.get("latest_frame_id", -1)):
            raise GuiError("STALE_FRAME", "GUI操作必须使用最新Frame。")
        frame = self._frame(session, frame_id)
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

    def _preflight(self, session: dict[str, Any], threshold: float) -> tuple[dict[str, Any], Image.Image, dict[str, int], float]:
        target = session["target"]
        if target["type"] == "window" and int(user32.GetForegroundWindow() or 0) != int(target["hwnd"]):
            raise GuiError("TARGET_NOT_FOREGROUND", "目标窗口已失去前台焦点，本次未执行；请重新查看目标窗口。")
        frame = self._frame(session, int(session["latest_frame_id"]))
        root = frame["views"]["root"]
        previous = Image.open(self._session_dir(session["gui_session_id"]) / root["raw_image"]).convert("RGB")
        current, rect = self._capture_target(session["target"])
        difference = image_difference_percent(previous, current)
        return frame, current, rect, difference

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
    ) -> dict[str, Any]:
        view = self._view(frame, str(arguments.get("view_id") or "root"))
        source_rect = view["source_rect_absolute"]
        captured_x, captured_y = screen_x, screen_y
        if session["target"]["type"] == "window":
            current_rect = self._target_rect(session["target"])
            captured_rect = frame["capture_rect"]
            captured_x -= current_rect["left"] - captured_rect["left"]
            captured_y -= current_rect["top"] - captured_rect["top"]
        local_x = captured_x - int(source_rect["left"])
        local_y = captured_y - int(source_rect["top"])
        folder = self._session_dir(session["gui_session_id"])
        image = Image.open(folder / view["overlay_image"]).convert("RGB")
        if not 0 <= local_x < image.width or not 0 <= local_y < image.height:
            raise GuiError("COORDINATE_PREVIEW_FAILED", "选定坐标不在当前View内，未生成预览图。")
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
        return result

    def _blocked_changed_result(self, session: dict[str, Any], raw: Image.Image, rect: dict[str, int], difference: float) -> dict[str, Any]:
        frame, image_path = self._create_frame(session, reason="interface_changed_before_action", raw=raw, source_rect=rect)
        view = frame["views"]["root"]
        state = {
            "changed_before_action": True,
            "changed_during_action": False,
            "difference_percent": difference,
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
        self._set_passthrough(True)
        try:
            yield mouse_before, keyboard_before
        finally:
            self._set_passthrough(False)

    def _finish_action(
        self,
        *,
        session: dict[str, Any],
        before_raw: Image.Image,
        mouse_before: int,
        keyboard_before: int,
        action_name: str,
        action_data: dict[str, Any],
    ) -> dict[str, Any]:
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
        result["data"]["action"] = action_data
        return result

    def mouse(self, arguments: dict[str, Any]) -> dict[str, Any]:
        session = self._load_session(str(arguments.get("gui_session_id") or ""))
        action = str(arguments.get("action") or "").strip()
        mouse_at_start = self.external_mouse_events
        keyboard_at_start = self.external_keyboard_events
        threshold = float(arguments.get("change_threshold_percent", 0.5))
        _frame, before_raw, rect, difference = self._preflight(session, threshold)
        if difference >= threshold:
            return self._blocked_changed_result(session, before_raw, rect, difference)
        frame, x, y = self._resolve_point(session, arguments)
        if action == "preview":
            return self._preview_coordinate(
                session=session,
                frame=frame,
                arguments=arguments,
                screen_x=x,
                screen_y=y,
                difference=difference,
                mouse_before=mouse_at_start,
                keyboard_before=keyboard_at_start,
            )
        action_data: dict[str, Any] = {"type": action, "screen_point": {"x": x, "y": y}}
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
                target = arguments.get("to")
                if not isinstance(target, dict):
                    raise GuiError("INVALID_ARGUMENT", "drag必须提供to坐标。")
                _target_frame, end_x, end_y = self._resolve_point(session, {"frame_id": frame["frame_id"], **target})
                modifiers = self._normalize_modifiers(arguments.get("modifiers"))
                with self._hold_modifiers(modifiers):
                    self._mouse_drag(x, y, end_x, end_y, str(arguments.get("button") or "left"), int(arguments.get("duration_ms", 0)))
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
        return self._finish_action(
            session=session,
            before_raw=before_raw,
            mouse_before=counters[0],
            keyboard_before=counters[1],
            action_name=action,
            action_data=action_data,
        )

    def keyboard(self, arguments: dict[str, Any]) -> dict[str, Any]:
        session = self._load_session(str(arguments.get("gui_session_id") or ""))
        threshold = float(arguments.get("change_threshold_percent", 0.5))
        _frame, before_raw, rect, difference = self._preflight(session, threshold)
        if difference >= threshold:
            return self._blocked_changed_result(session, before_raw, rect, difference)
        action = str(arguments.get("action") or "").strip()
        action_data: dict[str, Any] = {"type": action}
        with self._ai_input() as counters:
            if action == "type_text":
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
        )

    def batch(self, arguments: dict[str, Any]) -> dict[str, Any]:
        session = self._load_session(str(arguments.get("gui_session_id") or ""))
        threshold = float(arguments.get("change_threshold_percent", 0.5))
        _frame, before_raw, rect, difference = self._preflight(session, threshold)
        if difference >= threshold:
            return self._blocked_changed_result(session, before_raw, rect, difference)
        actions = arguments.get("actions")
        if not isinstance(actions, list) or not 1 <= len(actions) <= 50:
            raise GuiError("INVALID_ARGUMENT", "actions必须包含1到50个动作。")
        results: list[dict[str, Any]] = []
        with self._ai_input() as counters:
            for index, item in enumerate(actions):
                if self.cancel_event.is_set():
                    raise GuiError("GUI_RUNTIME_STOPPED", "GUI后台运行器已经退出。", {"completed_actions": index})
                if not isinstance(item, dict):
                    raise GuiError("INVALID_ARGUMENT", f"actions[{index}]必须是对象。")
                results.append(self._execute_batch_item(session, item))
        return self._finish_action(
            session=session,
            before_raw=before_raw,
            mouse_before=counters[0],
            keyboard_before=counters[1],
            action_name="batch",
            action_data={"type": "batch", "actions": results},
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
            with self._hold_modifiers(self._normalize_modifiers(item.get("modifiers"))):
                self._mouse_drag(x, y, end_x, end_y, str(item.get("button") or "left"), int(item.get("duration_ms", 0)))
            return {"type": action, "from": {"x": x, "y": y}, "to": {"x": end_x, "y": end_y}}
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

    def _mouse_move_event(self, x: int, y: int) -> None:
        left, top, width, height = self._virtual_metrics()
        normalized_x = round((x - left) * 65535 / max(1, width - 1))
        normalized_y = round((y - top) * 65535 / max(1, height - 1))
        flags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK
        self._send_input(INPUT(type=INPUT_MOUSE, mi=MOUSEINPUT(normalized_x, normalized_y, 0, flags, 0, self.marker)))

    def _mouse_move(self, x: int, y: int, duration_ms: int) -> None:
        duration = max(0, min(int(duration_ms), 10000))
        point = POINT()
        user32.GetCursorPos(ctypes.byref(point))
        if duration <= 0:
            self._mouse_move_event(x, y)
            return
        steps = max(2, min(120, math.ceil(duration / 15)))
        for step in range(1, steps + 1):
            ratio = step / steps
            self._mouse_move_event(round(point.x + (x - point.x) * ratio), round(point.y + (y - point.y) * ratio))
            if step < steps:
                self._interruptible_sleep(duration / steps / 1000)

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

    def _mouse_drag(self, x: int, y: int, end_x: int, end_y: int, button: str, duration_ms: int) -> None:
        chosen = self._button(button)
        self._mouse_move(x, y, 0)
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
        while time.monotonic() < deadline:
            if self.cancel_event.is_set():
                raise GuiError("GUI_RUNTIME_STOPPED", "GUI后台运行器已经退出。")
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
    parser.add_argument("--block-user-input", action="store_true")
    return parser.parse_args()


def main() -> int:
    global SERVICE
    if os.name != "nt":
        return 2
    SERVICE = GuiService(parse_args())
    return SERVICE.run()


if __name__ == "__main__":
    raise SystemExit(main())
