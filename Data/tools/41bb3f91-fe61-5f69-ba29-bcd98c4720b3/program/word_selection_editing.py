from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable

from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph
from docx.text.run import Run
from docx.shared import Pt

from word_elements import apply_font, apply_paragraph_format, parse_color, set_font_family
from word_selection import (
    ParagraphRef,
    SelectionRange,
    W_P,
    W_PPR,
    W_TBL,
    count_equations,
    node_text_length,
    paragraph_plain_text,
)

W_R = qn("w:r")
OMATH_PARA_TAG = "{http://schemas.openxmlformats.org/officeDocument/2006/math}oMathPara"


UNSAFE_PARTIAL_TAGS = {
    qn("w:drawing"),
    qn("w:object"),
    qn("w:pict"),
    qn("w:fldChar"),
    qn("w:instrText"),
}


def delete_selection(selection: SelectionRange) -> dict[str, int]:
    require_nonempty(selection, "delete")
    removed = {"characters": 0, "equations": 0, "blocks": 0}
    if selection.equation_targets and selection.start is selection.end and selection.start_offset == selection.end_offset:
        removed["equations"] = delete_equation_targets(selection.equation_targets)
        refresh_ref(selection.start)
        return removed

    if selection.same_paragraph:
        merge_counts(
            removed,
            rewrite_paragraph_range(
                selection.start.paragraph,
                selection.start_offset,
                selection.end_offset,
                [],
            ),
        )
        # Explicit formula targets may sit at the caret and not be covered by text range.
        removed["equations"] += delete_equation_targets(
            [node for node in selection.equation_targets if node.getparent() is not None]
        )
        refresh_ref(selection.start)
        return removed

    if selection.same_container and selection.start.kind.startswith("table:"):
        merge_counts(removed, delete_same_container_range(selection))
        refresh_ref(selection.start)
        refresh_ref(selection.end)
        return removed

    merge_counts(
        removed,
        rewrite_paragraph_range(
            selection.start.paragraph,
            selection.start_offset,
            len(selection.start.text),
            [],
        ),
    )
    merge_counts(
        removed,
        rewrite_paragraph_range(selection.end.paragraph, 0, selection.end_offset, []),
    )
    body = selection.start.body_block.getparent()
    start_index = body.index(selection.start.body_block)
    end_index = body.index(selection.end.body_block)
    for node in list(body)[start_index + 1 : end_index]:
        removed["equations"] += count_equations(node)
        removed["blocks"] += 1
        body.remove(node)
    refresh_ref(selection.start)
    refresh_ref(selection.end)
    return removed


def delete_same_container_range(selection: SelectionRange) -> dict[str, int]:
    removed = {"characters": 0, "equations": 0, "blocks": 0}
    container = selection.start.container
    paragraphs = [child for child in list(container) if child.tag == W_P]
    start_p = selection.start.paragraph._p
    end_p = selection.end.paragraph._p
    start_index = paragraphs.index(start_p)
    end_index = paragraphs.index(end_p)
    merge_counts(
        removed,
        rewrite_paragraph_range(
            selection.start.paragraph,
            selection.start_offset,
            len(selection.start.text),
            [],
        ),
    )
    for paragraph_element in paragraphs[start_index + 1 : end_index]:
        removed["equations"] += count_equations(paragraph_element)
        removed["blocks"] += 1
        container.remove(paragraph_element)
    merge_counts(
        removed,
        rewrite_paragraph_range(selection.end.paragraph, 0, selection.end_offset, []),
    )
    return removed


def delete_equation_targets(targets: list[Any]) -> int:
    removed = 0
    for omath in targets:
        parent = omath.getparent()
        if parent is None:
            continue
        parent.remove(omath)
        removed += 1
        # Drop empty oMathPara wrappers left behind.
        if parent.tag == OMATH_PARA_TAG and len(parent) == 0:
            grand = parent.getparent()
            if grand is not None:
                grand.remove(parent)
    return removed


