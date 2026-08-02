from app.domain.project.project_conversation import ProjectConversationMessage


CONVERSATION_RUN_STARTED_KIND = "conversation_run_started"
CONVERSATION_RUN_SETTLED_KIND = "conversation_run_settled"


def conversation_run_started_payload(
    user_message: ProjectConversationMessage | None,
) -> dict[str, object | None] | None:
    if user_message is None:
        return None
    return {
        "kind": CONVERSATION_RUN_STARTED_KIND,
        "user_message_id": user_message.message_id,
    }


def conversation_run_settled_payload(
    user_message: ProjectConversationMessage | None,
    assistant_message: ProjectConversationMessage | None,
    *,
    status: str,
) -> dict[str, object | None] | None:
    if user_message is None:
        return None
    return {
        "kind": CONVERSATION_RUN_SETTLED_KIND,
        "user_message_id": user_message.message_id,
        "assistant_message_id": (
            assistant_message.message_id if assistant_message is not None else None
        ),
        "status": status,
    }
