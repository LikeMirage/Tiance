from __future__ import annotations

from app.domain.project.conversation_export import (
    ConversationExportContentSelection,
    PreparedConversationExport,
    RenderedConversationExport,
)

from ..content import (
    message_body,
    message_is_visible,
    message_label,
    parse_tool_result,
    range_label,
    usage_items,
)


class TextConversationExportRenderer:
    def render(
        self,
        prepared: PreparedConversationExport,
        selection: ConversationExportContentSelection,
    ) -> RenderedConversationExport:
        document = prepared.document
        lines: list[str] = []
        if selection.session_info:
            lines.extend(
                (
                    document.session.title,
                    "=" * max(4, len(document.session.title)),
                    "",
                    f"会话 ID：{document.session.session_id}",
                    f"导出范围：{range_label(document.export_range.value)}",
                    f"导出消息数：{len(document.messages)}",
                    f"导出时间：{document.exported_at.isoformat()}",
                    "",
                )
            )

        visible_index = 0
        for message in document.messages:
            if not message_is_visible(message, selection, has_images=False):
                continue
            visible_index += 1
            lines.extend((f"[{message_label(message)} {visible_index}]",))
            if selection.timestamps:
                lines.append(f"创建时间：{message.created_at}")
                if message.updated_at and message.updated_at != message.created_at:
                    lines.append(f"更新时间：{message.updated_at}")
            if selection.model_info:
                if message.provider_id:
                    lines.append(f"服务商：{message.provider_id}")
                if message.model_id:
                    lines.append(f"模型：{message.model_id}")
                if message.target_provider_id:
                    lines.append(f"目标服务商：{message.target_provider_id}")
                if message.target_model_id:
                    lines.append(f"目标模型：{message.target_model_id}")
            if selection.token_usage:
                lines.extend(f"Token {label}：{value}" for label, value in usage_items(message))
            body = message_body(message, selection).strip()
            if body:
                lines.extend(("", body))
            if selection.thinking and message.thinking_content.strip():
                lines.extend(("", "[思考过程]", message.thinking_content.strip()))
            if selection.tool_calls:
                for call_index, tool_call in enumerate(message.tool_calls, start=1):
                    lines.extend(
                        (
                            "",
                            f"[工具调用 {call_index}] {tool_call.name}",
                            tool_call.arguments,
                        )
                    )
            if selection.tool_results and message.role == "tool":
                result = parse_tool_result(message)
                lines.extend(("", f"[工具结果] {result.name}", result.result))
                if result.error:
                    lines.extend(("[错误]", result.error))
            lines.extend(("", "-" * 48, ""))

        return RenderedConversationExport(
            content=("\n".join(lines).rstrip() + "\n").encode("utf-8-sig"),
            extension=".txt",
        )