def replace_selection_with_text(
    selection: SelectionRange,
    text: str,
    style: dict[str, Any],
    theme: dict[str, Any],
) -> dict[str, int]:
    require_nonempty(selection, "replace")
    new_run = make_text_run(selection.start.paragraph, text, style, theme)
    if selection.equation_targets and selection.start is selection.end and selection.start_offset == selection.end_offset:
        removed = {"characters": 0, "equations": delete_equation_targets(selection.equation_targets), "blocks": 0}
        rewrite_paragraph_range(
            selection.start.paragraph,
            selection.start_offset,
            selection.start_offset,
            [new_run],
        )
        refresh_ref(selection.start)
        return removed
    if selection.same_paragraph:
        removed = rewrite_paragraph_range(
            selection.start.paragraph,
            selection.start_offset,
            selection.end_offset,
            [new_run],
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
            [new_run],
        )
    refresh_ref(selection.start)
    return removed


def insert_text(
    selection: SelectionRange,
    text: str,
    style: dict[str, Any],
    theme: dict[str, Any],
) -> None:
    rewrite_paragraph_range(
        selection.start.paragraph,
        selection.start_offset,
        selection.start_offset,
        [make_text_run(selection.start.paragraph, text, style, theme)],
    )
    refresh_ref(selection.start)


def format_selection(
    doc: Any,
    selection: SelectionRange,
    style: dict[str, Any],
    theme: dict[str, Any],
) -> dict[str, int]:
    require_nonempty(selection, "format")
    result = {"paragraphs": 0, "runs": 0, "equations_skipped": selection.equation_count}
    if selection.same_paragraph:
        result["runs"] = format_paragraph_range(
            selection.start.paragraph,
            selection.start_offset,
            selection.end_offset,
            style,
            theme,
        )
        result["paragraphs"] = 1
        return result

    if selection.same_container and selection.start.kind.startswith("table:"):
        return format_same_container_range(selection, style, theme)

    result["runs"] += format_paragraph_range(
        selection.start.paragraph,
        selection.start_offset,
        len(selection.start.text),
        style,
        theme,
    )
    result["paragraphs"] += 1
    body = doc.element.body
    start_index = body.index(selection.start.body_block)
    end_index = body.index(selection.end.body_block)
    for block in list(body)[start_index + 1 : end_index]:
        for paragraph in paragraphs_in_body_block(block, doc):
            result["runs"] += format_paragraph_range(
                paragraph,
                0,
                len(paragraph_plain_text(paragraph)),
                style,
                theme,
            )
            result["paragraphs"] += 1
    result["runs"] += format_paragraph_range(
        selection.end.paragraph,
        0,
        selection.end_offset,
        style,
        theme,
    )
    result["paragraphs"] += 1
    return result


def format_same_container_range(
    selection: SelectionRange,
    style: dict[str, Any],
    theme: dict[str, Any],
) -> dict[str, int]:
    result = {"paragraphs": 0, "runs": 0, "equations_skipped": selection.equation_count}
    container = selection.start.container
    paragraphs = [child for child in list(container) if child.tag == W_P]
    start_index = paragraphs.index(selection.start.paragraph._p)
    end_index = paragraphs.index(selection.end.paragraph._p)
    result["runs"] += format_paragraph_range(
        selection.start.paragraph,
        selection.start_offset,
        len(selection.start.text),
        style,
        theme,
    )
    result["paragraphs"] += 1
    for paragraph_element in paragraphs[start_index + 1 : end_index]:
        paragraph = Paragraph(paragraph_element, selection.start.paragraph._parent)
        result["runs"] += format_paragraph_range(
            paragraph,
            0,
            len(paragraph_plain_text(paragraph)),
            style,
            theme,
        )
        result["paragraphs"] += 1
    result["runs"] += format_paragraph_range(
        selection.end.paragraph,
        0,
        selection.end_offset,
        style,
        theme,
    )
    result["paragraphs"] += 1
    return result


