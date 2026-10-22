from app.domain.llm.chat import ChatMessage, ChatMessageRole
from app.domain.llm.reasoning_replay import ReasoningReplayMode


def should_replay_reasoning(message: ChatMessage, mode: ReasoningReplayMode) -> bool:
    """Apply the provider's choice to a historical assistant message, not the next reply."""
    return message.role == ChatMessageRole.ASSISTANT and (
        mode == ReasoningReplayMode.ALWAYS
        or (mode == ReasoningReplayMode.TOOL_CALL_ROUNDS and bool(message.tool_calls))
    )
