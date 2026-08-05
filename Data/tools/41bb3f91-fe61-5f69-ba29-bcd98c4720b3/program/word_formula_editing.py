from __future__ import annotations

from typing import Any

from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from word_errors import WordOperationError
from word_elements import normalize_color
from word_formula_match import formula_omml_from_latex
from word_selection import SelectionRange
from word_selection_editing import (
    delete_equation_targets,
    delete_selection,
    refresh_ref,
    require_nonempty,
    rewrite_paragraph_range,
)


OMML_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
M_R = f"{{{OMML_NS}}}r"
M_RPR = f"{{{OMML_NS}}}rPr"
W_RPR = qn("w:rPr")

RUN_PROPERTY_ORDER = {
    qn("w:rFonts"): 0,
    qn("w:b"): 1,
    qn("w:bCs"): 2,
    qn("w:i"): 3,
    qn("w:iCs"): 4,
    qn("w:strike"): 5,
    qn("w:color"): 6,
    qn("w:sz"): 7,
    qn("w:szCs"): 8,
    qn("w:u"): 9,
}


def replace_selection_with_equation(
    selection: SelectionRange,
    latex: str,
    style: dict[str, Any] | None = None,
) -> dict[str, int]:
    require_nonempty(selection, "replace")
    equation = formula_omml_from_latex(latex)
    apply_equation_style(equation, style or {})
    if (
        len(selection.equation_targets) == 1
        and selection.start is selection.end
        and selection.start_offset == selection.end_offset
    ):
        target = selection.equation_targets[0]
        parent = target.getparent()
        if parent is None:
            raise WordOperationError(
                "SELECTION_NOT_FOUND",
                "目标公式已不在文档中，请重新 inspect。",
            )
        parent.replace(target, equation)
        refresh_ref(selection.start)
        return {"characters": 0, "equations": 1, "blocks": 0}
    if selection.same_paragraph:
        removed = rewrite_paragraph_range(
            selection.start.paragraph,
            selection.start_offset,
            selection.end_offset,
            [equation],
        )
        removed["equations"] += delete_equation_targets(
            [node for node in selection.equation_targets if node.getparent() is not None]
        )
    else:
        removed = delete_selection(selection)
        rewrite_paragraph_range(
            selection.start.paragraph,
            selection.start_offset,
            selection.start_offset,
            [equation],
        )
    refresh_ref(selection.start)
    return removed


def insert_equation(
    selection: SelectionRange,
    latex: str,
    style: dict[str, Any] | None = None,
) -> None:
    equation = formula_omml_from_latex(latex)
    apply_equation_style(equation, style or {})
    if (
        len(selection.equation_targets) == 1
        and selection.start is selection.end
        and selection.start_offset == selection.end_offset
    ):
        target = selection.equation_targets[0]
        if target.getparent() is None:
            raise WordOperationError(
                "SELECTION_NOT_FOUND",
                "目标公式已不在文档中，请重新 inspect。",
            )
        target.addprevious(equation)
        refresh_ref(selection.start)
        return
    rewrite_paragraph_range(
        selection.start.paragraph,
        selection.start_offset,
        selection.start_offset,
        [equation],
    )
    refresh_ref(selection.start)


def format_equation_targets(
    selection: SelectionRange,
    style: dict[str, Any],
) -> int:
    formatted = 0
    for equation in selection.equation_targets:
        if equation.getparent() is None:
            continue
        apply_equation_style(equation, style)
        formatted += 1
    return formatted


def apply_equation_style(equation: Any, style: dict[str, Any]) -> None:
    if not style:
        return
    for math_run in equation.iter(M_R):
        properties = math_run.find(W_RPR)
        if properties is None:
            properties = OxmlElement("w:rPr")
            math_properties = math_run.find(M_RPR)
            math_run.insert(1 if math_properties is not None else 0, properties)
        _patch_run_properties(properties, style)


def _patch_run_properties(properties: Any, style: dict[str, Any]) -> None:
    if "color" in style:
        _set_value_property(properties, "w:color", normalize_color(style["color"]))
    if isinstance(style.get("font_size"), (int, float)):
        if float(style["font_size"]) <= 0:
            raise ValueError("style.font_size 必须大于 0。")
        half_points = str(max(1, round(float(style["font_size"]) * 2)))
        _set_value_property(properties, "w:sz", half_points)
        _set_value_property(properties, "w:szCs", half_points)
    for key, tag in (("bold", "w:b"), ("italic", "w:i"), ("strike", "w:strike")):
        if key in style:
            _set_value_property(properties, tag, "1" if bool(style[key]) else "0")
            if key in {"bold", "italic"}:
                _set_value_property(
                    properties,
                    "w:bCs" if key == "bold" else "w:iCs",
                    "1" if bool(style[key]) else "0",
                )
    if "underline" in style:
        _set_value_property(properties, "w:u", "single" if bool(style["underline"]) else "none")
    if any(
        key in style
        for key in (
            "font_family",
            "east_asia_font",
            "eastAsia_font",
            "cjk_font",
            "complex_script_font",
            "cs_font",
        )
    ):
        fonts = _get_or_add_property(properties, "w:rFonts")
        family = style.get("font_family")
        east_asia = style.get("east_asia_font") or style.get("eastAsia_font") or style.get("cjk_font")
        complex_script = style.get("complex_script_font") or style.get("cs_font")
        if family:
            fonts.set(qn("w:ascii"), str(family))
            fonts.set(qn("w:hAnsi"), str(family))
        if east_asia:
            fonts.set(qn("w:eastAsia"), str(east_asia))
        if complex_script:
            fonts.set(qn("w:cs"), str(complex_script))


def _set_value_property(properties: Any, tag: str, value: str) -> None:
    element = _get_or_add_property(properties, tag)
    element.set(qn("w:val"), value)


def _get_or_add_property(properties: Any, tag: str) -> Any:
    qualified = qn(tag)
    existing = properties.find(qualified)
    if existing is not None:
        return existing
    element = OxmlElement(tag)
    target_order = RUN_PROPERTY_ORDER[qualified]
    for index, child in enumerate(properties):
        if RUN_PROPERTY_ORDER.get(child.tag, len(RUN_PROPERTY_ORDER)) > target_order:
            properties.insert(index, element)
            break
    else:
        properties.append(element)
    return element
