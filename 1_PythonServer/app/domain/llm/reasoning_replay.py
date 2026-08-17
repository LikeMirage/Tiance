from enum import StrEnum


class ReasoningReplayMode(StrEnum):
    """Controls which stored assistant reasoning is replayed to message-based APIs."""

    NEVER = "never"
    TOOL_CALL_ROUNDS = "tool_call_rounds"
    ALWAYS = "always"
