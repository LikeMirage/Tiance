from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph

from word_errors import WordOperationError
from word_formula_match import collect_formula_nodes, formula_text, normalized_formula_text


W_PPR = qn("w:pPr")
W_T = qn("w:t")
OMATH_TAG = "{http://schemas.openxmlformats.org/officeDocument/2006/math}oMath"
MAX_EQUATION_BOUNDARY_DRIFT = 4


@dataclass(slots=True)
class WordRangeResolution:
    start: Any
    start_offset: int
    end: Any
    end_offset: int
    selected_text: str
    selected_rendered_text: str
    content_markdown: str
    segments: list[dict[str, Any]]
    equation_targets: list[Any]
    formula_refs: list[str]
    formula_texts: list[str]
    resolution: dict[str, Any]


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

    requested_start = nonnegative_int(start_position.get("characterOffset"), "start.characterOffset")
    requested_end = nonnegative_int(end_position.get("characterOffset"), "end.characterOffset")
    preview_start, preview_end, resolution = resolve_preview_range(
        doc,
        refs,
        start,
        requested_start,
        end,
        requested_end,
        expected_text,
    )
    start_offset = map_preview_offset(start.paragraph, preview_start)
    end_offset = map_preview_offset(end.paragraph, preview_end)
    selected_rendered = extract_rendered_text(refs, start, preview_start, end, preview_end)

    if isinstance(expected_text, str) and expected_text.strip():
        if normalized_formula_text(selected_rendered) != normalized_formula_text(expected_text):
            details = range_diagnostics(
                doc,
                refs,
                start,
                requested_start,
                end,
                requested_end,
                expected_text,
            )
            raise WordOperationError(
                "REFERENCE_CONTENT_MISMATCH",
                "引用位置已找到，但引用内容与当前 Word 内容不一致；请根据候选范围重新选择或 inspect。",
                details,
            )

    targets = selected_equations(refs, start, preview_start, end, preview_end)
    formula_nodes = collect_formula_nodes(doc)
    selected_formulas = [
        formula for formula in formula_nodes if any(formula.element is target for target in targets)
    ]
    segments = extract_selected_segments(
        refs,
        start,
        preview_start,
        end,
        preview_end,
        formula_nodes,
    )
    return WordRangeResolution(
        start=start,
        start_offset=start_offset,
        end=end,
        end_offset=end_offset,
        selected_text=extract_plain_text(refs, start, start_offset, end, end_offset),
        selected_rendered_text=selected_rendered,
        content_markdown=segments_markdown(segments),
        segments=segments,
        equation_targets=targets,
        formula_refs=[formula.reference for formula in selected_formulas],
        formula_texts=[formula.text for formula in selected_formulas],
        resolution=resolution,
    )


def resolve_preview_range(
    doc: Any,
    refs: list[Any],
    start: Any,
    requested_start: int,
    end: Any,
    requested_end: int,
    expected_text: Any,
) -> tuple[int, int, dict[str, Any]]:
    start_length = len(rendered_paragraph_text(start.paragraph))
    end_length = len(rendered_paragraph_text(end.paragraph))
    offsets_valid = requested_start <= start_length and requested_end <= end_length
    order_valid = start is not end or requested_end >= requested_start
    if offsets_valid and order_valid:
        return requested_start, requested_end, {
            "strategy": "exact",
            "adjusted": False,
            "requested_start_offset": requested_start,
            "requested_end_offset": requested_end,
            "resolved_start_offset": requested_start,
            "resolved_end_offset": requested_end,
        }

    if start is end and requested_start <= start_length and requested_end >= requested_start:
        clamped_end = min(requested_end, end_length)
        drift = requested_end - clamped_end
        targets = selected_equations(refs, start, requested_start, end, clamped_end)
        if targets and 0 < drift <= MAX_EQUATION_BOUNDARY_DRIFT:
            return requested_start, clamped_end, {
                "strategy": "equation_boundary_adjustment",
                "adjusted": True,
                "reason": "预览与 Word 对原生公式的线性字符计数不同，已在同一段落内校准公式边界。",
                "requested_start_offset": requested_start,
                "requested_end_offset": requested_end,
                "resolved_start_offset": requested_start,
                "resolved_end_offset": clamped_end,
                "offset_difference": drift,
            }

    details = range_diagnostics(
        doc,
        refs,
        start,
        requested_start,
        end,
        requested_end,
        expected_text,
    )
    raise WordOperationError(
        "REFERENCE_OFFSET_MISMATCH",
        "引用容器已找到，但预览字符偏移无法直接映射到当前 Word 内容；请根据候选范围重新选择或 inspect。",
        details,
    )


