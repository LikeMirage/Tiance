"""Native non-activating, click-through annotation windows. No input hooks."""
from __future__ import annotations

import ctypes as C
from ctypes import wintypes as W
import os
import sys
from uuid import uuid4

from PIL import Image, ImageDraw
from annotation_store import AnnotationError, font, render

user32 = C.WinDLL("user32", use_last_error=True)
gdi32 = C.WinDLL("gdi32", use_last_error=True)
kernel32 = C.WinDLL("kernel32", use_last_error=True)
LRESULT, WPARAM, LPARAM = C.c_ssize_t, C.c_size_t, C.c_ssize_t
WNDPROC = C.WINFUNCTYPE(LRESULT, W.HWND, W.UINT, WPARAM, LPARAM)


class WindowClass(C.Structure):
    _fields_ = [("cbSize", W.UINT), ("style", W.UINT), ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", C.c_int), ("cbWndExtra", C.c_int), ("hInstance", W.HINSTANCE),
                ("hIcon", W.HICON), ("hCursor", W.HANDLE), ("hbrBackground", W.HBRUSH),
                ("lpszMenuName", W.LPCWSTR), ("lpszClassName", W.LPCWSTR), ("hIconSm", W.HICON)]


class BitmapHeader(C.Structure):
    _fields_ = [("size", W.DWORD), ("width", W.LONG), ("height", W.LONG), ("planes", W.WORD),
                ("bits", W.WORD), ("compression", W.DWORD), ("image_size", W.DWORD),
                ("xppm", W.LONG), ("yppm", W.LONG), ("used", W.DWORD), ("important", W.DWORD)]


class BitmapInfo(C.Structure):
    _fields_ = [("header", BitmapHeader), ("colors", W.DWORD * 1)]


class Blend(C.Structure):
    _fields_ = [("operation", W.BYTE), ("flags", W.BYTE), ("alpha", W.BYTE), ("format", W.BYTE)]


def api(dll, name, args, result):
    function = getattr(dll, name)
    function.argtypes, function.restype = args, result
    return function


api(user32, "SetThreadDpiAwarenessContext", [C.c_void_p], C.c_void_p)
api(user32, "RegisterClassExW", [C.POINTER(WindowClass)], W.ATOM)
api(user32, "CreateWindowExW", [W.DWORD, W.LPCWSTR, W.LPCWSTR, W.DWORD, C.c_int, C.c_int, C.c_int, C.c_int,
                              W.HWND, W.HMENU, W.HINSTANCE, C.c_void_p], W.HWND)
api(user32, "DefWindowProcW", [W.HWND, W.UINT, WPARAM, LPARAM], LRESULT)
api(user32, "DestroyWindow", [W.HWND], W.BOOL)
api(user32, "ShowWindow", [W.HWND, C.c_int], W.BOOL)
api(user32, "SetWindowPos", [W.HWND, W.HWND, C.c_int, C.c_int, C.c_int, C.c_int, W.UINT], W.BOOL)
api(user32, "SetWindowDisplayAffinity", [W.HWND, W.DWORD], W.BOOL)
api(user32, "GetWindowDisplayAffinity", [W.HWND, C.POINTER(W.DWORD)], W.BOOL)
api(user32, "SetLayeredWindowAttributes", [W.HWND, W.DWORD, W.BYTE, W.DWORD], W.BOOL)
api(user32, "UnregisterClassW", [W.LPCWSTR, W.HINSTANCE], W.BOOL)
api(user32, "UpdateLayeredWindow", [W.HWND, W.HDC, C.POINTER(W.POINT), C.POINTER(W.SIZE), W.HDC,
                                  C.POINTER(W.POINT), W.DWORD, C.POINTER(Blend), W.DWORD], W.BOOL)
