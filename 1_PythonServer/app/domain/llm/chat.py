from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from app.domain.llm.generation_params import LlmGenerationParams, LlmOutputOptions


class ChatMessageRole(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class ChatMessageContentPartType(StrEnum):
    TEXT = "text"
    IMAGE_URL = "image_url"
    IMAGE_REF = "image_ref"


@dataclass(frozen=True, slots=True)
class ChatImageUrl:
    url: str
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class ChatImageRef:
    path: str
    mime_type: str | None = None
    detail: str | None = None
    name: str | None = None
    size_bytes: int | None = None


@dataclass(frozen=True, slots=True)
class ChatMessageContentPart:
    type: ChatMessageContentPartType
    text: str | None = None
    image_url: ChatImageUrl | None = None
    image_ref: ChatImageRef | None = None


@dataclass(frozen=True, slots=True)
class ChatToolCall:
    call_id: str
    name: str
    arguments: str


@dataclass(frozen=True, slots=True)
class ChatToolResult:
    call_id: str
    name: str
    arguments: str
    ok: bool
    content: str
    error: str | None = None
    tool_project_id: str | None = None
    elapsed_ms: int | None = None
    dynamic: bool | None = None


@dataclass(frozen=True, slots=True)
class ChatClientToolRequest:
    request_id: str
    call_id: str
    name: str
    arguments: str
    project_id: str | None = None
    session_id: str | None = None
    timeout_seconds: int = 60
    model_context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ChatToolDefinition:
    name: str
    description: str
    parameters: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: ChatMessageRole
    content: str
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: tuple[ChatToolCall, ...] = ()
    content_parts: tuple[ChatMessageContentPart, ...] = ()
    thinking_content: str = ""
    preview_metadata: dict[str, Any] = field(default_factory=dict)
    provider_output_items: tuple[dict[str, Any], ...] = ()
    internal_metadata: dict[str, Any] = field(default_factory=dict)
    message_id: str | None = None
    created_at: str | None = None


@dataclass(frozen=True, slots=True)
class ChatCompletionRequest:
    provider_id: str
    model_id: str
    messages: tuple[ChatMessage, ...]
    project_id: str | None = None
    session_id: str | None = None
    cache_affinity_id: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    tools: tuple[ChatToolDefinition, ...] = ()
    generation: LlmGenerationParams = field(default_factory=LlmGenerationParams)
    output: LlmOutputOptions = field(default_factory=LlmOutputOptions)
    record_usage: bool = True
    usage_message_id: str | None = None
    usage_feature_key: str = "main_chat"
    return_thinking_content: bool = False
    inject_message_timestamps: bool = False
    max_tool_calls: int = 99999


@dataclass(frozen=True, slots=True)
class ChatUsage:
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    prompt_cache_hit_tokens: int | None = None
    prompt_cache_miss_tokens: int | None = None
    reasoning_tokens: int | None = None
    estimated_fields: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ChatCompletionResult:
    provider_id: str
    model_id: str
    message: ChatMessage
    thinking_content: str = ""
    finish_reason: str | None = None
    usage: ChatUsage | None = None
    selected_key_id: str | None = None
    selected_api_key_hint: str | None = None
    raw_response: dict[str, Any] | None = None


class ChatStreamEventKind(StrEnum):
    DELTA = "delta"
    THINKING_DELTA = "thinking_delta"
    USAGE = "usage"
    TOOL_CALL_DELTA = "tool_call_delta"
    TOOL_CALL = "tool_call"
    CLIENT_TOOL_REQUEST = "client_tool_request"
    TOOL_RESULT = "tool_result"
    PROVIDER_OUTPUT_ITEM = "provider_output_item"
    DONE = "done"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class ChatStreamEvent:
    kind: ChatStreamEventKind
    content: str | None = None
    finish_reason: str | None = None
    error: str | None = None
    usage: ChatUsage | None = None
    tool_call: ChatToolCall | None = None
    client_tool_request: ChatClientToolRequest | None = None
    tool_result: ChatToolResult | None = None
    provider_output_item: dict[str, Any] | None = None