def range_diagnostics(
    doc: Any,
    refs: list[Any],
    start: Any,
    requested_start: int,
    end: Any,
    requested_end: int,
    expected_text: Any,
) -> dict[str, Any]:
    start_rendered = rendered_paragraph_text(start.paragraph)
    end_rendered = rendered_paragraph_text(end.paragraph)
    details: dict[str, Any] = {
        "container_found": True,
        "requested_range": {
            "start_offset": requested_start,
            "end_offset": requested_end,
        },
        "actual_lengths": {
            "start_paragraph": len(start_rendered),
            "end_paragraph": len(end_rendered),
        },
        "start_container": start.kind,
        "end_container": end.kind,
        "offset_semantics": "段落语义渲染文本中的零基位置，起点包含、终点不包含。",
        "candidates": [],
    }
    if start is end:
        details["rendered_text"] = start_rendered[:500]
        details["candidates"] = candidate_ranges(
            doc,
            start.paragraph,
            requested_start,
            requested_end,
            expected_text if isinstance(expected_text, str) else "",
        )
    return details


def candidate_ranges(
    doc: Any,
    paragraph: Paragraph,
    requested_start: int,
    requested_end: int,
    expected_text: str,
) -> list[dict[str, Any]]:
    rendered = rendered_paragraph_text(paragraph)
    formula_nodes = collect_formula_nodes(doc)
    ranges: list[tuple[int, int, str]] = []
    clamped_start = min(requested_start, len(rendered))
    clamped_end = min(max(requested_end, clamped_start), len(rendered))
    ranges.append((clamped_start, clamped_end, "requested_range_clamped"))
    if rendered:
        ranges.append((0, len(rendered), "whole_paragraph"))
    if expected_text:
        cursor = 0
        while True:
            position = rendered.find(expected_text, cursor)
            if position < 0:
                break
            ranges.append((position, position + len(expected_text), "exact_content"))
            cursor = position + max(1, len(expected_text))
        ranges.extend(approximate_text_ranges(rendered, expected_text))
    ranges.extend((start, end, "equation") for start, end, _node in equation_spans(paragraph))

    unique: dict[tuple[int, int], str] = {}
    for start, end, source in ranges:
        if end > start:
            unique.setdefault((start, end), source)
    expected_normalized = normalized_formula_text(expected_text) if expected_text else ""
    candidates: list[dict[str, Any]] = []
    for (start, end), source in unique.items():
        content = rendered[start:end]
        segments = extract_paragraph_segments(paragraph, start, end, formula_nodes)
        candidate: dict[str, Any] = {
            "candidate_id": f"range:{start}:{end}",
            "source": source,
            "start_offset": start,
            "end_offset": end,
            "content_kind": segments_content_kind(segments),
            "content_text": content,
            "content_markdown": segments_markdown(segments),
            "segments": segments,
        }
        if expected_normalized:
            candidate["similarity"] = round(
                SequenceMatcher(
                    None,
                    expected_normalized,
                    normalized_formula_text(content),
                ).ratio(),
                4,
            )
        candidates.append(candidate)
    candidates.sort(
        key=lambda item: (
            float(item.get("similarity", 0)),
            item["source"] == "exact_content",
            item["source"] == "equation",
        ),
        reverse=True,
    )
    return candidates[:5]


