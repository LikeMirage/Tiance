from __future__ import annotations

from math import ceil
from typing import Any


EMU_PER_INCH = 914400
POINTS_PER_INCH = 72
MANUAL_BULLET_PREFIXES = ("•", "·", "●", "▪", "-", "*")
RISK_ORDER = {"none": 0, "low": 1, "medium": 2, "high": 3}


def shape_inventory(prs: Any, *, max_text_chars_per_shape: int = 1200) -> dict[str, Any]:
    slides: list[dict[str, Any]] = []
    for slide_index, slide in enumerate(prs.slides):
        shapes: list[dict[str, Any]] = []
        for shape_index, shape in enumerate(iter_shapes(slide.shapes)):
            item = text_shape_item(
                shape,
                slide_index=slide_index,
                shape_index=shape_index,
                slide_width=int(prs.slide_width),
                slide_height=int(prs.slide_height),
                max_text_chars=max_text_chars_per_shape,
            )
            if item:
                shapes.append(item)
        slides.append({"slide_index": slide_index, "text_shapes": shapes})
    return {
        "slide_count": len(prs.slides),
        "unit": "inches",
        "slides": slides,
    }


def static_text_risk_report(prs: Any) -> dict[str, Any]:
    highest = "none"
    risk_count = 0
    slides: list[dict[str, Any]] = []
    for slide_index, slide in enumerate(prs.slides):
        risks: list[dict[str, Any]] = []
        for shape_index, shape in enumerate(iter_shapes(slide.shapes)):
            item = text_shape_item(
                shape,
                slide_index=slide_index,
                shape_index=shape_index,
                slide_width=int(prs.slide_width),
                slide_height=int(prs.slide_height),
                max_text_chars=220,
            )
            if not item:
                continue
            risk = item["risk"]
            if risk["level"] in {"medium", "high"} or item["warnings"]:
                risks.append(
                    {
                        "shape_id": item["shape_id"],
                        "shape_index": shape_index,
                        "name": item["name"],
                        "risk": risk,
                        "warnings": item["warnings"],
                        "text_preview": item["text"],
                        "box": item["box"],
                    }
                )
                risk_count += 1
                if RISK_ORDER[risk["level"]] > RISK_ORDER[highest]:
                    highest = risk["level"]
        if risks:
            slides.append({"slide_index": slide_index, "risks": risks})
    return {
        "note": "static heuristic; review the PPT visually for final layout quality",
        "highest_risk": highest,
        "risk_count": risk_count,
        "slides": slides,
    }


def quality_warnings(report: dict[str, Any]) -> list[str]:
    if report.get("highest_risk") not in {"medium", "high"}:
        return []
    warnings: list[str] = []
    for slide in report.get("slides", [])[:5]:
        slide_index = slide.get("slide_index")
        for item in slide.get("risks", [])[:2]:
            level = item.get("risk", {}).get("level")
            if level in {"medium", "high"}:
                warnings.append(f"第 {int(slide_index) + 1} 页存在 {level} 级文字拥挤风险，建议打开 PPT 复查。")
                break
    return warnings


def text_shape_item(
    shape: Any,
    *,
    slide_index: int,
    shape_index: int,
    slide_width: int,
    slide_height: int,
    max_text_chars: int,
) -> dict[str, Any] | None:
    if not getattr(shape, "has_text_frame", False):
        return None
    text = shape.text_frame.text.strip()
    if not text:
        return None
    paragraphs = paragraph_items(shape)
    box = {
        "x": round(emu_to_inches(getattr(shape, "left", 0) or 0), 3),
        "y": round(emu_to_inches(getattr(shape, "top", 0) or 0), 3),
        "w": round(emu_to_inches(getattr(shape, "width", 0) or 0), 3),
        "h": round(emu_to_inches(getattr(shape, "height", 0) or 0), 3),
    }
    warnings = shape_warnings(shape, text, paragraphs, slide_width, slide_height)
    risk = estimate_text_risk(shape, text, paragraphs)
    if len(text) > max_text_chars:
        text = text[:max_text_chars] + f"\n...<truncated {len(text) - max_text_chars} chars>"
    return {
        "slide_index": slide_index,
        "shape_id": f"s{slide_index + 1}-shape{shape_index + 1}",
        "shape_index": shape_index,
        "name": str(getattr(shape, "name", "") or ""),
        "type": str(getattr(shape, "shape_type", "") or ""),
        "box": box,
        "text": text,
        "paragraphs": paragraphs,
        "risk": risk,
        "warnings": warnings,
    }


