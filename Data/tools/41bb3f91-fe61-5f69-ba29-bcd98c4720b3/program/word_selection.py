from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

from word_formula_match import (
    collect_formula_nodes,
    find_formula_match,
    parse_formula_anchor,
    resolve_formula_reference,
)
from word_errors import WordOperationError
from word_range_selection import resolve_word_range


W_P = qn("w:p")
W_PPR = qn("w:pPr")
W_T = qn("w:t")
W_TBL = qn("w:tbl")
OMML_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
OMATH_TAG = f"{{{OMML_NS}}}oMath"


@dataclass(slots=True)
class ParagraphRef:
    paragraph: Paragraph
    text: str
    order: int
    kind: str
    body_block: Any
    body_index: int
    container: Any


@dataclass(slots=True)
class SelectionRange:
    start: ParagraphRef
    start_offset: int
    end: ParagraphRef
    end_offset: int
    start_anchor: str
    end_anchor: str | None
    selected_text: str
    equation_count: int
    boundary_mode: str = "exclusive"
    expand: str = "none"
    equation_targets: list[Any] = field(default_factory=list)
    matched_formulas: list[str] = field(default_factory=list)
    matched_formula_refs: list[str] = field(default_factory=list)
    formula_match_strategies: list[str] = field(default_factory=list)
    selection_source: str = "anchor"

    @property
    def empty(self) -> bool:
        if self.equation_targets:
            return False
        return self.start is self.end and self.start_offset == self.end_offset

    @property
    def same_paragraph(self) -> bool:
        return self.start is self.end

    @property
    def same_container(self) -> bool:
        return self.start.container is self.end.container

    def summary(self) -> dict[str, Any]:
        if self.equation_count and self.selected_text:
            content_kind = "mixed"
        elif self.equation_count:
            content_kind = "equation"
        else:
            content_kind = "text"
        return {
            "kind": "point" if self.empty else "range",
            "boundary_mode": self.boundary_mode,
            "expand": self.expand,
            "start": paragraph_location(self.start, self.start_offset),
            "end": paragraph_location(self.end, self.end_offset),
            "start_anchor": self.start_anchor,
            "end_anchor": self.end_anchor or "",
            "selected_text": self.selected_text,
            "selected_char_count": len(self.selected_text),
            "equation_count": self.equation_count,
            "matched_formulas": list(self.matched_formulas),
            "matched_formula_refs": list(self.matched_formula_refs),
            "formula_match_strategies": list(self.formula_match_strategies),
            "content_kind": content_kind,
            "content": self.selected_text,
            "content_markdown": self.selected_text if content_kind == "text" else None,
            "formulas": [
                {"formula_ref": ref, "formula_text": text}
                for ref, text in zip(self.matched_formula_refs, self.matched_formulas)
            ],
            "selection_source": self.selection_source,
        }


