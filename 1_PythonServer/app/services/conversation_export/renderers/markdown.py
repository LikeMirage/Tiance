from __future__ import annotations

from collections.abc import Callable
import re

from app.domain.project.conversation_export import (
    ConversationExportContentSelection,
    ConversationExportFile,
    ConversationExportImage,
    PreparedConversationExport,
    RenderedConversationExport,
)
from app.domain.project.project_conversation import ProjectConversationMessage
from app.services.document_conversion.markdown_docx.markdown_inline import (
    parse_image_token,
    tokenize_inline,
)

from ..content import (
    message_body,
    message_is_visible,
    message_label,
    parse_tool_result,
    range_label,
    usage_items,
)


class MarkdownConversationExportRenderer:
    def render(
        self,
        prepared: PreparedConversationExport,
        selection: ConversationExportContentSelection,
    ) -> RenderedConversationExport:
        markdown = build_conversation_markdown(prepared, selection)
        unique_assets = {
            image.asset_name: image.content
            for image in prepared.images
        }
        return RenderedConversationExport(
            content=markdown.encode("utf-8"),
            extension=".md",
            bundle=True,
            files=tuple(
                ConversationExportFile(
                    relative_path=f"assets/{asset_name}",
                    content=content,
                )
                for asset_name, content in unique_assets.items()
            ),
        )


def build_conversation_markdown(
    prepared: PreparedConversationExport,
    selection: ConversationExportContentSelection,
    *,
    image_reference: Callable[[ConversationExportImage], str] | None = None,
) -> str:
    document = prepared.document
    lines: list[str] = []

    if selection.session_info:
        lines.extend(
            (
                f"# {_inline_text(document.session.title)}",
                "",
                "## 会话信息",
                "",
                f"- 会话 ID：`{_inline_code(document.session.session_id)}`",
                f"- 导出范围：{range_label(document.export_range.value)}",
                f"- 导出消息数：{len(document.messages)}",
                f"- 导出时间：{document.exported_at.isoformat()}",
            )
        )
        if selection.model_info and document.session.provider_id:
            lines.append(f"- 服务商：{_inline_text(document.session.provider_id)}")
        if selection.model_info and document.session.model_id:
            lines.append(f"- 模型：{_inline_text(document.session.model_id)}")
        lines.append("")

    visible_index = 0
    for message in document.messages:
        images = prepared.images_for_message(message.message_id) if selection.images else ()
        if not message_is_visible(message, selection, has_images=bool(images)):
            continue
        visible_index += 1
        lines.extend((f"## {message_label(message)} {visible_index}", ""))
        lines.extend(_message_metadata_lines(message, selection))

        body = message_body(message, selection).strip()
        rendered_embedded_sources = _embedded_image_sources(body)
        if body:
            lines.extend((_rewrite_embedded_images(body, images, image_reference), ""))
        if selection.thinking and message.thinking_content.strip():
            rendered_embedded_sources.update(
                _embedded_image_sources(message.thinking_content)
            )
            lines.extend(
                (
                    "### 思考过程",
                    "",
                    _rewrite_embedded_images(
                        message.thinking_content.strip(),
                        images,
                        image_reference,
                    ),
                    "",
                )
            )
        if selection.tool_calls:
            lines.extend(_tool_call_lines(message))
        if selection.tool_results and message.role == "tool":
            lines.extend(_tool_result_lines(message))
        attachment_images = tuple(
            image
            for image in images
            if not image.embedded or image.source not in rendered_embedded_sources
        )
        if attachment_images:
            lines.extend(("### 图片", ""))
            for image in attachment_images:
                target = image_reference(image) if image_reference else f"assets/{image.asset_name}"
                lines.extend((f"![{_image_alt(image.alt_text)}]({target})", ""))

    return _normalize_document_lines(lines)


def _message_metadata_lines(
    message: ProjectConversationMessage,
    selection: ConversationExportContentSelection,
) -> list[str]:
    items: list[tuple[str, str]] = []
    if selection.timestamps:
        items.append(("创建时间", message.created_at))
        if message.updated_at and message.updated_at != message.created_at:
            items.append(("更新时间", message.updated_at))
    if selection.model_info:
        if message.provider_id:
            items.append(("服务商", message.provider_id))
        if message.model_id:
            items.append(("模型", message.model_id))
        if message.target_provider_id:
            items.append(("目标服务商", message.target_provider_id))
        if message.target_model_id:
            items.append(("目标模型", message.target_model_id))
    if selection.token_usage:
        items.extend((f"Token {label}", str(value)) for label, value in usage_items(message))
    if not items:
        return []
    return [*(f"- {label}：{_inline_text(value)}" for label, value in items), ""]


def _tool_call_lines(message: ProjectConversationMessage) -> list[str]:
    lines: list[str] = []
    for index, tool_call in enumerate(message.tool_calls, start=1):
        lines.extend(
            (
                f"### 工具调用 {index}：{_inline_text(tool_call.name)}",
                "",
                _fenced_code(tool_call.arguments, "json"),
                "",
            )
        )
    return lines


def _tool_result_lines(message: ProjectConversationMessage) -> list[str]:
    result = parse_tool_result(message)
    status = "成功" if result.ok is True else "失败" if result.ok is False else message.status
    lines = [
        f"### 工具结果：{_inline_text(result.name)}",
        "",
        f"- 状态：{_inline_text(status)}",
        "",
    ]
    if result.arguments:
        lines.extend(("#### 调用参数", "", _fenced_code(result.arguments, "json"), ""))
    if result.result:
        lines.extend(("#### 返回内容", "", _fenced_code(result.result), ""))
    if result.error:
        lines.extend(("#### 错误", "", _fenced_code(result.error), ""))
    return lines


def _fenced_code(value: str, language: str = "") -> str:
    longest_run = max((len(run) for run in re.findall(r"`+", value)), default=0)
    fence = "`" * max(3, longest_run + 1)
    return f"{fence}{language}\n{value.rstrip()}\n{fence}"


def _inline_text(value: str) -> str:
    return value.replace("\r", " ").replace("\n", " ").strip()


def _inline_code(value: str) -> str:
    return value.replace("`", "\\`")


def _image_alt(value: str) -> str:
    return value.replace("\\", "\\\\").replace("]", "\\]").replace("\n", " ")


def _rewrite_embedded_images(
    value: str,
    images: tuple[ConversationExportImage, ...],
    image_reference: Callable[[ConversationExportImage], str] | None,
) -> str:
    replacements = {
        image.source: (
            image_reference(image) if image_reference else f"assets/{image.asset_name}"
        )
        for image in images
        if image.embedded
    }
    if not replacements:
        return value

    pieces: list[str] = []
    cursor = 0
    for token in tokenize_inline(value):
        parsed = parse_image_token(token.raw)
        if parsed is None or parsed[1] not in replacements:
            continue
        pieces.append(value[cursor:token.start])
        pieces.append(f"![{_image_alt(parsed[0])}]({replacements[parsed[1]]})")
        cursor = token.end
    if cursor == 0:
        return value
    pieces.append(value[cursor:])
    return "".join(pieces)


def _embedded_image_sources(value: str) -> set[str]:
    return {
        parsed[1]
        for token in tokenize_inline(value)
        if (parsed := parse_image_token(token.raw)) is not None
    }


def _normalize_document_lines(lines: list[str]) -> str:
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines) + "\n"