api(user32, "GetMessageW", [C.POINTER(W.MSG), W.HWND, W.UINT, W.UINT], C.c_int)
api(user32, "TranslateMessage", [C.POINTER(W.MSG)], W.BOOL)
api(user32, "DispatchMessageW", [C.POINTER(W.MSG)], LRESULT)
api(user32, "PostThreadMessageW", [W.DWORD, W.UINT, WPARAM, LPARAM], W.BOOL)
api(user32, "PeekMessageW", [C.POINTER(W.MSG), W.HWND, W.UINT, W.UINT, W.UINT], W.BOOL)
api(kernel32, "GetModuleHandleW", [W.LPCWSTR], W.HMODULE)
api(kernel32, "GetCurrentThreadId", [], W.DWORD)
api(gdi32, "CreateCompatibleDC", [W.HDC], W.HDC)
api(gdi32, "DeleteDC", [W.HDC], W.BOOL)
api(gdi32, "CreateDIBSection", [W.HDC, C.POINTER(BitmapInfo), W.UINT, C.POINTER(C.c_void_p), W.HANDLE, W.DWORD], W.HBITMAP)
api(gdi32, "SelectObject", [W.HDC, W.HANDLE], W.HANDLE)
api(gdi32, "DeleteObject", [W.HANDLE], W.BOOL)
api(gdi32, "GetStockObject", [C.c_int], W.HANDLE)

WM_WORK, WM_STOP = 0x8001, 0x8002
PASS_THROUGH = 0x20
NO_ACTIVATE = 0x08000000
LAYERED_STYLE = 0x00080000 | 0x00000008 | 0x00000080 | NO_ACTIVATE


def desktop_rect():
    return dict(zip(("left", "top", "width", "height"), (user32.GetSystemMetrics(i) for i in (76, 77, 78, 79))))


