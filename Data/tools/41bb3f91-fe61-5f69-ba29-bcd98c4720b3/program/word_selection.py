from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph


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

    @property
    def empty(self) -> bool:
        return self.start is self.end and self.start_offset == self.end_offset

    @property
    def same_paragraph(self) -> bool:
        return self.start is self.end

    def summary(self) -> dict[str, Any]:
        return {
            "kind": "point" if self.empty else "range",
            "start": paragraph_location(self.start, self.start_offset),
            "end": paragraph_location(self.end, self.end_offset),
            "start_anchor": self.start_anchor,
            "end_anchor": self.end_anchor or "",
            "selected_text": self.selected_text,
            "selected_char_count": len(self.selected_text),
            "equation_count": self.equation_count,
        }


def resolve_selection(doc: Any, spec: Any) -> SelectionRange:
    if not isinstance(spec, dict):
        raise ValueError("selection 必须是对象。")
    start_anchor = spec.get("start_anchor")
    if not isinstance(start_anchor, str) or not start_anchor:
        raise ValueError("selection.start_anchor 必须是非空纯文字。")
    end_anchor = spec.get("end_anchor")
    if end_anchor is not None and (not isinstance(end_anchor, str) or not end_anchor):
        raise ValueError("selection.end_anchor 必须是非空纯文字；省略表示插入点。")
    match_case = spec.get("match_case")
    match_case = match_case if isinstance(match_case, bool) else True
    start_occurrence = positive_int(spec.get("start_occurrence"), 1, "start_occurrence")
    end_occurrence = positive_int(spec.get("end_occurrence"), 1, "end_occurrence")
    refs = collect_document_paragraphs(doc)
    if not refs:
        raise ValueError("文档正文中没有可定位的段落。")

    start_ref, start_match = find_anchor(
        refs,
        start_anchor,
        occurrence=start_occurrence,
        match_case=match_case,
    )
    start_offset = start_match + len(start_anchor)
    if end_anchor is None:
        end_ref, end_offset = start_ref, start_offset
    else:
        end_ref, end_offset = find_anchor(
            refs,
            end_anchor,
            occurrence=end_occurrence,
            match_case=match_case,
            after=(start_ref.order, start_offset),
        )
    validate_supported_range(start_ref, end_ref)
    return SelectionRange(
        start=start_ref,
        start_offset=start_offset,
        end=end_ref,
        end_offset=end_offset,
        start_anchor=start_anchor,
        end_anchor=end_anchor,
        selected_text=extract_selected_text(refs, start_ref, start_offset, end_ref, end_offset),
        equation_count=count_selected_equations(refs, start_ref, start_offset, end_ref, end_offset),
    )


def collect_document_paragraphs(doc: Any) -> list[ParagraphRef]:
    refs: list[ParagraphRef] = []
    seen_paragraphs: set[Any] = set()
    body = doc.element.body
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
                                kind=f"table:{row_index}:{column_index}:{paragraph_index}",
                                body_block=child,
                                body_index=body_index,
                                container=cell._tc,
                            )
                        )
    return refs


def paragraph_plain_text(paragraph: Paragraph) -> str:
    return "".join(node.text or "" for node in paragraph._p.iter(W_T))


def find_anchor(
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
    raise ValueError(f"未找到选区边界文字：{anchor}{qualifier}")


def validate_supported_range(start: ParagraphRef, end: ParagraphRef) -> None:
    if end.order < start.order:
        raise ValueError("右边界位于左边界之前。")
    if start is end:
        return
    if start.kind != "body" or end.kind != "body":
        raise ValueError("跨段落选区目前只支持正文；不同表格单元格之间请拆成多次操作。")


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
