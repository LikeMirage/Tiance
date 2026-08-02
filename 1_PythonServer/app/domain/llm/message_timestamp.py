from app.domain.llm.chat import ChatMessage, ChatMessageRole


def model_visible_message_content(message: ChatMessage) -> str:
    if message.role != ChatMessageRole.USER:
        return message.content
    timestamp = (message.created_at or "").strip()
    if not timestamp:
        return message.content
    marker = f"<message_time>{timestamp}</message_time>"
    return f"{marker}\n{message.content}" if message.content else marker
