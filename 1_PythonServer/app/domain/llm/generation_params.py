from dataclasses import dataclass
from enum import StrEnum


class LlmOutputFormat(StrEnum):
    TEXT = "text"
    JSON_OBJECT = "json_object"


class LlmReasoningMode(StrEnum):
    DEFAULT = "default"
    AUTO = "auto"
    ENABLED = "enabled"
    OFF = "off"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    MAX = "max"


@dataclass(frozen=True, slots=True)
class LlmReasoningOptions:
    mode: LlmReasoningMode = LlmReasoningMode.DEFAULT
    budget_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class LlmGenerationParams:
    temperature: float | None = None
    top_p: float | None = None
    presence_penalty: float | None = None
    frequency_penalty: float | None = None
    max_output_tokens: int | None = None
    reasoning: LlmReasoningOptions | None = None


@dataclass(frozen=True, slots=True)
class LlmOutputOptions:
    format: LlmOutputFormat = LlmOutputFormat.TEXT
