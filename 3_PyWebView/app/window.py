import sys
from dataclasses import dataclass

from app.config import ShellSettings
from app.runtime import LaunchTarget
from app.startup_theme import load_startup_theme


@dataclass(frozen=True)
class WindowPosition:
    x: int
    y: int


def build_window_options(settings: ShellSettings) -> dict[str, object]:
    startup_theme = load_startup_theme()
    options: dict[str, object] = {
        "title": settings.title,
        "width": settings.width,
        "height": settings.height,
        "min_size": (settings.min_width, settings.min_height),
        "frameless": settings.frameless,
        "easy_drag": settings.easy_drag,
        "shadow": settings.shadow,
        "hidden": True,
        "background_color": startup_theme.window_background or settings.background_color,
        "text_select": True,
    }

    position = _resolve_centered_initial_position(settings)
    if position is not None:
        options["x"] = position.x
        options["y"] = position.y

    return options


def build_entrypoint(target: LaunchTarget) -> dict[str, str]:
    if target.url:
        return {"url": target.url}

    return {"html": target.html or ""}


def _resolve_centered_initial_position(settings: ShellSettings) -> WindowPosition | None:
    work_area = _get_primary_work_area()
    if work_area is None:
        return None

    left, top, right, bottom = work_area
    work_width = max(1, right - left)
    work_height = max(1, bottom - top)
    x = left + max(0, (work_width - settings.width) // 2)
    y = top + max(0, (work_height - settings.height) // 2)
    return WindowPosition(x=x, y=y)


def _get_primary_work_area() -> tuple[int, int, int, int] | None:
    if sys.platform != "win32":
        return None

    import ctypes

    SPI_GETWORKAREA = 0x0030

    class Rect(ctypes.Structure):
        _fields_ = [
            ("left", ctypes.c_long),
            ("top", ctypes.c_long),
            ("right", ctypes.c_long),
            ("bottom", ctypes.c_long),
        ]

    rect = Rect()
    if not ctypes.windll.user32.SystemParametersInfoW(
        SPI_GETWORKAREA,
        0,
        ctypes.byref(rect),
        0,
    ):
        return None

    return (int(rect.left), int(rect.top), int(rect.right), int(rect.bottom))