def approximate_text_ranges(rendered: str, expected_text: str) -> list[tuple[int, int, str]]:
    if not rendered or not expected_text or len(rendered) > 5000 or len(expected_text) > 500:
        return []
    target = normalized_formula_text(expected_text)
    if not target:
        return []
    expected_length = len(expected_text)
    minimum_length = max(1, expected_length - 3)
    maximum_length = min(len(rendered), expected_length + 3)
    ranked: list[tuple[float, int, int]] = []
    for start in range(len(rendered)):
        for length in range(minimum_length, maximum_length + 1):
            end = start + length
            if end > len(rendered):
                break
            score = SequenceMatcher(
                None,
                target,
                normalized_formula_text(rendered[start:end]),
            ).ratio()
            if score >= 0.6:
                ranked.append((score, start, end))
    ranked.sort(reverse=True)
    selected: list[tuple[int, int, str]] = []
    seen: set[tuple[int, int]] = set()
    for _score, start, end in ranked:
        key = (start, end)
        if key in seen:
            continue
        seen.add(key)
        selected.append((start, end, "approximate_content"))
        if len(selected) == 5:
            break
    return selected


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
        raise WordOperationError(
            "REFERENCE_OFFSET_MISMATCH",
            "引用字符偏移超出当前段落的语义渲染文本范围。",
            {"requested_offset": preview_offset, "rendered_length": rendered_length},
        )
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
        for equation_start, equation_end, equation in equation_spans(ref.paragraph):
            if equation_start < range_end and equation_end > range_start:
                targets.append(equation)
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


def equation_spans(paragraph: Paragraph) -> list[tuple[int, int, Any]]:
    spans: list[tuple[int, int, Any]] = []
    cursor = 0
    for child in paragraph._p.iterchildren():
        if child.tag == W_PPR:
            continue
        equations = top_level_equations(child)
        if equations:
            for equation in equations:
                value = formula_text(equation)
                spans.append((cursor, cursor + len(value), equation))
                cursor += len(value)
        else:
            cursor += len(rendered_node_text(child))
    return spans


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


def extract_selected_segments(
    refs: list[Any],
    start: Any,
    start_offset: int,
    end: Any,
    end_offset: int,
    formula_nodes: list[Any],
) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    for ref in refs[start.order : end.order + 1]:
        range_start = start_offset if ref is start else 0
        range_end = end_offset if ref is end else len(rendered_paragraph_text(ref.paragraph))
        paragraph_segments = extract_paragraph_segments(
            ref.paragraph,
            range_start,
            range_end,
            formula_nodes,
        )
        if segments and paragraph_segments:
            segments.append({"kind": "paragraph_break", "text": "\n"})
        segments.extend(paragraph_segments)
    return segments


def extract_paragraph_segments(
    paragraph: Paragraph,
    start_offset: int,
    end_offset: int,
    formula_nodes: list[Any],
) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    cursor = 0
    for child in paragraph._p.iterchildren():
        if child.tag == W_PPR:
            continue
        equations = top_level_equations(child)
        if equations:
            for equation in equations:
                value = formula_text(equation)
                node_start, node_end = cursor, cursor + len(value)
                if node_start < end_offset and node_end > start_offset:
                    formula = next((item for item in formula_nodes if item.element is equation), None)
                    segments.append({
                        "kind": "equation",
                        "rendered_start": node_start,
                        "rendered_end": node_end,
                        "formula_ref": formula.reference if formula is not None else "",
                        "formula_text": value,
                        "markdown": f"${value}$",
                    })
                cursor = node_end
            continue
        value = rendered_node_text(child)
        node_start, node_end = cursor, cursor + len(value)
        left = max(start_offset, node_start)
        right = min(end_offset, node_end)
        if right > left:
            text = value[left - node_start : right - node_start]
            if text:
                segments.append({
                    "kind": "text",
                    "rendered_start": left,
                    "rendered_end": right,
                    "text": text,
                    "markdown": text,
                })
        cursor = node_end
    return segments


def segments_content_kind(segments: list[dict[str, Any]]) -> str:
    kinds = {segment.get("kind") for segment in segments if segment.get("kind") != "paragraph_break"}
    if "equation" in kinds and "text" in kinds:
        return "mixed"
    if "equation" in kinds:
        return "equation"
    return "text"


def segments_markdown(segments: list[dict[str, Any]]) -> str:
    return "".join(str(segment.get("markdown") or segment.get("text") or "") for segment in segments)


def plain_node_text_length(node: Any) -> int:
    return sum(len(text.text or "") for text in node.iter(W_T))


def nonnegative_int(value: Any, field: str) -> int:
    if not isinstance(value, int) or value < 0:
        raise ValueError(f"selection.word_range.{field} 必须是大于等于 0 的整数。")
    return value