def resolve_selection(doc: Any, spec: Any) -> SelectionRange:
    if not isinstance(spec, dict):
        raise ValueError("selection 必须是对象。")
    start_anchor = spec.get("start_anchor")
    formula_ref = spec.get("formula_ref")
    word_range = spec.get("word_range")
    has_start_anchor = isinstance(start_anchor, str) and bool(start_anchor)
    has_formula_ref = isinstance(formula_ref, str) and bool(formula_ref)
    has_word_range = isinstance(word_range, dict)
    if sum((has_start_anchor, has_formula_ref, has_word_range)) != 1:
        raise ValueError("selection 必须且只能提供 start_anchor、formula_ref 或 word_range 其中一个。")
    end_anchor = spec.get("end_anchor")
    if end_anchor is not None and (not isinstance(end_anchor, str) or not end_anchor):
        raise ValueError("selection.end_anchor 必须是非空字符串；省略表示插入点或显式扩展。")

    match_case = spec.get("match_case")
    match_case = match_case if isinstance(match_case, bool) else True
    start_occurrence = positive_int(spec.get("start_occurrence"), 1, "start_occurrence")
    end_occurrence = positive_int(spec.get("end_occurrence"), 1, "end_occurrence")
    boundary_mode = str(spec.get("boundary_mode") or "exclusive").strip().lower()
    if boundary_mode not in {"exclusive", "inclusive"}:
        raise ValueError("selection.boundary_mode 必须是 exclusive 或 inclusive。")
    expand = str(spec.get("expand") or "none").strip().lower()
    if expand not in {"none", "paragraph_end", "cell_end"}:
        raise ValueError("selection.expand 必须是 none、paragraph_end 或 cell_end。")

    refs = collect_document_paragraphs(doc)
    if not refs:
        raise ValueError("文档正文中没有可定位的段落。")

    matched_formulas: list[str] = []
    matched_formula_refs: list[str] = []
    formula_match_strategies: list[str] = []
    equation_targets: list[Any] = []

    if has_word_range:
        resolved = resolve_word_range(doc, refs, word_range, spec.get("expected_text"))
        validate_supported_range(resolved.start, resolved.end)
        return SelectionRange(
            start=resolved.start,
            start_offset=resolved.start_offset,
            end=resolved.end,
            end_offset=resolved.end_offset,
            start_anchor="word_range",
            end_anchor=None,
            selected_text=resolved.selected_text,
            equation_count=len(resolved.equation_targets),
            boundary_mode="inclusive",
            equation_targets=resolved.equation_targets,
            matched_formulas=resolved.formula_texts,
            matched_formula_refs=resolved.formula_refs,
            formula_match_strategies=["word_range"] * len(resolved.equation_targets),
            selection_source="word_range",
        )

    if has_formula_ref:
        if end_anchor is not None:
            raise ValueError("selection.formula_ref 已精确选中一个公式，不能同时提供 end_anchor。")
        if expand != "none":
            raise ValueError("selection.formula_ref 已精确选中一个公式，expand 必须为 none。")
        formula_node = resolve_formula_reference(doc, formula_ref)
        start_ref = paragraph_ref_for_element(refs, formula_node.paragraph_element)
        formula_offset = formula_character_offset(start_ref.paragraph, formula_node.element)
        return SelectionRange(
            start=start_ref,
            start_offset=formula_offset,
            end=start_ref,
            end_offset=formula_offset,
            start_anchor=formula_ref,
            end_anchor=None,
            selected_text="",
            equation_count=1,
            boundary_mode="inclusive",
            expand="none",
            equation_targets=[formula_node.element],
            matched_formulas=[formula_node.text],
            matched_formula_refs=[formula_node.reference],
            formula_match_strategies=["formula_ref"],
            selection_source="formula_ref",
        )

    start_formula = parse_formula_anchor(start_anchor)
    start_formula_omath: Any | None = None
    if start_formula is not None:
        start_ref, formula_offset, start_formula_omath, matched_ref, match_strategy = resolve_formula_anchor(
            doc,
            refs,
            start_formula,
            occurrence=start_occurrence,
        )
        matched_formulas.append(start_formula)
        matched_formula_refs.append(matched_ref)
        formula_match_strategies.append(match_strategy)
        # Exclusive: caret after the formula node; Inclusive: include formula object.
        start_offset = formula_offset
        start_match_end = formula_offset
        if boundary_mode == "inclusive" or end_anchor is None:
            equation_targets.append(start_formula_omath)
    else:
        start_ref, start_match = find_text_anchor(
            refs,
            start_anchor,
            occurrence=start_occurrence,
            match_case=match_case,
        )
        if boundary_mode == "inclusive":
            start_offset = start_match
            start_match_end = start_match + len(start_anchor)
        else:
            start_offset = start_match + len(start_anchor)
            start_match_end = start_offset

    if end_anchor is None:
        # Bare formula anchor always selects that formula object (ignore expand).
        if start_formula is not None:
            validate_supported_range(start_ref, start_ref)
            return SelectionRange(
                start=start_ref,
                start_offset=start_offset,
                end=start_ref,
                end_offset=start_offset,
                start_anchor=start_anchor,
                end_anchor=None,
                selected_text="",
                equation_count=1,
                boundary_mode="inclusive",
                expand="none",
                equation_targets=equation_targets,
                matched_formulas=matched_formulas,
                matched_formula_refs=matched_formula_refs,
                formula_match_strategies=formula_match_strategies,
            )
        resolved_expand = expand
        if resolved_expand == "none":
            end_ref, end_offset = start_ref, start_offset
        else:
            end_ref, end_offset = expand_selection_end(refs, start_ref, start_offset, resolved_expand)
        validate_supported_range(start_ref, end_ref)
        selected_text = extract_selected_text(refs, start_ref, start_offset, end_ref, end_offset)
        equation_count = count_selected_equations(refs, start_ref, start_offset, end_ref, end_offset)
        return SelectionRange(
            start=start_ref,
            start_offset=start_offset,
            end=end_ref,
            end_offset=end_offset,
            start_anchor=start_anchor,
            end_anchor=None,
            selected_text=selected_text,
            equation_count=equation_count,
            boundary_mode=boundary_mode,
            expand=resolved_expand,
            equation_targets=equation_targets,
            matched_formulas=matched_formulas,
            matched_formula_refs=matched_formula_refs,
            formula_match_strategies=formula_match_strategies,
        )

    end_formula = parse_formula_anchor(end_anchor)
    if end_formula is not None:
        end_ref, end_formula_offset, end_omath, matched_ref, match_strategy = resolve_formula_anchor(
            doc,
            refs,
            end_formula,
            occurrence=end_occurrence,
            after_paragraph_order=start_ref.order,
            after_offset=start_match_end,
        )
        matched_formulas.append(end_formula)
        matched_formula_refs.append(matched_ref)
        formula_match_strategies.append(match_strategy)
        end_offset = end_formula_offset
        if boundary_mode == "inclusive":
            equation_targets.append(end_omath)
    else:
        end_ref, end_match = find_text_anchor(
            refs,
            end_anchor,
            occurrence=end_occurrence,
            match_case=match_case,
            after=(start_ref.order, start_match_end),
        )
        if boundary_mode == "inclusive":
            end_offset = end_match + len(end_anchor)
        else:
            end_offset = end_match

    validate_supported_range(start_ref, end_ref)
    selected_text = extract_selected_text(refs, start_ref, start_offset, end_ref, end_offset)
    equation_count = count_selected_equations(refs, start_ref, start_offset, end_ref, end_offset)
    if equation_targets:
        equation_count = max(equation_count, len({id(node) for node in equation_targets}))
    return SelectionRange(
        start=start_ref,
        start_offset=start_offset,
        end=end_ref,
        end_offset=end_offset,
        start_anchor=start_anchor,
        end_anchor=end_anchor,
        selected_text=selected_text,
        equation_count=equation_count,
        boundary_mode=boundary_mode,
        expand="none",
        equation_targets=equation_targets,
        matched_formulas=matched_formulas,
        matched_formula_refs=matched_formula_refs,
        formula_match_strategies=formula_match_strategies,
    )