def prepare_block_insertion(selection: SelectionRange, *, replace: bool) -> tuple[Any, int]:
    if selection.start.kind != "body":
        raise ValueError("Markdown 块只能插入正文；表格单元格内请使用 text 模式。")
    cross_paragraph = not selection.same_paragraph
    if replace:
        require_nonempty(selection, "replace")
        if selection.equation_targets and selection.start is selection.end and selection.start_offset == selection.end_offset:
            delete_equation_targets(selection.equation_targets)
            parent = selection.start.paragraph._p.getparent()
            return parent, parent.index(selection.start.paragraph._p) + 1
        delete_selection(selection)
        if cross_paragraph:
            parent = selection.start.paragraph._p.getparent()
            return parent, parent.index(selection.start.paragraph._p) + 1
    right = split_paragraph_at(selection.start.paragraph, selection.start_offset)
    parent = selection.start.paragraph._p.getparent()
    return parent, parent.index(right)


def insert_body_nodes(parent: Any, index: int, nodes: Iterable[Any]) -> int:
    inserted = 0
    for node in nodes:
        parent.insert(index + inserted, node)
        inserted += 1
    return inserted


def detach_appended_body_nodes(doc: Any, before_nodes: set[Any]) -> list[Any]:
    body = doc.element.body
    nodes = [node for node in list(body) if node.tag != qn("w:sectPr") and node not in before_nodes]
    for node in nodes:
        body.remove(node)
    return nodes


def body_nodes_snapshot(doc: Any) -> set[Any]:
    return set(doc.element.body.iterchildren())


def rewrite_paragraph_range(
    paragraph: Paragraph,
    start: int,
    end: int,
    replacement_nodes: list[Any],
) -> dict[str, int]:
    text_length = len(paragraph_plain_text(paragraph))
    if not 0 <= start <= end <= text_length:
        raise ValueError("选区字符范围无效。")
    before, selected, after = partition_inline_nodes(paragraph, start, end)
    removed = {
        "characters": end - start,
        "equations": sum(count_equations(node) for node in selected),
        "blocks": 0,
    }
    replace_paragraph_children(paragraph, before + replacement_nodes + after)
    return removed


def format_paragraph_range(
    paragraph: Paragraph,
    start: int,
    end: int,
    style: dict[str, Any],
    theme: dict[str, Any],
) -> int:
    if start == end:
        return 0
    before, selected, after = partition_inline_nodes(paragraph, start, end)
    run_count = 0
    for node in selected:
        for run_element in node.iter(W_R):
            apply_font_patch(Run(run_element, paragraph).font, style, theme)
            run_count += 1
    replace_paragraph_children(paragraph, before + selected + after)
    if any(key in style for key in ("align", "space_after", "space_before", "line_spacing")):
        apply_paragraph_format(paragraph, style)
    return run_count


def split_paragraph_at(paragraph: Paragraph, offset: int) -> Any:
    before, _, after = partition_inline_nodes(paragraph, offset, offset)
    paragraph_element = paragraph._p
    right = OxmlElement("w:p")
    properties = paragraph_element.find(W_PPR)
    if properties is not None:
        right.append(deepcopy(properties))
    replace_paragraph_children(paragraph, before)
    for node in after:
        right.append(node)
    parent = paragraph_element.getparent()
    parent.insert(parent.index(paragraph_element) + 1, right)
    return right


def partition_inline_nodes(
    paragraph: Paragraph,
    start: int,
    end: int,
) -> tuple[list[Any], list[Any], list[Any]]:
    before: list[Any] = []
    selected: list[Any] = []
    after: list[Any] = []
    cursor = 0
    for original in paragraph._p.iterchildren():
        if original.tag == W_PPR:
            continue
        length = node_text_length(original)
        node_start, node_end = cursor, cursor + length
        if length == 0:
            clone = deepcopy(original)
            if end > start and start <= cursor < end:
                selected.append(clone)
            elif cursor < start:
                before.append(clone)
            else:
                after.append(clone)
            continue
        if node_end <= start:
            before.append(deepcopy(original))
        elif node_start >= end:
            after.append(deepcopy(original))
        else:
            ensure_safe_partial_node(original, node_start, node_end, start, end)
            prefix_end = max(0, min(length, start - node_start))
            selected_start = max(0, start - node_start)
            selected_end = min(length, end - node_start)
            suffix_start = max(0, min(length, end - node_start))
            if prefix_end > 0:
                before.append(slice_text_node(original, 0, prefix_end))
            if selected_end > selected_start:
                selected.append(slice_text_node(original, selected_start, selected_end))
            if suffix_start < length:
                after.append(slice_text_node(original, suffix_start, length))
        cursor = node_end
    return before, selected, after


