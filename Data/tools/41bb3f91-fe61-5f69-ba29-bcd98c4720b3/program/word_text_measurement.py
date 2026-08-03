from __future__ import annotations

import ctypes
import os
import unicodedata
from ctypes import wintypes
from typing import Any


class FontTextMeasurer:
    def __init__(self, *, font_name: str, size_points: float) -> None:
        self._font_name = font_name
        self._cache: dict[tuple[str, bool], float] = {}
        self._backend: Any = _create_measurement_backend(size_points)
        self.backend = self._backend.name

    def measure(self, text: str, *, bold: bool = False) -> float:
        key = (text, bold)
        cached = self._cache.get(key)
        if cached is None:
            cached = self._backend.measure(text, self._font_name, bold=bold)
            self._cache[key] = cached
        return cached

    def close(self) -> None:
        self._backend.close()

    def __enter__(self) -> "FontTextMeasurer":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()


def is_east_asian_character(char: str) -> bool:
    codepoint = ord(char)
    return (
        0x2E80 <= codepoint <= 0x9FFF
        or 0xAC00 <= codepoint <= 0xD7AF
        or 0xF900 <= codepoint <= 0xFAFF
        or 0x20000 <= codepoint <= 0x3134F
        or unicodedata.east_asian_width(char) in {"W", "F"}
    )


class _Size(ctypes.Structure):
    _fields_ = [("cx", wintypes.LONG), ("cy", wintypes.LONG)]


def _create_measurement_backend(size_points: float) -> Any:
    if os.name == "nt":
        try:
            return _WindowsGdiBackend(size_points)
        except OSError:
            pass
    return _HeuristicBackend(size_points)


class _WindowsGdiBackend:
    name = "windows-gdi"

    def __init__(self, size_points: float) -> None:
        self._gdi = ctypes.windll.gdi32
        self._gdi.CreateCompatibleDC.argtypes = [wintypes.HDC]
        self._gdi.CreateCompatibleDC.restype = wintypes.HDC
        self._gdi.DeleteDC.argtypes = [wintypes.HDC]
        self._gdi.DeleteDC.restype = wintypes.BOOL
        self._gdi.GetDeviceCaps.argtypes = [wintypes.HDC, ctypes.c_int]
        self._gdi.GetDeviceCaps.restype = ctypes.c_int
        self._gdi.CreateFontW.restype = wintypes.HFONT
        self._gdi.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
        self._gdi.SelectObject.restype = wintypes.HGDIOBJ
        self._gdi.DeleteObject.argtypes = [wintypes.HGDIOBJ]
        self._gdi.DeleteObject.restype = wintypes.BOOL
        self._gdi.GetTextExtentPoint32W.argtypes = [wintypes.HDC, wintypes.LPCWSTR, ctypes.c_int, ctypes.POINTER(_Size)]
        self._gdi.GetTextExtentPoint32W.restype = wintypes.BOOL
        self._dc = self._gdi.CreateCompatibleDC(None)
        if not self._dc:
            raise OSError("无法创建字体测量上下文。")
        self._dpi = self._gdi.GetDeviceCaps(self._dc, 90) or 96
        self._height = -max(1, round(size_points * self._dpi / 72.0))
        self._fonts: dict[bool, int] = {}

    def measure(self, text: str, font_name: str, *, bold: bool) -> float:
        font = self._fonts.get(bold)
        if not font:
            font = self._gdi.CreateFontW(
                self._height, 0, 0, 0, 700 if bold else 400,
                False, False, False, 1, 0, 0, 0, 0, font_name,
            )
            if not font:
                raise OSError(f"无法创建字体：{font_name}")
            self._fonts[bold] = font
        previous = self._gdi.SelectObject(self._dc, font)
        size = _Size()
        try:
            length = len(text.encode("utf-16-le")) // 2
            if not self._gdi.GetTextExtentPoint32W(self._dc, text, length, ctypes.byref(size)):
                raise OSError(f"无法测量字体：{font_name}")
            return max(0.0, size.cx * 72.0 / self._dpi)
        finally:
            self._gdi.SelectObject(self._dc, previous)

    def close(self) -> None:
        for font in self._fonts.values():
            self._gdi.DeleteObject(font)
        self._gdi.DeleteDC(self._dc)


class _HeuristicBackend:
    name = "unicode-heuristic"

    def __init__(self, size_points: float) -> None:
        self._size_points = size_points

    def measure(self, text: str, font_name: str, *, bold: bool) -> float:
        del font_name
        width = sum(
            self._size_points
            * (1.0 if is_east_asian_character(char) else 0.28 if char.isspace() else 0.35 if unicodedata.category(char).startswith("P") else 0.52)
            for char in text
        )
        return width * (1.04 if bold else 1.0)

    def close(self) -> None:
        return
