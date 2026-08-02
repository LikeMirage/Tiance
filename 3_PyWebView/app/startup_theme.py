"""Read-only boot snapshot adapter for backend-owned theme files.

The backend owns theme writes and validation. The shell reads only the versioned
color subset needed before the backend and React application are ready.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
from typing import Any

from app.config import PROJECT_ROOT
from app.startup_timing import mark


DEFAULT_THEME_ID = "dark-gold"
THEME_SETTINGS_FILE = "theme-settings.json"
THEME_MANIFEST_FILE = "theme.json"
THEME_SETTINGS_SCHEMA_VERSION = 1
THEME_MANIFEST_SCHEMA_VERSION = 2
THEME_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
CSS_COLOR_PATTERN = re.compile(r"^[#(),.%\w\s-]+$")


@dataclass(frozen=True)
class StartupTheme:
    mode: str
    surface_base: str
    window_background: str
    surface_titlebar: str
    border_separator: str
    text_primary: str
    text_muted: str
    accent: str
    accent_rgb: str
    danger_text: str
    danger_border: str


DEFAULT_STARTUP_THEME = StartupTheme(
    mode="dark",
    surface_base="rgb(30, 30, 30)",
    window_background="#1e1e1e",
    surface_titlebar="rgb(25, 25, 25)",
    border_separator="rgba(255, 255, 255, 0.06)",
    text_primary="#f3f4f7",
    text_muted="rgba(243, 244, 247, 0.58)",
    accent="#dea059",
    accent_rgb="222, 160, 89",
    danger_text="#fecaca",
    danger_border="rgba(239, 68, 68, 0.2)",
)


def load_startup_theme() -> StartupTheme:
    theme_id = _read_active_theme_id() or DEFAULT_THEME_ID
    theme = _load_theme(theme_id)
    if theme is not None:
        return theme

    if theme_id != DEFAULT_THEME_ID:
        theme = _load_theme(DEFAULT_THEME_ID)
        if theme is not None:
            return theme

    return DEFAULT_STARTUP_THEME


def _read_active_theme_id() -> str | None:
    themes_root = _resolve_project_path(os.getenv("THEMES_DATA_DIR", "Data/themes"))
    settings_path = themes_root / THEME_SETTINGS_FILE
    if not settings_path.is_file():
        return None

    try:
        payload = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    if not isinstance(payload, dict):
        return None

    if payload.get("schemaVersion") != THEME_SETTINGS_SCHEMA_VERSION:
        mark(
            "startup snapshot: unsupported theme settings version",
            expected=THEME_SETTINGS_SCHEMA_VERSION,
            actual=payload.get("schemaVersion"),
        )
        return None

    theme_id = str(payload.get("activeThemeId") or "").strip()
    if not THEME_ID_PATTERN.fullmatch(theme_id):
        return None

    return theme_id


def _load_theme(theme_id: str) -> StartupTheme | None:
    if not THEME_ID_PATTERN.fullmatch(theme_id):
        return None

    themes_root = _resolve_project_path(os.getenv("THEMES_DATA_DIR", "Data/themes"))
    theme_file = themes_root / theme_id / THEME_MANIFEST_FILE
    if not theme_file.is_file():
        return None

    try:
        payload = json.loads(theme_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    if not isinstance(payload, dict):
        return None

    if payload.get("schemaVersion") != THEME_MANIFEST_SCHEMA_VERSION:
        mark(
            "startup snapshot: unsupported theme manifest version",
            theme_id=theme_id,
            expected=THEME_MANIFEST_SCHEMA_VERSION,
            actual=payload.get("schemaVersion"),
        )
        return None

    try:
        color = payload["tokens"]["color"]
        surface = color["surface"]
        text = color["text"]
        border = color["border"]
        accent = color["accent"]
        state = color["state"]
        surface_base = _read_css_color(surface.get("base"), DEFAULT_STARTUP_THEME.surface_base)
        return StartupTheme(
            mode=_read_mode(payload.get("mode")),
            surface_base=surface_base,
            window_background=_read_window_background(
                surface_base,
                DEFAULT_STARTUP_THEME.window_background,
            ),
            surface_titlebar=_read_css_color(
                surface.get("titlebar"),
                DEFAULT_STARTUP_THEME.surface_titlebar,
            ),
            border_separator=_read_css_color(
                border.get("separator"),
                DEFAULT_STARTUP_THEME.border_separator,
            ),
            text_primary=_read_css_color(text.get("primary"), DEFAULT_STARTUP_THEME.text_primary),
            text_muted=_read_css_color(text.get("muted"), DEFAULT_STARTUP_THEME.text_muted),
            accent=_read_css_color(accent.get("base"), DEFAULT_STARTUP_THEME.accent),
            accent_rgb=_read_rgb(accent.get("rgb"), DEFAULT_STARTUP_THEME.accent_rgb),
            danger_text=_read_css_color(state.get("dangerText"), DEFAULT_STARTUP_THEME.danger_text),
            danger_border=_read_css_color(
                state.get("dangerBorder"),
                DEFAULT_STARTUP_THEME.danger_border,
            ),
        )
    except (KeyError, TypeError):
        return None


def _read_mode(value: Any) -> str:
    return "light" if value == "light" else "dark"


def _read_css_color(value: Any, fallback: str) -> str:
    if not isinstance(value, str):
        return fallback

    color = value.strip()
    if not color or not CSS_COLOR_PATTERN.fullmatch(color):
        return fallback
    return color


def _read_rgb(value: Any, fallback: str) -> str:
    if not isinstance(value, str):
        return fallback

    rgb = value.strip()
    parts = [part.strip() for part in rgb.split(",")]
    if len(parts) != 3:
        return fallback

    try:
        values = [int(part) for part in parts]
    except ValueError:
        return fallback

    if any(value < 0 or value > 255 for value in values):
        return fallback

    return ", ".join(str(value) for value in values)


def _read_window_background(value: str, fallback: str) -> str:
    color = value.strip()
    if re.fullmatch(r"#[0-9a-fA-F]{6}", color):
        return color

    rgb_match = re.fullmatch(
        r"rgb\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*\)",
        color,
        flags=re.IGNORECASE,
    )
    if rgb_match is None:
        return fallback

    values = [int(part) for part in rgb_match.groups()]
    if any(part < 0 or part > 255 for part in values):
        return fallback

    return "#" + "".join(f"{part:02x}" for part in values)


def _resolve_project_path(raw_path: str) -> Path:
    path = Path(raw_path).expanduser()
    if path.is_absolute():
        return path.resolve()
    return (PROJECT_ROOT / path).resolve()