def iter_shapes(shapes: Any) -> Any:
    for shape in shapes:
        yield shape
        if hasattr(shape, "shapes"):
            yield from iter_shapes(shape.shapes)


def paragraph_items(shape: Any) -> list[dict[str, Any]]:
    paragraphs: list[dict[str, Any]] = []
    for paragraph_index, paragraph in enumerate(shape.text_frame.paragraphs):
        text = paragraph.text or ""
        font_sizes = [safe_font_size(run.font.size) for run in paragraph.runs if safe_font_size(run.font.size)]
        paragraphs.append(
            {
                "paragraph_index": paragraph_index,
                "text": text,
                "level": int(getattr(paragraph, "level", 0) or 0),
                "alignment": str(getattr(paragraph, "alignment", "") or ""),
                "font_size": round(sum(font_sizes) / len(font_sizes), 1) if font_sizes else None,
                "run_count": len(paragraph.runs),
            }
        )
    return paragraphs


def shape_warnings(shape: Any, text: str, paragraphs: list[dict[str, Any]], slide_width: int, slide_height: int) -> list[str]:
    warnings: list[str] = []
    if any(str(item.get("text") or "").lstrip().startswith(MANUAL_BULLET_PREFIXES) for item in paragraphs):
        warnings.append("manual_bullet_prefix")
    left = int(getattr(shape, "left", 0) or 0)
    top = int(getattr(shape, "top", 0) or 0)
    width = int(getattr(shape, "width", 0) or 0)
    height = int(getattr(shape, "height", 0) or 0)
    if left < 0 or top < 0 or left + width > slide_width or top + height > slide_height:
        warnings.append("shape_outside_slide")
    if "\t" in text:
        warnings.append("tab_in_text")
    return warnings


def estimate_text_risk(shape: Any, text: str, paragraphs: list[dict[str, Any]]) -> dict[str, Any]:
    font_size = average_font_size(paragraphs)
    width_points = max(emu_to_points(getattr(shape, "width", 0) or 0) - 12, 12)
    height_points = max(emu_to_points(getattr(shape, "height", 0) or 0) - 8, 12)
    char_width = max(font_size * 0.56, 5)
    line_height = max(font_size * 1.25, 10)
    chars_per_line = max(int(width_points / char_width), 1)
    available_lines = max(int(height_points / line_height), 1)
    estimated_lines = 0
    for paragraph in paragraphs:
        paragraph_text = str(paragraph.get("text") or "")
        estimated_lines += max(1, ceil(len(paragraph_text) / chars_per_line))
    fill_ratio = estimated_lines / available_lines if available_lines else 1
    level = "none"
    if text.strip():
        if fill_ratio >= 1.15:
            level = "high"
        elif fill_ratio >= 0.85:
            level = "medium"
        elif fill_ratio >= 0.65:
            level = "low"
    return {
        "level": level,
        "char_count": len(text),
        "paragraph_count": len(paragraphs),
        "font_size": round(font_size, 1),
        "estimated_lines": estimated_lines,
        "available_lines": available_lines,
        "fill_ratio": round(fill_ratio, 2),
    }


def average_font_size(paragraphs: list[dict[str, Any]]) -> float:
    values = [float(item["font_size"]) for item in paragraphs if isinstance(item.get("font_size"), (int, float))]
    if values:
        return sum(values) / len(values)
    return 16.0


def safe_font_size(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value.pt)
    except AttributeError:
        return None


def emu_to_inches(value: int) -> float:
    return float(value) / EMU_PER_INCH


def emu_to_points(value: int) -> float:
    return emu_to_inches(value) * POINTS_PER_INCH
