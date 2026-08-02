from dataclasses import replace

from app.domain.llm.chat import ChatMessage


_CONVERSATION_MESSAGE_ID_KEY = "conversation_message_id"


def tag_conversation_message(
    message: ChatMessage,
    message_id: str | None,
) -> ChatMessage:
    if not message_id:
        return message
    return replace(
        message,
        internal_metadata={
            **message.internal_metadata,
            _CONVERSATION_MESSAGE_ID_KEY: message_id,
        },
    )


def conversation_message_id(message: ChatMessage) -> str | None:
    value = message.internal_metadata.get(_CONVERSATION_MESSAGE_ID_KEY)
    return value if isinstance(value, str) and value else None
