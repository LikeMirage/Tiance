from __future__ import annotations

from json import dumps
from re import IGNORECASE, search
from typing import Any

from app.domain.llm.chat import (
    ChatMessage,
    ChatMessageContentPart,
    ChatMessageContentPartType,
)

def references_from_chat_message(message: ChatMessage | None) -> list[dict]:
    if message is None:
        return empty_conversation_references()
    return normalize_conversation_references(
        message.internal_metadata.get("conversation_references")
    )


def normalize_conversation_references(value: object) -> list[dict]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def empty_conversation_references() -> list[dict]:
    return []


def build_referenced_user_content(user_content: str, value: object) -> str:
    references = normalize_conversation_references(value)
    blocks: list[str] = []
    for index, item in enumerate(references, start=1):
        reference = item.get("reference")
        if not isinstance(reference, dict):
            continue
        reference_type = item.get("type")
        if reference_type == "file":
            blocks.append(
                _image_file_reference_block(index, reference)
                if _is_image_file_reference(reference)
                else _file_reference_block(index, reference)
            )
        elif reference_type == "text":
            blocks.append(_text_reference_block(index, reference))
        elif reference_type == "image":
            blocks.append(_image_reference_block(index, reference))

    if not blocks:
        return user_content
    joined_blocks = "\n\n".join(blocks)
    context = f"【用户引用内容】\n{joined_blocks}"
    return f"{context}\n\n【用户消息】\n{user_content}"


def build_referenced_user_message_content(
    user_content: str,
    value: object,
    image_parts: tuple[ChatMessageContentPart, ...],
) -> tuple[str, tuple[ChatMessageContentPart, ...]]:
    references = normalize_conversation_references(value)
    if not references:
        return user_content, image_parts

    remaining_parts = list(image_parts)
    content_parts: list[ChatMessageContentPart] = [
        _text_part("【用户引用内容】\n")
    ]
    rendered_count = 0
    for index, item in enumerate(references, start=1):
        reference = item.get("reference")
        if not isinstance(reference, dict):
            continue
        block = _reference_block(index, item.get("type"), reference)
        if not block:
            continue
        if rendered_count:
            content_parts.append(_text_part("\n\n"))
        content_parts.append(_text_part(block))
        rendered_count += 1

        image_path = _reference_image_path(item.get("type"), reference)
        image_part = _take_image_part(remaining_parts, image_path)
        if image_part is not None:
            content_parts.append(image_part)

    content_parts.append(_text_part(f"\n\n【用户消息】\n{user_content}"))
    content_parts.extend(remaining_parts)
    return "", tuple(content_parts)


def _reference_block(index: int, reference_type: object, reference: dict[str, Any]) -> str:
    if reference_type == "file":
        return (
            _image_file_reference_block(index, reference)
            if _is_image_file_reference(reference)
            else _file_reference_block(index, reference)
        )
    if reference_type == "text":
        return _text_reference_block(index, reference)
    if reference_type == "image":
        return _image_reference_block(index, reference)
    return ""


def _reference_image_path(reference_type: object, reference: dict[str, Any]) -> str:
    if reference_type == "file" and _is_image_file_reference(reference):
        return _text(reference, "filePath")
    if reference_type == "image":
        return _text(reference, "imagePath")
    return ""


def _take_image_part(
    parts: list[ChatMessageContentPart],
    image_path: str,
) -> ChatMessageContentPart | None:
    if not image_path:
        return None
    for index, part in enumerate(parts):
        if (
            part.type == ChatMessageContentPartType.IMAGE_REF
            and part.image_ref is not None
            and part.image_ref.path == image_path
        ):
            return parts.pop(index)
    return None


def _text_part(text: str) -> ChatMessageContentPart:
    return ChatMessageContentPart(type=ChatMessageContentPartType.TEXT, text=text)


