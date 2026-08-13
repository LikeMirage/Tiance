from dataclasses import asdict, dataclass, field, replace
from hashlib import sha256
from json import dumps

from app.domain.llm.chat import ChatMessageContentPart, ChatToolCall


@dataclass(frozen=True, slots=True)
class ProjectConversationSessionSettings:
    global_memory_enabled: bool = True
    global_memory_extraction_enabled: bool = True
    memory_compression_enabled: bool = True
    memory_context_token_trigger_threshold: int = 250000
    memory_raw_context_token_reserve: int = 30000
    project_memory_enabled: bool = True
    project_memory_extraction_enabled: bool = True
    return_thinking_content: bool = False
    return_cancelled_messages: bool = True
    return_user_before_cancelled: bool = True
    streaming_enabled: bool = True
    auto_collapse_assistant_process: bool = True
    inject_message_timestamps: bool = True
    system_prompt: str = ""
    max_output_tokens: int = 32768
    temperature: float | None = None
    top_p: float | None = None
    tools_enabled: bool = True
    enabled_tool_names: tuple[str, ...] | None = None
    max_tool_calls: int = 99999


def functional_session_recursion_guard_settings(
    settings: ProjectConversationSessionSettings,
) -> ProjectConversationSessionSettings:
    return replace(
        settings,
        global_memory_extraction_enabled=False,
        memory_compression_enabled=False,
        project_memory_extraction_enabled=False,
    )


@dataclass(frozen=True, slots=True)
class ProjectConversationSession:
    session_id: str
    sequence_number: int
    title: str
    provider_id: str | None
    model_id: str | None
    created_at: str
    updated_at: str
    message_count: int
    reasoning_mode: str | None = None
    manual_title: bool = False
    settings: ProjectConversationSessionSettings = field(
        default_factory=ProjectConversationSessionSettings
    )
    pinned: bool = False
    role_project_id: str | None = None
    role_configuration_hash: str | None = None


def conversation_session_configuration_hash(
    session: ProjectConversationSession,
) -> str:
    settings = asdict(session.settings)
    enabled_tool_names = settings.get("enabled_tool_names")
    if isinstance(enabled_tool_names, tuple):
        settings["enabled_tool_names"] = sorted(enabled_tool_names)
    payload = {
        "provider_id": session.provider_id,
        "model_id": session.model_id,
        "reasoning_mode": session.reasoning_mode,
        "settings": settings,
    }
    content = dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return sha256(content.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ProjectConversationMessage:
    message_id: str
    session_id: str
    role: str
    content: str
    thinking_content: str
    usage: dict | None
    provider_id: str | None
    model_id: str | None
    status: str
    created_at: str
    updated_at: str
    created_at_local: str | None = None
    context_tokens: int | None = None
    context_tokens_estimated: bool = False
    target_provider_id: str | None = None
    target_model_id: str | None = None
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: tuple[ChatToolCall, ...] = ()
    content_parts: tuple[ChatMessageContentPart, ...] = ()
    origin_message_id: str | None = None
    variant_group_id: str | None = None
    variant_index: int = 1
    references: list[dict] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ProjectConversationMessagePage:
    items: tuple[ProjectConversationMessage, ...]
    total_count: int
    has_more: bool
    next_before_message_id: str | None


@dataclass(frozen=True, slots=True)
class ProjectConversationMessageTurn:
    user_message_id: str
    items: tuple[ProjectConversationMessage, ...]


@dataclass(frozen=True, slots=True)
class ProjectConversationNamingCallRecord:
    naming_call_id: str
    session_id: str
    provider_id: str
    model_id: str
    request: dict
    response: dict | None
    status: str
    error: str | None
    created_at: str
    completed_at: str | None = None


@dataclass(frozen=True, slots=True)
class ProjectConversationSessionState:
    session_id: str
    runtime_status: str
    draft: str
    references: list[dict]
    updated_at: str
