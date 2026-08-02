from __future__ import annotations

from typing import Any

from openpyxl.chart import AreaChart, BarChart, LineChart, PieChart, Reference
from openpyxl.utils.cell import range_boundaries


def add_chart(ws: Any, spec: dict[str, Any]) -> None:
    chart_type = str(spec.get("type") or "").strip().lower()
    chart = _create_chart(chart_type)
    data_ref = _reference(ws, str(spec["data_range"]))
    titles_from_data = _read_bool(spec.get("titles_from_data"), True)
    from_rows = _read_bool(spec.get("from_rows"), False)

    chart.add_data(data_ref, titles_from_data=titles_from_data, from_rows=from_rows)
    categories_range = spec.get("categories_range")
    if isinstance(categories_range, str) and categories_range.strip():
        chart.set_categories(_reference(ws, categories_range))

    if isinstance(spec.get("title"), str):
        chart.title = spec["title"]
    if chart_type == "bar":
        direction = str(spec.get("bar_direction") or "col")
        chart.type = "bar" if direction == "bar" else "col"
    if isinstance(spec.get("x_axis_title"), str) and hasattr(chart, "x_axis"):
        chart.x_axis.title = spec["x_axis_title"]
    if isinstance(spec.get("y_axis_title"), str) and hasattr(chart, "y_axis"):
        chart.y_axis.title = spec["y_axis_title"]
    if isinstance(spec.get("height"), (int, float)):
        chart.height = spec["height"]
    if isinstance(spec.get("width"), (int, float)):
        chart.width = spec["width"]
    if isinstance(spec.get("style"), int):
        chart.style = spec["style"]
    if isinstance(spec.get("legend_position"), str) and chart.legend is not None:
        chart.legend.position = spec["legend_position"]

    anchor = str(spec.get("anchor") or "J2")
    ws.add_chart(chart, anchor)


def _create_chart(chart_type: str) -> Any:
    if chart_type == "bar":
        return BarChart()
    if chart_type == "line":
        return LineChart()
    if chart_type == "pie":
        return PieChart()
    if chart_type == "area":
        return AreaChart()
    raise ValueError(f"不支持的图表类型：{chart_type}")


def _reference(ws: Any, range_text: str) -> Reference:
    cleaned = _strip_sheet_name(range_text)
    min_col, min_row, max_col, max_row = range_boundaries(cleaned)
    return Reference(ws, min_col=min_col, min_row=min_row, max_col=max_col, max_row=max_row)


def _strip_sheet_name(range_text: str) -> str:
    text = range_text.strip().replace("$", "")
    if "!" not in text:
        return text
    return text.split("!", 1)[1].strip("'")


def _read_bool(value: Any, default: bool) -> bool:
    return value if isinstance(value, bool) else default