def _file_reference_block(index: int, reference: dict[str, Any]) -> str:
    kind = _text(reference, "kind")
    kind_text = "文件夹" if kind == "folder" else "文件"
    source_text = "外部路径" if _text(reference, "source") == "external_path" else "工作区"
    return "\n".join(
        (
            f"{index}. 【{kind_text}引用】",
            f"- 名称：{_text(reference, 'fileName')}",
            f"- 类型：{source_text}{kind_text}",
            f"- 路径：{_text(reference, 'filePath')}",
        )
    )


def _text_reference_block(index: int, reference: dict[str, Any]) -> str:
    return "\n".join(
        (
            f"{index}. 【文本选区引用】",
            f"- 来源：{_text(reference, 'fileName')}",
            f"- 路径：{_text(reference, 'filePath')}",
            f"- 位置：{_text_reference_position(reference)}",
            "- 内容：",
            _text(reference, "content"),
        )
    )


def _image_reference_block(index: int, reference: dict[str, Any]) -> str:
    source = _text(reference, "source")
    if source == "pdf_page":
        return "\n".join(
            (
                f"{index}. 【PDF 页面引用】",
                f"- 来源：{_text(reference, 'sourceFileName')}",
                f"- 路径：{_text(reference, 'sourceFilePath')}",
                f"- 页码：{_optional_text(reference, 'pageNumber')}",
                f"- 页面图片：{_text(reference, 'imagePath')}",
            )
        )
    if source == "ppt_slide":
        return "\n".join(
            (
                f"{index}. 【PPT 幻灯片引用】",
                f"- 来源：{_text(reference, 'sourceFileName')}",
                f"- 路径：{_text(reference, 'sourceFilePath')}",
                f"- 幻灯片：{_optional_text(reference, 'slideNumber')}",
                f"- 页面图片：{_text(reference, 'imagePath')}",
            )
        )
    return "\n".join(
        (
            f"{index}. 【Excel 区域引用】",
            f"- 来源：{_text(reference, 'sourceFileName')}",
            f"- 路径：{_text(reference, 'sourceFilePath')}",
            f"- Sheet：{_optional_text(reference, 'sheetName')}",
            f"- 范围：{_optional_text(reference, 'rangeAddress')}",
            f"- 区域截图：{_text(reference, 'imagePath')}",
            "- 单元格数据：",
            dumps(reference.get("cells") or [], ensure_ascii=False, indent=2),
        )
    )


def _image_file_reference_block(index: int, reference: dict[str, Any]) -> str:
    return "\n".join(
        (
            f"{index}. 【图片引用】",
            f"- 名称：{_text(reference, 'fileName')}",
            f"- 图片路径：{_text(reference, 'filePath')}",
        )
    )


def _text_reference_position(reference: dict[str, Any]) -> str:
    start_line = reference.get("startLine")
    end_line = reference.get("endLine")
    if isinstance(start_line, int) and isinstance(end_line, int):
        return f"L{start_line}" if start_line == end_line else f"L{start_line}-L{end_line}"
    return {
        "markdown_preview": "Markdown 预览选区",
        "markdown_visual": "Markdown 编辑选区",
        "pdf": "PDF 选区",
        "office": "Office 文档选区",
    }.get(_text(reference, "source"), "文本选区")


def _is_image_file_reference(reference: dict[str, Any]) -> bool:
    if _text(reference, "kind") != "file":
        return False
    file_path = _text(reference, "filePath").replace("\\", "/")
    file_name = _text(reference, "fileName")
    return bool(
        search(r"(^|/)\.Tiance/conversation_references/images/", file_path, flags=IGNORECASE)
        or search(r"\.(png|jpe?g|webp|gif|bmp|tiff?|svg)$", file_name, flags=IGNORECASE)
        or search(r"\.(png|jpe?g|webp|gif|bmp|tiff?|svg)$", file_path, flags=IGNORECASE)
    )


def _text(value: dict[str, Any], key: str) -> str:
    item = value.get(key)
    return item if isinstance(item, str) else ""


def _optional_text(value: dict[str, Any], key: str) -> str:
    item = value.get(key)
    return str(item) if item is not None and item != "" else "-"