class NativeLayer:
    def __init__(self, on_close):
        if sys.getwindowsversion().build < 19041:
            raise AnnotationError("PLATFORM_NOT_SUPPORTED", "标注层需要Windows 10 2004或更新版本。")
        self.previous_dpi = user32.SetThreadDpiAwarenessContext(C.c_void_p(-4))
        if not self.previous_dpi:
            raise AnnotationError("DPI_CONTEXT_UNAVAILABLE", "无法启用物理屏幕坐标。")
        self.on_close = on_close
        self.overlay = self.button = None
        self.surfaces = {}
        self.callback = WNDPROC(self.window_proc)
        self.instance = kernel32.GetModuleHandleW(None)
        self.name = f"TianceAnnotations_{os.getpid()}_{uuid4().hex}"
        definition = WindowClass(cbSize=C.sizeof(WindowClass), lpfnWndProc=self.callback,
                                 hInstance=self.instance, lpszClassName=self.name, hbrBackground=gdi32.GetStockObject(4))
        if not user32.RegisterClassExW(C.byref(definition)):
            raise C.WinError(C.get_last_error())

    def window_proc(self, hwnd, message, wparam, lparam):
        if message == 0x0084 and hwnd in (self.overlay, self.surfaces.get(self.overlay)):  # WM_NCHITTEST
            return -1
        if message == 0x0021:  # WM_MOUSEACTIVATE
            return 3  # MA_NOACTIVATE: button receives clicks without foreground activation.
        if (message == 0x0202 and hwnd in (self.button, self.surfaces.get(self.button))) or message == 0x0010:
            try:
                self.on_close()
            except Exception:
                # User's close action must always remove the visible layer.
                self.destroy_windows()
            return 0
        return int(user32.DefWindowProcW(hwnd, message, wparam, lparam))

    def create(self, rect, *, button=False):
        # Windows hit-tests the host before its alpha child. A color-keyed,
        # entirely transparent host makes even an opaque button child click-through.
        style = (LAYERED_STYLE & ~0x00080000) if button else (LAYERED_STYLE | PASS_THROUGH)
        hwnd = user32.CreateWindowExW(style, self.name, "关闭全部标注" if button else "GUI 标注层", 0x80000000,
                                     rect["left"], rect["top"], rect["width"], rect["height"], None, None, self.instance, None)
        if not hwnd:
            raise C.WinError(C.get_last_error())
        try:
            # Only the drawing host uses a transparent color key. The close button
            # has a normal interactive host; both exclude their alpha child from capture.
            if not button and not user32.SetLayeredWindowAttributes(hwnd, 0, 255, 1):
                raise C.WinError(C.get_last_error())
            affinity = W.DWORD()
            if not user32.SetWindowDisplayAffinity(hwnd, 0x11) or not user32.GetWindowDisplayAffinity(hwnd, C.byref(affinity)) or affinity.value != 0x11:
                raise AnnotationError("CAPTURE_EXCLUSION_UNAVAILABLE", "无法从后续GUI截图中排除标注层。")
            child = user32.CreateWindowExW(0x00080000 | NO_ACTIVATE | (0 if button else PASS_THROUGH), self.name,
                                          "GUI annotation pixels", 0x40000000, 0, 0, rect["width"], rect["height"],
                                          hwnd, None, self.instance, None)
            if not child:
                raise C.WinError(C.get_last_error())
            self.surfaces[hwnd] = child
            return hwnd
        except BaseException:
            user32.DestroyWindow(hwnd)
            raise

    def upload(self, hwnd, rect, image):
        surface = self.surfaces[hwnd]
        if not user32.SetWindowPos(hwnd, W.HWND(-1), rect["left"], rect["top"], image.width, image.height, 0x10):
            raise C.WinError(C.get_last_error())
        pixels = image.convert("RGBa").tobytes("raw", "BGRa")
        info = BitmapInfo(header=BitmapHeader(size=C.sizeof(BitmapHeader), width=image.width, height=-image.height,
                                            planes=1, bits=32, image_size=len(pixels)))
        dc = gdi32.CreateCompatibleDC(None)
        if not dc:
            raise C.WinError(C.get_last_error())
        bitmap = old = None
        try:
            bits = C.c_void_p()
            bitmap = gdi32.CreateDIBSection(dc, C.byref(info), 0, C.byref(bits), None, 0)
            if not bitmap or not bits.value:
                raise C.WinError(C.get_last_error())
            old = gdi32.SelectObject(dc, bitmap)
            if not old or old == C.c_void_p(-1).value:
                old = None
                raise C.WinError(C.get_last_error())
            C.memmove(bits, pixels, len(pixels))
            destination, source = W.POINT(0, 0), W.POINT(0, 0)
            size, blend = W.SIZE(image.width, image.height), Blend(0, 0, 255, 1)
            if not user32.UpdateLayeredWindow(surface, None, C.byref(destination), C.byref(size), dc, C.byref(source), 0, C.byref(blend), 2):
                raise C.WinError(C.get_last_error())
        finally:
            if old:
                gdi32.SelectObject(dc, old)
            if bitmap:
                gdi32.DeleteObject(bitmap)
            gdi32.DeleteDC(dc)

    def update(self, items):
        if not items:
            self.destroy_windows()
            return
        rect = desktop_rect()
        image = render(rect, items)
        if not self.overlay:
            self.overlay = self.create(rect)
        self.upload(self.overlay, rect, image)
        button_rect = {"left": max(0, user32.GetSystemMetrics(0) - 200), "top": 12, "width": 184, "height": 36}
        if not self.button:
            self.button = self.create(button_rect, button=True)
        image = Image.new("RGBA", (184, 36))
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((0, 0, 183, 35), radius=8, fill=(35, 35, 35, 245), outline=(230, 230, 230, 255))
        draw.text((92, 18), "关闭全部标注 ×", font=font(16), fill="white", anchor="mm")
        self.upload(self.button, button_rect, image)
        for hwnd in (self.overlay, self.button):
            user32.ShowWindow(self.surfaces[hwnd], 4)
            user32.ShowWindow(hwnd, 4)
            if not user32.SetWindowPos(hwnd, W.HWND(-1), 0, 0, 0, 0, 0x13):
                raise C.WinError(C.get_last_error())

    def destroy_windows(self):
        for name in ("button", "overlay"):
            hwnd = getattr(self, name)
            setattr(self, name, None)
            if hwnd:
                user32.DestroyWindow(hwnd)
                self.surfaces.pop(hwnd, None)

    def close(self):
        self.destroy_windows()
        user32.UnregisterClassW(self.name, self.instance)
        user32.SetThreadDpiAwarenessContext(self.previous_dpi)
