from __future__ import annotations

from typing import Any

from openpyxl.formatting.rule import CellIsRule, ColorScaleRule, DataBarRule, FormulaRule, IconSetRule

from excel_styles import build_border, build_fill, build_font, normalize_color


def add_conditional_format(ws: Any, spec: dict[str, Any]) -> None:
    target_range = str(spec.get("range") or "").strip()
    rule_type = str(spec.get("type") or "").strip().lower()
    if not target_range:
        raise ValueError("条件格式缺少 range。")
    if rule_type == "color_scale":
        rule = _color_scale_rule(spec)
    elif rule_type == "data_bar":
        rule = _data_bar_rule(spec)
    elif rule_type == "icon_set":
        rule = _icon_set_rule(spec)
    elif rule_type == "cell_is":
        rule = _cell_is_rule(spec)
    elif rule_type == "formula":
        rule = _formula_rule(spec)
    else:
        raise ValueError(f"不支持的条件格式类型：{rule_type}")
    ws.conditional_formatting.add(target_range, rule)


def _color_scale_rule(spec: dict[str, Any]) -> Any:
    colors = _read_colors(spec.get("colors"), ["F8696B", "FFEB84", "63BE7B"])
    if len(colors) == 2:
        return ColorScaleRule(
            start_type=str(spec.get("start_type") or "min"),
            start_value=spec.get("start_value"),
            start_color=colors[0],
            end_type=str(spec.get("end_type") or "max"),
            end_value=spec.get("end_value"),
            end_color=colors[1],
        )
    return ColorScaleRule(
        start_type=str(spec.get("start_type") or "min"),
        start_value=spec.get("start_value"),
        start_color=colors[0],
        mid_type=str(spec.get("mid_type") or "percentile"),
        mid_value=spec.get("mid_value", 50),
        mid_color=colors[1],
        end_type=str(spec.get("end_type") or "max"),
        end_value=spec.get("end_value"),
        end_color=colors[2],
    )


def _data_bar_rule(spec: dict[str, Any]) -> Any:
    return DataBarRule(
        start_type=str(spec.get("start_type") or "min"),
        start_value=spec.get("start_value"),
        end_type=str(spec.get("end_type") or "max"),
        end_value=spec.get("end_value"),
        color=normalize_color(spec.get("color")) or "638EC6",
        showValue=_read_bool(spec.get("show_value"), True),
    )


def _icon_set_rule(spec: dict[str, Any]) -> Any:
    values = spec.get("values")
    if not isinstance(values, list) or not values:
        values = [0, 33, 67]
    return IconSetRule(
        icon_style=str(spec.get("icon_style") or "3TrafficLights1"),
        type=str(spec.get("value_type") or "percent"),
        values=values,
        showValue=_read_bool(spec.get("show_value"), True),
        percent=None,
        reverse=_read_bool(spec.get("reverse"), False),
    )


def _cell_is_rule(spec: dict[str, Any]) -> Any:
    return CellIsRule(
        operator=str(spec.get("operator") or "greaterThan"),
        formula=_read_formula_list(spec),
        stopIfTrue=_read_bool(spec.get("stop_if_true"), False),
        font=build_font((spec.get("style") or {}).get("font")),
        border=build_border((spec.get("style") or {}).get("border")),
        fill=build_fill((spec.get("style") or {}).get("fill")),
    )


def _formula_rule(spec: dict[str, Any]) -> Any:
    return FormulaRule(
        formula=_read_formula_list(spec),
        stopIfTrue=_read_bool(spec.get("stop_if_true"), False),
        font=build_font((spec.get("style") or {}).get("font")),
        border=build_border((spec.get("style") or {}).get("border")),
        fill=build_fill((spec.get("style") or {}).get("fill")),
    )


def _read_formula_list(spec: dict[str, Any]) -> list[str]:
    formula = spec.get("formula")
    if isinstance(formula, list):
        return [str(item) for item in formula]
    if isinstance(formula, str):
        return [formula]
    return ["0"]


def _read_colors(value: Any, defaults: list[str]) -> list[str]:
    if not isinstance(value, list):
        return defaults
    colors = [color for item in value if (color := normalize_color(item))]
    if len(colors) < 2:
        return defaults
    return colors[:3]


def _read_bool(value: Any, default: bool) -> bool:
    return value if isinstance(value, bool) else default
