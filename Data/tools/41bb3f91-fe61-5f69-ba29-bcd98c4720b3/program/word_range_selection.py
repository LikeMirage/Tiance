from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph

from word_errors import WordOperationError
from word_formula_match import collect_formula_nodes, formula_text, normalized_formula_text


W_PPR = qn("w:pPr")
W_T = qn("w:t")
OMATH_TAG = "{http://schemas.openxmlformats.org/officeDocument/2006/math}oMath"


@dataclass(slots=True)
class WordRangeResolution:
    start: Any
    start_offset: int
    end: Any
    end_offset: int
    selected_text: str
    equation_targets: list[Any]
    formula_refs: list[str]
    formula_texts: list[str]


def resolve_word_range(
    doc: Any,
    refs: list[Any],
    location: dict[str, Any],
    expected_text: Any,
) -> WordRangeResolution:
    start_position = location.get("start")
    end_position = location.get("end")
    if not isinstance(start_position, dict) or not isinstance(end_position, dict):
        raise ValueError("selection.word_range 必须包含 start 和 end。")
    start = paragraph_for_position(refs, start_position)
    end = paragraph_for_position(refs, end_position)
    if end.order < start.order:
        raise ValueError("引用终点位于起点之前。")
    start_preview = nonnegative_int(start_position.get("characterOffset"), "start.characterOffset")
    end_preview = nonnegative_int(end_position.get("characterOffset"), "end.characterOffset")
    start_offset = map_preview_offset(start.paragraph, start_preview)
    end_offset = map_preview_offset(end.paragraph, end_preview)
    selected_rendered = extract_rendered_text(refs, start, start_preview, end, end_preview)
    if isinstance(expected_text, str) and expected_text.strip():
        if normalized_formula_text(selected_rendered) != normalized_formula_text(expected_text):
            raise WordOperationError(
                "STALE_REFERENCE",
                "引用内容与当前 Word 文档不一致，文档可能已修改；请重新引用或 inspect。",
            )
    targets = selected_equations(refs, start, start_preview, end, end_preview)
    formula_nodes = collect_formula_nodes(doc)
    selected_formulas = [
        formula for formula in formula_nodes if any(formula.element is target for target in targets)
    ]
    return WordRangeResolution(
        start=start,
        start_offset=start_offset,
        end=end,
        end_offset=end_offset,
        selected_text=extract_plain_text(refs, start, start_offset, end, end_offset),
        equation_targets=targets,
        formula_refs=[formula.reference for formula in selected_formulas],
        formula_texts=[formula.text for formula in selected_formulas],
    )


def paragraph_for_position(refs: list[Any], position: dict[str, Any]) -> Any:
    container = position.get("container")
    if container == "body":
        index = position.get("paragraphIndex")
        if not isinstance(index, int) or index < 1:
            raise ValueError("正文引用必须包含 paragraphIndex。")
        if index > len(refs) or refs[index - 1].kind != "body":
            raise WordOperationError("SELECTION_NOT_FOUND", "引用中的正文段落不存在，请重新引用。")
        return refs[index - 1]
    if container == "table":
        values = [position.get(key) for key in ("tableIndex", "rowIndex", "columnIndex", "cellParagraphIndex")]
        if not all(isinstance(value, int) and value >= 1 for value in values):
            raise ValueError("表格引用必须包含 tableIndex、rowIndex、columnIndex 和 cellParagraphIndex。")
        kind = f"table:{values[0] - 1}:{values[1] - 1}:{values[2] - 1}:{values[3] - 1}"
        ref = next((item for item in refs if item.kind == kind), None)
        if ref is None:
            raise WordOperationError("SELECTION_NOT_FOUND", "引用中的表格单元格不存在，请重新引用。")
        return ref
    raise ValueError("当前只支持正文和表格单元格的 word_range 引用。")


def map_preview_offset(paragraph: Paragraph, preview_offset: int) -> int:
    rendered_length = len(rendered_paragraph_text(paragraph))
    if preview_offset > rendered_length:
        raise WordOperationError("STALE_REFERENCE", "引用字符偏移超出当前段落范围，请重新引用。")
    plain_cursor = 0
    rendered_cursor = 0
    for child in paragraph._p.iterchildren():
        if child.tag == W_PPR:
            continue
        child_text = rendered_node_text(child)
        child_end = rendered_cursor + len(child_text)
        if rendered_cursor < preview_offset < child_end:
            return plain_cursor if contains_equation(child) else plain_cursor + preview_offset - rendered_cursor
        if preview_offset == rendered_cursor:
            return plain_cursor
        plain_cursor += plain_node_text_length(child)
        rendered_cursor = child_end
    return plain_cursor


def selected_equations(refs: list[Any], start: Any, start_offset: int, end: Any, end_offset: int) -> list[Any]:
    targets: list[Any] = []
    for ref in refs[start.order : end.order + 1]:
        range_start = start_offset if ref is start else 0
        range_end = end_offset if ref is end else len(rendered_paragraph_text(ref.paragraph))
        rendered_cursor = 0
        for child in ref.paragraph._p.iterchildren():
            if child.tag == W_PPR:
                continue
            child_text = rendered_node_text(child)
            child_end = rendered_cursor + len(child_text)
            if contains_equation(child) and rendered_cursor < range_end and child_end > range_start:
                targets.extend(top_level_equations(child))
            rendered_cursor = child_end
    return targets


def rendered_paragraph_text(paragraph: Paragraph) -> str:
    return "".join(rendered_node_text(child) for child in paragraph._p.iterchildren() if child.tag != W_PPR)


def rendered_node_text(node: Any) -> str:
    equations = top_level_equations(node)
    if equations:
        return "".join(formula_text(equation) for equation in equations)
    return "".join(text.text or "" for text in node.iter(W_T))


def contains_equation(node: Any) -> bool:
    return any(child.tag == OMATH_TAG for child in node.iter())


def top_level_equations(node: Any) -> list[Any]:
    return [
        child for child in node.iter()
        if child.tag == OMATH_TAG
        and not any(parent.tag == OMATH_TAG for parent in child.iterancestors())
    ]


def extract_rendered_text(refs: list[Any], start: Any, start_offset: int, end: Any, end_offset: int) -> str:
    if start is end:
        return rendered_paragraph_text(start.paragraph)[start_offset:end_offset]
    parts = [rendered_paragraph_text(start.paragraph)[start_offset:]]
    parts.extend(rendered_paragraph_text(ref.paragraph) for ref in refs[start.order + 1 : end.order])
    parts.append(rendered_paragraph_text(end.paragraph)[:end_offset])
    return "\n".join(parts)


def extract_plain_text(refs: list[Any], start: Any, start_offset: int, end: Any, end_offset: int) -> str:
    if start is end:
        return start.text[start_offset:end_offset]
    parts = [start.text[start_offset:]]
    parts.extend(ref.text for ref in refs[start.order + 1 : end.order] if ref.text)
    parts.append(end.text[:end_offset])
    return "\n".join(parts)


def plain_node_text_length(node: Any) -> int:
    return sum(len(text.text or "") for text in node.iter(W_T))


def nonnegative_int(value: Any, field: str) -> int:
    if not isinstance(value, int) or value < 0:
        raise ValueError(f"selection.word_range.{field} 必须是大于等于 0 的整数。")
    return value