def slice_text_node(node: Any, start: int, end: int) -> Any:
    clone = deepcopy(node)
    cursor = 0
    for text_node in clone.iter(qn("w:t")):
        value = text_node.text or ""
        node_start, node_end = cursor, cursor + len(value)
        left = max(start, node_start)
        right = min(end, node_end)
        text_node.text = value[left - node_start : right - node_start] if right > left else ""
        if text_node.text.startswith(" ") or text_node.text.endswith(" "):
            text_node.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        cursor = node_end
    return clone


def ensure_safe_partial_node(node: Any, node_start: int, node_end: int, start: int, end: int) -> None:
    partial = start > node_start or end < node_end
    if partial and any(element.tag in UNSAFE_PARTIAL_TAGS for element in node.iter()):
        raise ValueError("选区边界落在图片、域或嵌入对象内部；请改用更靠外的纯文字边界。")


def replace_paragraph_children(paragraph: Paragraph, nodes: list[Any]) -> None:
    element = paragraph._p
    for child in list(element):
        if child.tag != W_PPR:
            element.remove(child)
    for node in nodes:
        element.append(node)


def make_text_run(paragraph: Paragraph, text: str, style: dict[str, Any], theme: dict[str, Any]) -> Any:
    run = paragraph.add_run(text)
    apply_font(run.font, style, theme)
    node = run._r
    paragraph._p.remove(node)
    return node


def apply_font_patch(font: Any, style: dict[str, Any], theme: dict[str, Any]) -> None:
    font_keys = {
        "font_family",
        "east_asia_font",
        "eastAsia_font",
        "cjk_font",
        "complex_script_font",
        "cs_font",
    }
    if font_keys.intersection(style):
        font_family = str(style.get("font_family") or font.name or theme["font_family"])
        east_asia_font = str(
            style.get("east_asia_font")
            or style.get("eastAsia_font")
            or style.get("cjk_font")
            or theme["east_asia_font"]
            or font_family
        )
        complex_script_font = str(
            style.get("complex_script_font")
            or style.get("cs_font")
            or theme["complex_script_font"]
            or font_family
        )
        set_font_family(
            font,
            font_family,
            east_asia_font=east_asia_font,
            complex_script_font=complex_script_font,
        )
    if isinstance(style.get("font_size"), (int, float)):
        font.size = Pt(float(style["font_size"]))
    for key in ("bold", "italic", "underline", "strike"):
        if key in style:
            setattr(font, key, bool(style[key]))
    if "color" in style:
        font.color.rgb = parse_color(style["color"])


def paragraphs_in_body_block(block: Any, doc: Any) -> Iterable[Paragraph]:
    if block.tag == W_P:
        yield Paragraph(block, doc)
        return
    if block.tag != W_TBL:
        return
    table = Table(block, doc)
    seen: set[Any] = set()
    for row in table.rows:
        for cell in row.cells:
            for paragraph in cell.paragraphs:
                if paragraph._p in seen:
                    continue
                seen.add(paragraph._p)
                yield paragraph


def refresh_ref(ref: ParagraphRef) -> None:
    ref.text = paragraph_plain_text(ref.paragraph)


def require_nonempty(selection: SelectionRange, action: str) -> None:
    if selection.empty:
        raise ValueError(f"零长度选区只能执行 insert，不能执行 {action}。")


def merge_counts(target: dict[str, int], source: dict[str, int]) -> None:
    for key, value in source.items():
        target[key] = target.get(key, 0) + value
