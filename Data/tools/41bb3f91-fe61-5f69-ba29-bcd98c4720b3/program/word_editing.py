from __future__ import annotations

from typing import Any

from word_markdown import append_markdown_fragment
from word_elements import add_elements, set_header_footer
from word_selection import resolve_selection
from word_selection_editing import (
    body_nodes_snapshot,
    delete_selection,
    detach_appended_body_nodes,
    format_selection,
    insert_body_nodes,
    insert_text,
    prepare_block_insertion,
    replace_selection_with_text,
)

OMML_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
OMATH_TAG = f"{{{OMML_NS}}}oMath"


def inspect_document(doc: Any, *, include_paragraphs: bool, include_tables: bool, max_paragraphs: int, max_text_chars: int) -> dict[str, Any]:
    paragraphs = []
    headings = []
    total_text_parts = []
    for index, paragraph in enumerate(doc.paragraphs):
        text = paragraph.text.strip()
        has_equation = paragraph_has_equation(paragraph)
        if text:
            total_text_parts.append(text)
        style_name = paragraph.style.name if paragraph.style is not None else ""
        if style_name.startswith("Heading") and text:
            headings.append({"index": index, "style": style_name, "text": text})
        if include_paragraphs and len(paragraphs) < max_paragraphs:
            paragraphs.append({"index": index, "style": style_name, "text": text, "has_equation": has_equation})

    tables = []
    if include_tables:
        for table_index, table in enumerate(doc.tables):
            rows = []
            for row in table.rows[:20]:
                rows.append([cell.text for cell in row.cells])
            tables.append(
                {
                    "index": table_index,
                    "row_count": len(table.rows),
                    "column_count": len(table.columns),
                    "preview_rows": rows,
                }
            )

    total_text = "\n".join(total_text_parts)
    if len(total_text) > max_text_chars:
        total_text = total_text[:max_text_chars] + f"\n...<truncated {len(total_text) - max_text_chars} chars>"

    return {
        "paragraph_count": len(doc.paragraphs),
        "heading_count": len(headings),
        "table_count": len(doc.tables),
        "inline_shape_count": len(doc.inline_shapes),
        "equation_count": count_equations(doc.element),
        "section_count": len(doc.sections),
        "headings": headings,
        "paragraphs": paragraphs if include_paragraphs else [],
        "tables": tables,
        "header_text": collect_header_footer_text(doc, header=True),
        "footer_text": collect_header_footer_text(doc, header=False),
        "text": total_text,
    }


def apply_operations(doc: Any, operations: list[Any], theme: dict[str, Any], root: Any) -> list[dict[str, Any]]:
    summaries = []
    for operation in operations:
        if not isinstance(operation, dict):
            continue
        operation_type = str(operation.get("type") or "").lower()
        if operation_type == "replace_text":
            summaries.append(replace_text(doc, operation))
        elif operation_type == "append_content":
            elements = operation.get("elements")
            if not isinstance(elements, list):
                raise ValueError("append_content.elements 必须是数组。")
            warnings: list[str] = []
            stats = add_elements(doc, elements, theme, root, warnings=warnings)
            summaries.append({"type": "append_content", "stats": stats, "warnings": warnings})
        elif operation_type == "set_header":
            text = operation.get("text")
            if not isinstance(text, str):
                raise ValueError("set_header.text 必须是字符串。")
            set_header_footer(doc, header=text, theme=theme)
            summaries.append({"type": "set_header"})
        elif operation_type == "set_footer":
            text = operation.get("text")
            if not isinstance(text, str):
                raise ValueError("set_footer.text 必须是字符串。")
            set_header_footer(doc, footer=text, theme=theme)
            summaries.append({"type": "set_footer"})
        elif operation_type == "selection":
            summaries.append(apply_selection_operation(doc, operation, theme, root))
        else:
            raise ValueError(f"不支持的 Word 编辑操作：{operation_type}")
    return summaries


