from __future__ import annotations

from copy import deepcopy
from typing import Any

from ppt_elements import add_slide


def inspect_deck(prs: Any, *, include_text_runs: bool, max_text_chars_per_slide: int) -> dict[str, Any]:
    slides: list[dict[str, Any]] = []
    for index, slide in enumerate(prs.slides):
        texts: list[str] = []
        runs: list[dict[str, Any]] = []
        shape_count = 0
        picture_count = 0
        table_count = 0
        for shape_index, shape in enumerate(slide.shapes):
            shape_count += 1
            if getattr(shape, "shape_type", None) == 13:
                picture_count += 1
            if getattr(shape, "has_table", False):
                table_count += 1
                for cell in iter_table_cells(shape):
                    text = cell.text_frame.text.strip()
                    if text:
                        texts.append(text)
                    if include_text_runs:
                        for paragraph_index, paragraph in enumerate(cell.text_frame.paragraphs):
                            for run_index, run in enumerate(paragraph.runs):
                                if run.text:
                                    runs.append(
                                        {
                                            "shape_index": shape_index,
                                            "paragraph_index": paragraph_index,
                                            "run_index": run_index,
                                            "text": run.text,
                                            "source": "table_cell",
                                        }
                                    )
            if getattr(shape, "has_text_frame", False):
                text = shape.text_frame.text.strip()
                if text:
                    texts.append(text)
                if include_text_runs:
                    for paragraph_index, paragraph in enumerate(shape.text_frame.paragraphs):
                        for run_index, run in enumerate(paragraph.runs):
                            if run.text:
                                runs.append(
                                    {
                                        "shape_index": shape_index,
                                        "paragraph_index": paragraph_index,
                                        "run_index": run_index,
                                        "text": run.text,
                                    }
                                )
        joined_text = "\n".join(texts)
        if len(joined_text) > max_text_chars_per_slide:
            joined_text = joined_text[:max_text_chars_per_slide] + f"\n...<truncated {len(joined_text) - max_text_chars_per_slide} chars>"
        item: dict[str, Any] = {
            "slide_index": index,
            "text": joined_text,
            "shape_count": shape_count,
            "picture_count": picture_count,
            "table_count": table_count,
        }
        if include_text_runs:
            item["text_runs"] = runs
        slides.append(item)
    return {
        "slide_count": len(prs.slides),
        "slide_width": int(prs.slide_width),
        "slide_height": int(prs.slide_height),
        "slides": slides,
    }


def apply_operations(prs: Any, operations: list[Any], theme: dict[str, Any], root: Any) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    normalize_slide_partnames(prs)
    for operation in operations:
        if not isinstance(operation, dict):
            continue
        operation_type = str(operation.get("type") or "").lower()
        if operation_type == "replace_text":
            summaries.append(replace_text(prs, operation))
        elif operation_type == "set_slide_title":
            summaries.append(set_slide_title(prs, operation, theme))
        elif operation_type == "add_slide":
            summaries.append(add_slide_operation(prs, operation, theme, root))
        elif operation_type == "delete_slide":
            summaries.append(delete_slide(prs, operation))
        elif operation_type == "duplicate_slide":
            summaries.append(duplicate_slide_operation(prs, operation))
        elif operation_type == "move_slide":
            summaries.append(move_slide_operation(prs, operation))
        elif operation_type == "reorder_slides":
            summaries.append(reorder_slides_operation(prs, operation))
        else:
            raise ValueError(f"不支持的编辑操作：{operation_type}")
    return summaries


def replace_text(prs: Any, operation: dict[str, Any]) -> dict[str, Any]:
    old_text = operation.get("old_text")
    new_text = operation.get("new_text")
    if not isinstance(old_text, str) or old_text == "":
        raise ValueError("replace_text.old_text 必须是非空字符串。")
    if not isinstance(new_text, str):
        raise ValueError("replace_text.new_text 必须是字符串。")
    slide_indexes = selected_slide_indexes(prs, operation.get("slide_indexes"))
    match_case = operation.get("match_case")
    match_case = match_case if isinstance(match_case, bool) else True
    replacements = 0
    touched_slides: set[int] = set()
    for slide_index in slide_indexes:
        slide = prs.slides[slide_index]
        for shape in slide.shapes:
            for text_frame in iter_text_frames(shape):
                for paragraph in text_frame.paragraphs:
                    for run in paragraph.runs:
                        replaced = replace_in_run(run, old_text, new_text, match_case=match_case)
                        if replaced:
                            replacements += replaced
                            touched_slides.add(slide_index)
    return {
        "type": "replace_text",
        "replacements": replacements,
        "slides": sorted(touched_slides),
    }


def replace_in_run(run: Any, old_text: str, new_text: str, *, match_case: bool) -> int:
    text = run.text or ""
    if match_case:
        count = text.count(old_text)
        if count:
            run.text = text.replace(old_text, new_text)
        return count
    lower_text = text.lower()
    lower_old = old_text.lower()
    count = lower_text.count(lower_old)
    if not count:
        return 0
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
    run.text = "".join(result)
    return count


