from dataclasses import dataclass


PERSISTENCE_CHECKPOINT_KIND = "_conversation_persistence_checkpoint"


@dataclass(frozen=True, slots=True)
class ConversationPersistenceCheckpoint:
    message_id: str


def persistence_checkpoint_payload(
    checkpoint: ConversationPersistenceCheckpoint,
) -> dict[str, object | None]:
    return {
        "kind": PERSISTENCE_CHECKPOINT_KIND,
        "checkpoint_message_id": checkpoint.message_id,
    }