def apply_selection_operation(
    doc: Any,
    operation: dict[str, Any],
    theme: dict[str, Any],
    root: Any,
) -> dict[str, Any]:
    selection = resolve_selection(doc, operation.get("selection"))
    action = str(operation.get("action") or "").strip().lower()
    summary: dict[str, Any] = {
        "type": "selection",
        "action": action,
        "selection": selection.summary(),
        "warnings": [],
    }
    if action == "extract":
        return summary
    if action == "delete":
        summary["removed"] = delete_selection(selection)
        return summary
    if action == "format":
        style = operation.get("style")
        if not isinstance(style, dict) or not style:
            raise ValueError("selection format 操作必须提供非空 style。")
        summary["formatted"] = format_selection(doc, selection, style, theme)
        if selection.equation_count:
            summary["warnings"].append("选区中的 Word 公式保持原样，格式操作仅应用于文字和段落。")
        return summary
    if action not in {"insert", "replace"}:
        raise ValueError("selection.action 必须是 insert、replace、delete、format 或 extract。")

    mode = str(operation.get("content_mode") or "text").strip().lower()
    content = operation.get("content")
    if not isinstance(content, str) or not content:
        raise ValueError("selection insert/replace 操作必须提供非空 content。")
    if mode == "text":
        style = operation.get("style") if isinstance(operation.get("style"), dict) else {}
        if action == "insert":
            insert_text(selection, content, style, theme)
        else:
            summary["removed"] = replace_selection_with_text(selection, content, style, theme)
        summary["content_mode"] = "text"
        summary["inserted_char_count"] = len(content)
        return summary
    if mode != "markdown":
        raise ValueError("selection.content_mode 必须是 text 或 markdown。")

    before = body_nodes_snapshot(doc)
    warnings: list[str] = []
    stats = append_markdown_fragment(doc, content, theme, root, warnings)
    nodes = detach_appended_body_nodes(doc, before)
    parent, insertion_index = prepare_block_insertion(selection, replace=action == "replace")
    summary["inserted_block_count"] = insert_body_nodes(parent, insertion_index, nodes)
    summary["content_mode"] = "markdown"
    summary["stats"] = stats
    summary["warnings"].extend(warnings)
    return summary


def replace_text(doc: Any, operation: dict[str, Any]) -> dict[str, Any]:
    old_text = operation.get("old_text")
    new_text = operation.get("new_text")
    if not isinstance(old_text, str) or not old_text:
        raise ValueError("replace_text.old_text 必须是非空字符串。")
    if not isinstance(new_text, str):
        raise ValueError("replace_text.new_text 必须是字符串。")
    match_case = operation.get("match_case")
    match_case = match_case if isinstance(match_case, bool) else True
    replacements = 0
    rebuilt_paragraphs = 0
    for paragraph in iter_all_paragraphs(doc):
        replaced, rebuilt = replace_in_paragraph(paragraph, old_text, new_text, match_case=match_case)
        replacements += replaced
        rebuilt_paragraphs += 1 if rebuilt else 0
    return {
        "type": "replace_text",
        "replacements": replacements,
        "rebuilt_paragraphs": rebuilt_paragraphs,
    }


def replace_in_paragraph(paragraph: Any, old_text: str, new_text: str, *, match_case: bool) -> tuple[int, bool]:
    replacements = 0
    for run in paragraph.runs:
        replacements += replace_in_run(run, old_text, new_text, match_case=match_case)
    if replacements:
        return replacements, False
    if paragraph_has_equation(paragraph):
        return 0, False
    text = paragraph.text
    count = text.count(old_text) if match_case else text.lower().count(old_text.lower())
    if not count:
        return 0, False
    paragraph.text = replace_text_value(text, old_text, new_text, match_case=match_case)
    return count, True


def replace_in_run(run: Any, old_text: str, new_text: str, *, match_case: bool) -> int:
    text = run.text or ""
    count = text.count(old_text) if match_case else text.lower().count(old_text.lower())
    if not count:
        return 0
    run.text = replace_text_value(text, old_text, new_text, match_case=match_case)
    return count


def replace_text_value(text: str, old_text: str, new_text: str, *, match_case: bool) -> str:
    if match_case:
        return text.replace(old_text, new_text)
    lower_text = text.lower()
    lower_old = old_text.lower()
    result = []
    start = 0
    old_len = len(old_text)
    while True:
        index = lower_text.find(lower_old, start)
        if index == -1:
            result.append(text[start:])
            break
        result.append(text[start:index])
        result.append(new_text)
        start = index + old_len
    return "".join(result)


def iter_all_paragraphs(doc: Any) -> Any:
    for paragraph in doc.paragraphs:
        yield paragraph
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for paragraph in cell.paragraphs:
                    yield paragraph
    for section in doc.sections:
        for paragraph in section.header.paragraphs:
            yield paragraph
        for paragraph in section.footer.paragraphs:
            yield paragraph


def collect_header_footer_text(doc: Any, *, header: bool) -> list[str]:
    values = []
    for section in doc.sections:
        part = section.header if header else section.footer
        text = "\n".join(p.text for p in part.paragraphs if p.text.strip()).strip()
        if text:
            values.append(text)
    return values


def paragraph_has_equation(paragraph: Any) -> bool:
    return count_equations(paragraph._p) > 0


def count_equations(root: Any) -> int:
    return sum(1 for element in root.iter() if element.tag == OMATH_TAG)
