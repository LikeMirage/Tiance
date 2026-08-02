from __future__ import annotations

import ctypes
import os
import unicodedata
from ctypes import wintypes
from typing import Literal, Protocol


FontRole = Literal["text", "math", "code"]


class TextMeasurer(Protocol):
    backend: str

    def measure(self, text: str, *, role: FontRole = "text", bold: bool = False) -> float: ...


class FontTextMeasurer:
    """Measures text in points with the same font roles used by the Word writer."""

    def __init__(
        self,
        *,
        chinese_font: str,
        english_font: str,
        math_font: str,
        size_points: float,
        code_font: str = "Consolas",
    ) -> None:
        self._font_names = {
            "chinese": chinese_font,
            "english": english_font,
            "math": math_font,
            "code": code_font,
        }
        self._size_points = size_points
        self._cache: dict[tuple[str, FontRole, bool], float] = {}
        self._backend = _create_backend(size_points)
        self.backend = self._backend.name

    def measure(self, text: str, *, role: FontRole = "text", bold: bool = False) -> float:
        if not text:
            return 0.0
        key = (text, role, bold)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        if role == "text":
            width = sum(
                self._backend.measure(run, self._font_names[font_role], bold=bold)
                for font_role, run in _font_runs(text)
            )
        else:
            width = self._backend.measure(text, self._font_names[role], bold=bold)
        self._cache[key] = width
        return width

    def close(self) -> None:
        self._backend.close()

    def __enter__(self) -> FontTextMeasurer:
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()


def is_east_asian_character(char: str) -> bool:
    if not char:
        return False
    codepoint = ord(char)
    if (
        0x2E80 <= codepoint <= 0x9FFF
        or 0xAC00 <= codepoint <= 0xD7AF
        or 0xF900 <= codepoint <= 0xFAFF
        or 0xFE30 <= codepoint <= 0xFE4F
        or 0xFF00 <= codepoint <= 0xFFEF
        or 0x20000 <= codepoint <= 0x3134F
    ):
        return True
    return unicodedata.east_asian_width(char) in {"W", "F"}


def _font_runs(text: str) -> list[tuple[str, str]]:
    runs: list[tuple[str, str]] = []
    current_role = "chinese" if is_east_asian_character(text[0]) else "english"
    start = 0
    for index, char in enumerate(text[1:], start=1):
        role = "chinese" if is_east_asian_character(char) else "english"
        if role == current_role:
            continue
        runs.append((current_role, text[start:index]))
        current_role = role
        start = index
    runs.append((current_role, text[start:]))
    return runs


class _MeasurementBackend(Protocol):
    name: str

    def measure(self, text: str, font_name: str, *, bold: bool) -> float: ...

    def close(self) -> None: ...


def _create_backend(size_points: float) -> _MeasurementBackend:
    if os.name == "nt":
        try:
            return _WindowsGdiBackend(size_points)
        except OSError:
            pass
    return _HeuristicBackend(size_points)


class _Size(ctypes.Structure):
    _fields_ = [("cx", wintypes.LONG), ("cy", wintypes.LONG)]


class _WindowsGdiBackend:
    name = "windows-gdi"
    _LOGPIXELSY = 90
    _DEFAULT_CHARSET = 1
    _FW_NORMAL = 400
    _FW_BOLD = 700

    def __init__(self, size_points: float) -> None:
        self._gdi = ctypes.windll.gdi32
        self._configure_signatures()
        self._dc = self._gdi.CreateCompatibleDC(None)
        if not self._dc:
            raise OSError("无法创建字体测量设备上下文。")
        self._dpi = self._gdi.GetDeviceCaps(self._dc, self._LOGPIXELSY) or 96
        self._height = -max(1, round(size_points * self._dpi / 72.0))
        self._fonts: dict[tuple[str, bool], int] = {}
        self._closed = False

    def measure(self, text: str, font_name: str, *, bold: bool) -> float:
        if self._closed:
            raise RuntimeError("字体测量器已经关闭。")
        font = self._font(font_name, bold)
        previous = self._gdi.SelectObject(self._dc, font)
        if not previous:
            raise OSError(f"无法选择字体：{font_name}")
        try:
            size = _Size()
            utf16_length = len(text.encode("utf-16-le")) // 2
            if not self._gdi.GetTextExtentPoint32W(
                self._dc,
                text,
                utf16_length,
                ctypes.byref(size),
            ):
                raise OSError(f"无法测量字体：{font_name}")
            return max(0.0, size.cx * 72.0 / self._dpi)
        finally:
            self._gdi.SelectObject(self._dc, previous)

    def close(self) -> None:
        if self._closed:
            return
        for font in self._fonts.values():
            self._gdi.DeleteObject(font)
        self._fonts.clear()
        self._gdi.DeleteDC(self._dc)
        self._closed = True

    def _font(self, font_name: str, bold: bool) -> int:
        key = (font_name, bold)
        font = self._fonts.get(key)
        if font:
            return font
        font = self._gdi.CreateFontW(
            self._height,
            0,
            0,
            0,
            self._FW_BOLD if bold else self._FW_NORMAL,
            False,
            False,
            False,
            self._DEFAULT_CHARSET,
            0,
            0,
            0,
            0,
            font_name,
        )
        if not font:
            raise OSError(f"无法创建字体：{font_name}")
        self._fonts[key] = font
        return font

    def _configure_signatures(self) -> None:
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
        self._gdi.GetTextExtentPoint32W.argtypes = [
            wintypes.HDC,
            wintypes.LPCWSTR,
            ctypes.c_int,
            ctypes.POINTER(_Size),
        ]
        self._gdi.GetTextExtentPoint32W.restype = wintypes.BOOL


class _HeuristicBackend:
    name = "unicode-heuristic"

    def __init__(self, size_points: float) -> None:
        self._size_points = size_points

    def measure(self, text: str, font_name: str, *, bold: bool) -> float:
        width = 0.0
        for char in text:
            if is_east_asian_character(char):
                factor = 1.0
            elif char.isspace():
                factor = 0.28
            elif unicodedata.category(char).startswith("P"):
                factor = 0.35
            else:
                factor = 0.52
            width += self._size_points * factor
        return width * (1.04 if bold else 1.0)

    def close(self) -> None:
        return
