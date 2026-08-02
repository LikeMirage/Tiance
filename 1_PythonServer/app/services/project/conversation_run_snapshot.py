from __future__ import annotations

from dataclasses import dataclass

from app.domain.llm.chat import (
    ChatCompletionRequest,
    ChatMessage,
    ChatMessageRole,
)
from app.domain.project.project_conversation import ProjectConversationMessage
from app.services.project.conversation_request_provenance import tag_conversation_message


@dataclass(frozen=True, slots=True)
class ConversationRunSnapshot:
    model_request: ChatCompletionRequest
    assistant_response: ChatMessage
    context_tokens: int | None = None
    context_tokens_estimated: bool = False


def build_conversation_run_snapshot(
    model_request: ChatCompletionRequest | None,
    assistant_message: ProjectConversationMessage,
) -> ConversationRunSnapshot | None:
    if model_request is None:
        return None
    return ConversationRunSnapshot(
        model_request=model_request,
        assistant_response=tag_conversation_message(
            ChatMessage(
                role=ChatMessageRole.ASSISTANT,
                content=assistant_message.content,
                content_parts=assistant_message.content_parts,
                thinking_content=assistant_message.thinking_content,
                tool_calls=assistant_message.tool_calls,
            ),
            assistant_message.message_id,
        ),
        context_tokens=assistant_message.context_tokens,
        context_tokens_estimated=assistant_message.context_tokens_estimated,
    )