def set_slide_title(prs: Any, operation: dict[str, Any], theme: dict[str, Any]) -> dict[str, Any]:
    slide_index = read_slide_index(prs, operation.get("slide_index"))
    title = operation.get("title")
    if not isinstance(title, str):
        raise ValueError("set_slide_title.title 必须是字符串。")
    slide = prs.slides[slide_index]
    for shape in slide.shapes:
        if getattr(shape, "has_text_frame", False) and shape.text_frame.text.strip():
            shape.text_frame.text = title
            return {"type": "set_slide_title", "slide_index": slide_index, "created": False}
    add_slide_title(slide, title, theme)
    return {"type": "set_slide_title", "slide_index": slide_index, "created": True}


def add_slide_title(slide: Any, title: str, theme: dict[str, Any]) -> None:
    from ppt_elements import add_title

    add_title(slide, title, theme)


def add_slide_operation(prs: Any, operation: dict[str, Any], theme: dict[str, Any], root: Any) -> dict[str, Any]:
    slide_spec = operation.get("slide")
    if not isinstance(slide_spec, dict):
        raise ValueError("add_slide.slide 必须是对象。")
    target_index = read_insert_index(prs, operation.get("index"))
    add_slide(prs, slide_spec, theme, root)
    new_index = len(prs.slides) - 1
    if target_index < new_index:
        move_slide(prs, new_index, target_index)
        new_index = target_index
    return {"type": "add_slide", "slide_index": new_index}


def duplicate_slide_operation(prs: Any, operation: dict[str, Any]) -> dict[str, Any]:
    source_index = read_slide_index(prs, operation.get("slide_index"))
    target_index = read_insert_index(prs, operation.get("index"))
    new_index = duplicate_slide(prs, source_index)
    if target_index < new_index:
        move_slide(prs, new_index, target_index)
        new_index = target_index
    return {"type": "duplicate_slide", "source_slide_index": source_index, "slide_index": new_index}


def move_slide_operation(prs: Any, operation: dict[str, Any]) -> dict[str, Any]:
    source_index = read_slide_index(prs, operation.get("slide_index"))
    target_index = read_slide_index(prs, operation.get("index"))
    if source_index != target_index:
        move_slide(prs, source_index, target_index)
    return {"type": "move_slide", "source_slide_index": source_index, "slide_index": target_index}


def reorder_slides_operation(prs: Any, operation: dict[str, Any]) -> dict[str, Any]:
    value = operation.get("slide_indexes")
    if not isinstance(value, list) or not value:
        raise ValueError("reorder_slides.slide_indexes 必须是非空数组。")
    slide_indexes = [read_slide_index(prs, item) for item in value]
    if len(slide_indexes) != len(prs.slides) or sorted(slide_indexes) != list(range(len(prs.slides))):
        raise ValueError("reorder_slides.slide_indexes 必须包含当前所有页码且不能重复。")
    reorder_slides(prs, slide_indexes)
    return {"type": "reorder_slides", "slide_indexes": slide_indexes}


def delete_slide(prs: Any, operation: dict[str, Any]) -> dict[str, Any]:
    if operation.get("confirm_delete") is not True:
        raise ValueError("delete_slide 必须设置 confirm_delete=true。")
    slide_indexes = delete_slide_indexes(prs, operation)
    remove_slides(prs, slide_indexes)
    return {"type": "delete_slide", "slide_indexes": slide_indexes}


def delete_slide_indexes(prs: Any, operation: dict[str, Any]) -> list[int]:
    if operation.get("slide_indexes") is not None:
        value = operation.get("slide_indexes")
        if not isinstance(value, list) or not value:
            raise ValueError("delete_slide.slide_indexes 必须是非空数组。")
        slide_indexes = [read_slide_index(prs, item) for item in value]
    elif operation.get("slide_index") is not None:
        slide_indexes = [read_slide_index(prs, operation.get("slide_index"))]
    else:
        raise ValueError("delete_slide 必须提供 slide_index 或 slide_indexes。")

    unique_indexes = sorted(set(slide_indexes))
    if len(unique_indexes) >= len(prs.slides):
        raise ValueError("delete_slide 不能删除全部幻灯片。")
    return unique_indexes


def move_slide(prs: Any, source_index: int, target_index: int) -> None:
    slide_id_list = prs.slides._sldIdLst
    slide_ids = list(slide_id_list)
    slide_id = slide_ids[source_index]
    slide_id_list.remove(slide_id)
    slide_id_list.insert(target_index, slide_id)


