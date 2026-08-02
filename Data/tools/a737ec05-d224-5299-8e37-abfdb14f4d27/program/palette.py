from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any


HEX_COLOR_PATTERN = re.compile(r"^#[0-9a-fA-F]{6}$")
PALETTE_FIELDS = ("background", "panel", "text", "accent")


class PaletteError(ValueError):
    pass


@dataclass(frozen=True)
class Rgb:
    red: int
    green: int
    blue: int


def derive_theme_palette(value: Any, *, mode: str) -> dict[str, str]:
    palette = read_palette(value)
    if mode not in {"dark", "light"}:
        raise PaletteError("主题 mode 必须是 dark 或 light。")

    background = palette["background"]
    panel = palette["panel"]
    text = palette["text"]
    accent = palette["accent"]
    is_dark = mode == "dark"
    strong_pole = "#FFFFFF" if is_dark else "#000000"
    surface_pole = "#FFFFFF"
    accent_hover = mix(accent, strong_pole, 0.14)
    inverse_text = best_contrast_color(accent)
    danger = semantic_color("#D84A4A", is_dark=is_dark)
    warning = semantic_color("#C58A24", is_dark=is_dark)
    success = semantic_color("#3F9363", is_dark=is_dark)

    return {
        "surface_base": background,
        "surface_panel": panel,
        "surface_panel_alt": mix(panel, background, 0.28),
        "surface_toolbar": mix(panel, background, 0.18),
        "surface_titlebar": mix(panel, background, 0.30),
        "surface_statusbar": mix(background, text, 0.08),
        "surface_sidebar": mix(panel, background, 0.12),
        "surface_canvas": mix(panel, surface_pole, 0.06 if is_dark else 0.34),
        "surface_elevated": mix(panel, surface_pole, 0.10 if is_dark else 0.48),
        "surface_muted": mix(background, text, 0.08),
        "surface_overlay": rgba(text, 0.30 if is_dark else 0.22),
        "surface_menu": mix(panel, surface_pole, 0.12 if is_dark else 0.55),
        "surface_input": mix(panel, surface_pole, 0.06 if is_dark else 0.60),
        "surface_input_hover": mix(panel, surface_pole, 0.11 if is_dark else 0.78),
        "surface_item_hover": rgba(accent, 0.11),
        "surface_item_hover_strong": rgba(accent, 0.20),
        "text_primary": text,
        "text_secondary": mix(text, background, 0.28),
        "text_muted": mix(text, background, 0.48),
        "text_heading": mix(text, strong_pole, 0.10),
        "text_heading_accent": mix(accent, text, 0.18),
        "text_inverse": inverse_text,
        "text_selection_text": inverse_text,
        "border_soft": rgba(text, 0.20),
        "border_subtle": rgba(text, 0.12),
        "border_strong": rgba(text, 0.34),
        "border_focus": accent,
        "border_separator": rgba(text, 0.16),
        "accent_base": accent,
        "accent_rgb": rgb_triplet(accent),
        "accent_hover": accent_hover,
        "accent_text": mix(accent, text, 0.16),
        "accent_soft_text": mix(accent, text, 0.42),
        "accent_selection_text": inverse_text,
        "accent_selection_bg_subtle": rgba(accent, 0.12),
        "accent_selection_bg": accent,
        "accent_selection_bg_hover": accent_hover,
        "accent_selection_border": rgba(accent, 0.62),
        "accent_text_selection_bg": rgba(accent, 0.78),
        "state_danger": danger,
        "state_danger_text": mix(danger, text, 0.18),
        "state_danger_soft_text": mix(danger, text, 0.42),
        "state_danger_bg": rgba(danger, 0.14),
        "state_danger_border": rgba(danger, 0.42),
        "state_warning": warning,
        "state_warning_text": mix(warning, text, 0.24),
        "state_success": success,
        "state_success_text": mix(success, text, 0.24),
        "collapse_fade_start": rgba(panel, 0),
        "collapse_fade_mid": rgba(panel, 0.84),
        "collapse_fade_end": rgba(panel, 1),
        "collapse_caret": mix(text, background, 0.42),
        "scrollbar_track": "transparent",
        "scrollbar_thumb": rgba(text, 0.26),
        "scrollbar_thumb_hover": rgba(accent, 0.54),
        "structure_color": rgba(text, 0.16),
        "structure_hover_color": rgba(accent, 0.48),
        "structure_active_color": accent,
        "shadow_floating": f"0 18px 46px {rgba('#000000', 0.40 if is_dark else 0.19)}",
        "shadow_panel": f"0 5px 22px {rgba('#000000', 0.28 if is_dark else 0.11)}",
        "editor_background": mix(background, panel, 0.45),
        "editor_foreground": text,
        "editor_gutter_background": mix(background, panel, 0.70),
        "editor_gutter_foreground": mix(text, background, 0.50),
        "editor_active_line": rgba(accent, 0.09),
        "editor_selection_match": rgba(warning, 0.28),
        "editor_tooltip_background": mix(panel, surface_pole, 0.12 if is_dark else 0.62),
    }


