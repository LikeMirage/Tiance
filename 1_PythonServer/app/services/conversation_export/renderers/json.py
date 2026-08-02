from __future__ import annotations

from json import dumps

from app.domain.project.conversation_export import (
    ConversationExportContentSelection,
    PreparedConversationExport,
    RenderedConversationExport,
)

from ..content import message_body, message_is_visible, parse_tool_result


class JsonConversationExportRenderer:
    def render(
        self,
        prepared: PreparedConversationExport,
        selection: ConversationExportContentSelection,
    ) -> RenderedConversationExport:
        document = prepared.document
        payload: dict[str, object] = {
            "schema_version": 1,
            "messages": [],
        }
        if selection.session_info:
            payload["conversation"] = {
                "session_id": document.session.session_id,
                "title": document.session.title,
            }
            if selection.model_info:
                payload["conversation"]["provider_id"] = document.session.provider_id
                payload["conversation"]["model_id"] = document.session.model_id
            if selection.timestamps:
                payload["conversation"]["created_at"] = document.session.created_at
                payload["conversation"]["updated_at"] = document.session.updated_at
            payload["export"] = {
                "range": document.export_range.value,
                "exported_at": document.exported_at.isoformat(),
                "message_count": len(document.messages),
            }

        message_items: list[dict[str, object]] = []
        for message in document.messages:
            if not message_is_visible(message, selection, has_images=False):
                continue
            item: dict[str, object] = {"role": message.role}
            body = message_body(message, selection)
            if body:
                item["content"] = body
            if selection.thinking and message.thinking_content:
                item["thinking"] = message.thinking_content
            if selection.tool_calls and message.tool_calls:
                item["tool_calls"] = [
                    {
                        "call_id": call.call_id,
                        "name": call.name,
                        "arguments": call.arguments,
                    }
                    for call in message.tool_calls
                ]
            if selection.tool_results and message.role == "tool":
                result = parse_tool_result(message)
                item["tool_result"] = {
                    "name": result.name,
                    "arguments": result.arguments,
                    "ok": result.ok,
                    "result": result.result,
                    "error": result.error or None,
                }
            if selection.timestamps:
                item["timestamps"] = {
                    "created_at": message.created_at,
                    "updated_at": message.updated_at,
                }
            if selection.model_info:
                item["model"] = {
                    "provider_id": message.provider_id,
                    "model_id": message.model_id,
                    "target_provider_id": message.target_provider_id,
                    "target_model_id": message.target_model_id,
                }
            if selection.token_usage and (message.usage or message.context_tokens is not None):
                item["usage"] = message.usage
                item["context_tokens"] = message.context_tokens
            if selection.message_metadata:
                item["metadata"] = {
                    "message_id": message.message_id,
                    "session_id": message.session_id,
                    "status": message.status,
                    "name": message.name,
                    "tool_call_id": message.tool_call_id,
                    "origin_message_id": message.origin_message_id,
                    "variant_group_id": message.variant_group_id,
                    "variant_index": message.variant_index,
                }
            message_items.append(item)
        payload["messages"] = message_items

        return RenderedConversationExport(
            content=dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"),
            extension=".json",
        )