def duplicate_slide(prs: Any, source_index: int) -> int:
    source = prs.slides[source_index]
    new_slide = prs.slides.add_slide(source.slide_layout)
    clear_slide_shapes(new_slide)
    rel_map = copy_slide_relationships(source, new_slide)
    copy_slide_background(source, new_slide, rel_map)
    for shape in source.shapes:
        new_element = deepcopy(shape._element)
        remap_relationship_ids(new_element, rel_map)
        new_slide.shapes._spTree.insert_element_before(new_element, "p:extLst")
    return len(prs.slides) - 1


def select_slides_by_sequence(prs: Any, slide_indexes: list[Any]) -> list[int]:
    original_count = len(prs.slides)
    if not slide_indexes:
        raise ValueError("template_slide_indexes 必须是非空数组。")
    selected = [read_index_from_count(item, original_count, "template_slide_indexes") for item in slide_indexes]
    for source_index in selected:
        duplicate_slide(prs, source_index)
    remove_slides(prs, list(range(original_count)), allow_all=True)
    normalize_slide_partnames(prs)
    return selected


def reorder_slides(prs: Any, slide_indexes: list[int]) -> None:
    slide_id_list = prs.slides._sldIdLst
    slide_ids = list(slide_id_list)
    for slide_id in slide_ids:
        slide_id_list.remove(slide_id)
    for source_index in slide_indexes:
        slide_id_list.append(slide_ids[source_index])


def remove_slides(prs: Any, slide_indexes: list[int], *, allow_all: bool = False) -> None:
    if not allow_all and len(set(slide_indexes)) >= len(prs.slides):
        raise ValueError("不能删除全部幻灯片。")
    slide_id_list = prs.slides._sldIdLst
    slide_ids = list(slide_id_list)
    for slide_index in sorted(set(slide_indexes), reverse=True):
        relation_id = slide_ids[slide_index].rId
        prs.part.drop_rel(relation_id)
        slide_id_list.remove(slide_ids[slide_index])
    normalize_slide_partnames(prs)


def normalize_slide_partnames(prs: Any) -> None:
    slide_id_list = prs.slides._sldIdLst
    if len(slide_id_list) == 0:
        return
    prs.part.rename_slide_parts([slide_id.rId for slide_id in slide_id_list])


def copy_slide_background(source: Any, target: Any, rel_map: dict[str, str]) -> None:
    source_bg = source._element.cSld.bg
    if source_bg is None:
        return
    new_bg = deepcopy(source_bg)
    remap_relationship_ids(new_bg, rel_map)
    target._element.cSld._remove_bg()
    target._element.cSld.insert(0, new_bg)


def clear_slide_shapes(slide: Any) -> None:
    shape_tree = slide.shapes._spTree
    for shape in list(slide.shapes):
        shape_tree.remove(shape._element)


def copy_slide_relationships(source: Any, target: Any) -> dict[str, str]:
    rel_map: dict[str, str] = {}
    for old_rid, rel in source.part.rels.items():
        rel_type = str(rel.reltype)
        if rel_type.endswith("/slideLayout") or rel_type.endswith("/notesSlide"):
            continue
        if rel.is_external:
            new_rid = target.part.relate_to(rel.target_ref, rel_type, is_external=True)
        else:
            new_rid = target.part.relate_to(rel.target_part, rel_type)
        rel_map[str(old_rid)] = str(new_rid)
    return rel_map


def remap_relationship_ids(element: Any, rel_map: dict[str, str]) -> None:
    if not rel_map:
        return
    relationship_ns = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    for node in element.iter():
        for attr_name, attr_value in list(node.attrib.items()):
            if attr_name.startswith(f"{{{relationship_ns}}}") and attr_value in rel_map:
                node.attrib[attr_name] = rel_map[attr_value]


def iter_text_frames(shape: Any) -> Any:
    if getattr(shape, "has_text_frame", False):
        yield shape.text_frame
    if getattr(shape, "has_table", False):
        for cell in iter_table_cells(shape):
            yield cell.text_frame


def iter_table_cells(shape: Any) -> Any:
    table = shape.table
    for row in table.rows:
        for cell in row.cells:
            yield cell


def selected_slide_indexes(prs: Any, value: Any) -> list[int]:
    if value is None:
        return list(range(len(prs.slides)))
    if not isinstance(value, list):
        raise ValueError("slide_indexes 必须是数组。")
    return [read_slide_index(prs, item) for item in value]


def read_slide_index(prs: Any, value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("slide_index 必须是整数。")
    if value < 0 or value >= len(prs.slides):
        raise ValueError(f"slide_index 超出范围：{value}")
    return value


def read_insert_index(prs: Any, value: Any) -> int:
    if value is None:
        return len(prs.slides)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("index 必须是整数。")
    if value < 0 or value > len(prs.slides):
        raise ValueError(f"index 超出范围：{value}")
    return value


def read_index_from_count(value: Any, count: int, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} 必须是整数数组。")
    if value < 0 or value >= count:
        raise ValueError(f"{field_name} 页码超出范围：{value}")
    return value