def read_palette(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        raise PaletteError("palette 必须是包含 background、panel、text、accent 的对象。")
    unexpected = sorted(str(key) for key in value if key not in PALETTE_FIELDS)
    if unexpected:
        raise PaletteError(f"palette 包含不支持的字段：{', '.join(unexpected)}。")
    missing = [field for field in PALETTE_FIELDS if field not in value]
    if missing:
        raise PaletteError(f"palette 缺少必填字段：{', '.join(missing)}。")
    return {
        field: normalize_hex_color(value[field], field_name=f"palette.{field}")
        for field in PALETTE_FIELDS
    }


def normalize_hex_color(value: Any, *, field_name: str) -> str:
    text = str(value or "").strip()
    if not HEX_COLOR_PATTERN.fullmatch(text):
        raise PaletteError(f"{field_name} 必须是 #RRGGBB 格式的十六进制颜色。")
    return text.upper()


def mix(first: str, second: str, amount: float) -> str:
    left = parse_hex_color(first)
    right = parse_hex_color(second)
    ratio = min(1.0, max(0.0, amount))
    return to_hex_color(
        Rgb(
            red=round(left.red * (1 - ratio) + right.red * ratio),
            green=round(left.green * (1 - ratio) + right.green * ratio),
            blue=round(left.blue * (1 - ratio) + right.blue * ratio),
        )
    )


def rgba(color: str, alpha: float) -> str:
    rgb = parse_hex_color(color)
    normalized_alpha = min(1.0, max(0.0, alpha))
    alpha_text = f"{normalized_alpha:.3f}".rstrip("0").rstrip(".")
    return f"rgba({rgb.red}, {rgb.green}, {rgb.blue}, {alpha_text})"


def rgb_triplet(color: str) -> str:
    rgb = parse_hex_color(color)
    return f"{rgb.red}, {rgb.green}, {rgb.blue}"


def best_contrast_color(color: str) -> str:
    rgb = parse_hex_color(color)
    luminance = relative_luminance(rgb)
    black_contrast = (luminance + 0.05) / 0.05
    white_contrast = 1.05 / (luminance + 0.05)
    return "#000000" if black_contrast >= white_contrast else "#FFFFFF"


def semantic_color(color: str, *, is_dark: bool) -> str:
    return mix(color, "#FFFFFF" if is_dark else "#000000", 0.12)


def parse_hex_color(value: str) -> Rgb:
    normalized = normalize_hex_color(value, field_name="color")
    return Rgb(
        red=int(normalized[1:3], 16),
        green=int(normalized[3:5], 16),
        blue=int(normalized[5:7], 16),
    )


def to_hex_color(value: Rgb) -> str:
    return f"#{value.red:02X}{value.green:02X}{value.blue:02X}"


def relative_luminance(value: Rgb) -> float:
    channels = [
        _linear_channel(value.red / 255),
        _linear_channel(value.green / 255),
        _linear_channel(value.blue / 255),
    ]
    return channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722


def _linear_channel(value: float) -> float:
    if value <= 0.04045:
        return value / 12.92
    return ((value + 0.055) / 1.055) ** 2.4