def expand_selection_end(
    refs: list[ParagraphRef],
    start_ref: ParagraphRef,
    start_offset: int,
    expand: str,
) -> tuple[ParagraphRef, int]:
    if expand == "paragraph_end":
        return start_ref, len(start_ref.text)
    if expand != "cell_end":
        raise ValueError(f"不支持的 expand：{expand}")
    if not start_ref.kind.startswith("table:"):
        return start_ref, len(start_ref.text)
    end_ref = start_ref
    for ref in refs[start_ref.order :]:
        if ref.container is not start_ref.container:
            break
        end_ref = ref
    if end_ref is start_ref and start_offset > len(start_ref.text):
        raise ValueError("选区扩展超出段落范围。")
    return end_ref, len(end_ref.text)


def resolve_formula_anchor(
    doc: Any,
    refs: list[ParagraphRef],
    latex: str,
    *,
    occurrence: int,
    after_paragraph_order: int | None = None,
    after_offset: int | None = None,
) -> tuple[ParagraphRef, int, Any, str, str]:
    next_occurrence = occurrence if after_paragraph_order is None else 1
    remaining_after_start = occurrence
    while True:
        formula_match = find_formula_match(doc, latex, occurrence=next_occurrence)
        ref = paragraph_ref_for_element(refs, formula_match.node.paragraph_element)
        offset = formula_character_offset(ref.paragraph, formula_match.node.element)
        if after_paragraph_order is None:
            return (
                ref,
                offset,
                formula_match.node.element,
                formula_match.node.reference,
                formula_match.strategy,
            )
        if ref.order > after_paragraph_order or (
            ref.order == after_paragraph_order and (after_offset is None or offset >= after_offset)
        ):
            remaining_after_start -= 1
            if remaining_after_start == 0:
                return (
                    ref,
                    offset,
                    formula_match.node.element,
                    formula_match.node.reference,
                    formula_match.strategy,
                )
        next_occurrence += 1


def paragraph_ref_for_element(refs: list[ParagraphRef], paragraph_element: Any) -> ParagraphRef:
    ref = next((item for item in refs if item.paragraph._p is paragraph_element), None)
    if ref is None:
        raise ValueError("找到了公式，但无法映射到可选段落。")
    return ref


def formula_character_offset(paragraph: Paragraph, omath: Any) -> int:
    cursor = 0
    for node in paragraph._p.iterchildren():
        if node.tag == W_PPR:
            continue
        if node is omath or any(child is omath for child in node.iter()):
            return cursor
        cursor += node_text_length(node)
    raise ValueError("公式节点不在目标段落内。")


def collect_document_paragraphs(doc: Any) -> list[ParagraphRef]:
    refs: list[ParagraphRef] = []
    seen_paragraphs: set[Any] = set()
    body = doc.element.body
    table_index = 0
    for body_index, child in enumerate(body.iterchildren()):
        if child.tag == W_P:
            paragraph = Paragraph(child, doc)
            refs.append(
                ParagraphRef(
                    paragraph=paragraph,
                    text=paragraph_plain_text(paragraph),
                    order=len(refs),
                    kind="body",
                    body_block=child,
                    body_index=body_index,
                    container=body,
                )
            )
        elif child.tag == W_TBL:
            table = Table(child, doc)
            for row_index, row in enumerate(table.rows):
                for column_index, cell in enumerate(row.cells):
                    for paragraph_index, paragraph in enumerate(cell.paragraphs):
                        if paragraph._p in seen_paragraphs:
                            continue
                        seen_paragraphs.add(paragraph._p)
                        refs.append(
                            ParagraphRef(
                                paragraph=paragraph,
                                text=paragraph_plain_text(paragraph),
                                order=len(refs),
                                kind=f"table:{table_index}:{row_index}:{column_index}:{paragraph_index}",
                                body_block=child,
                                body_index=body_index,
                                container=cell._tc,
                            )
                        )
            table_index += 1
    return refs


