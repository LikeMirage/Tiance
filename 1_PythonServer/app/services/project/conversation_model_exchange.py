from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from app.domain.llm.chat import ChatCompletionRequest, ChatUsage
from app.domain.project.project_conversation import ProjectConversationMessage
from app.services.project.conversation_injection_preview import (
    build_conversation_injection_preview,
)


def build_model_exchange_record(
    request: ChatCompletionRequest,
    assistant_message: ProjectConversationMessage,
    *,
    round_index: int,
    usage: ChatUsage | None,
) -> dict[str, Any]:
    """Build a key-free record of one logical model request and response round."""

    request_preview = build_conversation_injection_preview(
        request,
        preview_source="real_request",
    )
    return {
        "schema_version": 1,
        "recorded_at": datetime.now(UTC).isoformat(),
        "round_index": round_index,
        "request": request_preview["request"],
        "request_snapshot": request_preview["request_snapshot"],
        "response": {
            "message_id": assistant_message.message_id,
            "role": assistant_message.role,
            "status": assistant_message.status,
            "content": assistant_message.content,
            "thinking_content": assistant_message.thinking_content,
            "tool_calls": [asdict(tool_call) for tool_call in assistant_message.tool_calls],
            "content_parts": [asdict(part) for part in assistant_message.content_parts],
            "protocol_continuation": (
                asdict(assistant_message.protocol_continuation)
                if assistant_message.protocol_continuation is not None
                else None
            ),
            "usage": asdict(usage) if usage is not None else assistant_message.usage,
        },
    }
