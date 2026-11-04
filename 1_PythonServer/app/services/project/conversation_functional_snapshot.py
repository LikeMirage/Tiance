from __future__ import annotations

from app.domain.llm.chat import ChatMessage
from app.services.project.conversation_run_snapshot import ConversationRunSnapshot


def legal_conversation_snapshot_messages(
    run_snapshot: ConversationRunSnapshot,
) -> tuple[ChatMessage, ...]:
    messages = run_snapshot.model_request.messages
    if run_snapshot.assistant_response.tool_calls:
        return messages
    return (*messages, run_snapshot.assistant_response)