def inspect_formula_catalog(doc: Any, *, limit: int) -> list[dict[str, Any]]:
    refs = collect_document_paragraphs(doc)
    catalog: list[dict[str, Any]] = []
    for formula in collect_formula_nodes(doc)[:limit]:
        ref = paragraph_ref_for_element(refs, formula.paragraph_element)
        offset = formula_character_offset(ref.paragraph, formula.element)
        catalog.append(
            {
                "formula_ref": formula.reference,
                "text": formula.text,
                "location": paragraph_location(ref, offset),
            }
        )
    return catalog


def paragraph_plain_text(paragraph: Paragraph) -> str:
    return "".join(node.text or "" for node in paragraph._p.iter(W_T))


def find_text_anchor(
    refs: list[ParagraphRef],
    anchor: str,
    *,
    occurrence: int,
    match_case: bool,
    after: tuple[int, int] | None = None,
) -> tuple[ParagraphRef, int]:
    remaining = occurrence
    needle = anchor if match_case else anchor.lower()
    for ref in refs:
        if after is not None and ref.order < after[0]:
            continue
        start = after[1] if after is not None and ref.order == after[0] else 0
        haystack = ref.text if match_case else ref.text.lower()
        position = start
        while True:
            match = haystack.find(needle, position)
            if match < 0:
                break
            remaining -= 1
            if remaining == 0:
                return ref, match
            position = match + max(1, len(needle))
    qualifier = f"（第 {occurrence} 处）" if occurrence > 1 else ""
    raise WordOperationError(
        "SELECTION_NOT_FOUND",
        f"未找到选区边界文字：{anchor}{qualifier}",
    )


def validate_supported_range(start: ParagraphRef, end: ParagraphRef) -> None:
    if end.order < start.order:
        raise ValueError("右边界位于左边界之前。")
    if start is end:
        return
    if start.kind == "body" and end.kind == "body":
        return
    if start.container is end.container and start.kind.startswith("table:") and end.kind.startswith("table:"):
        return
    raise ValueError("跨段落选区目前只支持正文，或同一表格单元格内；不同单元格之间请拆成多次操作。")


def extract_selected_text(
    refs: list[ParagraphRef],
    start: ParagraphRef,
    start_offset: int,
    end: ParagraphRef,
    end_offset: int,
) -> str:
    if start is end:
        return start.text[start_offset:end_offset]
    parts = [start.text[start_offset:]]
    parts.extend(ref.text for ref in refs[start.order + 1 : end.order] if ref.text)
    parts.append(end.text[:end_offset])
    return "\n".join(parts)


def count_selected_equations(
    refs: list[ParagraphRef],
    start: ParagraphRef,
    start_offset: int,
    end: ParagraphRef,
    end_offset: int,
) -> int:
    if start is end:
        return count_equations_in_character_range(start.paragraph, start_offset, end_offset)
    count = count_equations_in_character_range(start.paragraph, start_offset, len(start.text))
    count += sum(count_equations(ref.paragraph._p) for ref in refs[start.order + 1 : end.order])
    count += count_equations_in_character_range(end.paragraph, 0, end_offset)
    return count


def paragraph_location(ref: ParagraphRef, offset: int) -> dict[str, Any]:
    return {
        "paragraph_order": ref.order,
        "body_block_index": ref.body_index,
        "container": ref.kind,
        "character_offset": offset,
        "text": ref.text,
    }


def node_text_length(node: Any) -> int:
    return sum(len(text.text or "") for text in node.iter(W_T))


def count_equations(root: Any) -> int:
    return sum(1 for node in root.iter() if node.tag == OMATH_TAG)


def count_equations_in_character_range(paragraph: Paragraph, start: int, end: int) -> int:
    if start == end:
        return 0
    cursor = 0
    count = 0
    for node in paragraph._p.iterchildren():
        if node.tag == W_PPR:
            continue
        length = node_text_length(node)
        if length == 0 and start <= cursor < end:
            count += count_equations(node)
        elif length > 0 and cursor < end and cursor + length > start:
            count += count_equations(node)
        cursor += length
    return count


def positive_int(value: Any, default: int, field: str) -> int:
    if value is None:
        return default
    if not isinstance(value, int) or value < 1:
        raise ValueError(f"selection.{field} 必须是大于等于 1 的整数。")
    return value
