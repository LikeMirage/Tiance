from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.domain.llm.generation_params import LlmReasoningMode
from app.domain.project.project_conversation import (
    conversation_session_configuration_hash,
    ProjectConversationMessage,
    ProjectConversationSession,
    ProjectConversationSessionState,
)
from app.domain.project.conversation_branch_overview import (
    ProjectConversationBranchGroup,
    ProjectConversationBranchGroupDetail,
    ProjectConversationBranchTurnEdge,
    ProjectConversationBranchTurnNode,
    ProjectConversationBranchTurnTarget,
)
from app.schemas.llm.chat import ChatMessageContentPartResponse, ChatToolCallResponse
from app.schemas.conversation_references import ConversationReferences

ProjectConversationRuntimeStatus = Literal["idle", "running", "error"]


class ProjectConversationSessionSettingsPatch(BaseModel):
    global_memory_enabled: bool | None = None
    global_memory_extraction_enabled: bool | None = None
    memory_compression_enabled: bool | None = None
    memory_context_token_trigger_threshold: int | None = Field(default=None, ge=1)
    memory_raw_context_token_reserve: int | None = Field(default=None, ge=0)
    project_memory_enabled: bool | None = None
    project_memory_extraction_enabled: bool | None = None
    return_thinking_content: bool | None = None
    return_cancelled_messages: bool | None = None
    return_user_before_cancelled: bool | None = None
    streaming_enabled: bool | None = None
    auto_collapse_assistant_process: bool | None = None
    inject_message_timestamps: bool | None = None
    system_prompt: str | None = None
    max_output_tokens: int | None = Field(default=None, ge=1)
    temperature: float | None = Field(default=None, ge=0)
    top_p: float | None = Field(default=None, ge=0)
    tools_enabled: bool | None = None
    enabled_tool_names: list[str] | None = None
    max_tool_calls: int | None = Field(default=None, ge=1)


class ProjectConversationCreateRequest(BaseModel):
    title: str | None = None
    provider_id: str | None = None
    model_id: str | None = None
    reasoning_mode: LlmReasoningMode | None = None
    settings: ProjectConversationSessionSettingsPatch | None = None
    activate: bool = True
    parent_session_id: str | None = None
    created_by: Literal["user", "ai"] = "user"
    role_project_id: str | None = None


class ProjectConversationSessionUpdateRequest(BaseModel):
    title: str | None = None
    provider_id: str | None = None
    model_id: str | None = None
    reasoning_mode: LlmReasoningMode | None = None
    settings: ProjectConversationSessionSettingsPatch | None = None


class ProjectConversationAutomaticTitleRequest(BaseModel):
    title: str = Field(min_length=1)


class ProjectConversationAutomaticTitleResponse(BaseModel):
    applied: bool
    source_session_id: str
    title: str
    status: Literal["completed", "superseded"]


class ProjectConversationAutomaticNamingSettleRequest(BaseModel):
    outcome: Literal["done", "error", "cancelled"]


class ProjectConversationAutomaticNamingSettleResponse(BaseModel):
    task_id: str
    status: Literal["completed", "superseded", "failed"]


class ProjectConversationSessionPinRequest(BaseModel):
    pinned: bool


class ProjectConversationSessionSettingsResponse(BaseModel):
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
    enabled_tool_names: list[str] | None = None
    max_tool_calls: int = 99999

    @classmethod
    def from_domain(
        cls,
        session: ProjectConversationSession,
    ) -> "ProjectConversationSessionSettingsResponse":
        return cls(
            global_memory_enabled=session.settings.global_memory_enabled,
            global_memory_extraction_enabled=(
                session.settings.global_memory_extraction_enabled
            ),
            memory_compression_enabled=session.settings.memory_compression_enabled,
            memory_context_token_trigger_threshold=(
                session.settings.memory_context_token_trigger_threshold
            ),
            memory_raw_context_token_reserve=(
                session.settings.memory_raw_context_token_reserve
            ),
            project_memory_enabled=session.settings.project_memory_enabled,
            project_memory_extraction_enabled=(
                session.settings.project_memory_extraction_enabled
            ),
            return_thinking_content=session.settings.return_thinking_content,
            return_cancelled_messages=session.settings.return_cancelled_messages,
            return_user_before_cancelled=session.settings.return_user_before_cancelled,
            streaming_enabled=session.settings.streaming_enabled,
            auto_collapse_assistant_process=session.settings.auto_collapse_assistant_process,
            inject_message_timestamps=session.settings.inject_message_timestamps,
            system_prompt=session.settings.system_prompt,
            max_output_tokens=session.settings.max_output_tokens,
            temperature=session.settings.temperature,
            top_p=session.settings.top_p,
            tools_enabled=session.settings.tools_enabled,
            enabled_tool_names=list(session.settings.enabled_tool_names)
            if session.settings.enabled_tool_names is not None
            else None,
            max_tool_calls=session.settings.max_tool_calls,
        )


class ProjectConversationSessionResponse(BaseModel):
    session_id: str
    sequence_number: int
    title: str
    provider_id: str | None = None
    model_id: str | None = None
    reasoning_mode: LlmReasoningMode | None = None
    manual_title: bool = False
    settings: ProjectConversationSessionSettingsResponse = Field(
        default_factory=ProjectConversationSessionSettingsResponse
    )
    created_at: str
    updated_at: str
    message_count: int
    pinned: bool = False
    role_project_id: str | None = None
    role_status: Literal["selected", "custom"] = "custom"

    @classmethod
    def from_domain(
        cls,
        session: ProjectConversationSession,
    ) -> "ProjectConversationSessionResponse":
        return cls(
            session_id=session.session_id,
            sequence_number=session.sequence_number,
            title=session.title,
            provider_id=session.provider_id,
            model_id=session.model_id,
            reasoning_mode=LlmReasoningMode(session.reasoning_mode) if session.reasoning_mode else None,
            manual_title=session.manual_title,
            settings=ProjectConversationSessionSettingsResponse.from_domain(session),
            created_at=session.created_at,
            updated_at=session.updated_at,
            message_count=session.message_count,
            pinned=session.pinned,
            role_project_id=session.role_project_id,
            role_status=(
                "selected"
                if session.role_project_id
                and session.role_configuration_hash
                == conversation_session_configuration_hash(session)
                else "custom"
            ),
        )


class ProjectConversationSessionStatePatch(BaseModel):
    runtime_status: ProjectConversationRuntimeStatus | None = None
    draft: str | None = None
    references: ConversationReferences | None = None


class ProjectConversationStateSaveRequest(BaseModel):
    assistant_title: str | None = None
    active_session_id: str | None = None
    session_states: dict[str, ProjectConversationSessionStatePatch] = Field(default_factory=dict)


class ProjectConversationSessionStateResponse(BaseModel):
    runtime_status: ProjectConversationRuntimeStatus
    draft: str
    references: ConversationReferences = Field(default_factory=ConversationReferences)
    updated_at: str

    @classmethod
    def from_domain(
        cls,
        state: ProjectConversationSessionState,
    ) -> "ProjectConversationSessionStateResponse":
        return cls(
            runtime_status=state.runtime_status,  # type: ignore[arg-type]
            draft=state.draft,
            references=state.references,
            updated_at=state.updated_at,
        )


class ProjectConversationStateResponse(BaseModel):
    project_id: str
    assistant_title: str
    active_session_id: str | None = None
    session_states: dict[str, ProjectConversationSessionStateResponse] = Field(default_factory=dict)


class ProjectConversationListResponse(BaseModel):
    project_id: str
    count: int
    assistant_title: str
    active_session_id: str | None = None
    session_states: dict[str, ProjectConversationSessionStateResponse] = Field(default_factory=dict)
    items: list[ProjectConversationSessionResponse]
    branch_nodes: list["ProjectConversationBranchNodeResponse"] = Field(default_factory=list)
    message_variants: list["ProjectConversationMessageVariantResponse"] = Field(default_factory=list)


class ProjectConversationBranchNodeResponse(BaseModel):
    branch_id: str
    tree_id: str
    session_id: str
    parent_branch_id: str | None = None
    parent_session_id: str | None = None
    relation_kind: Literal["root", "child", "fork", "functional"]
    function_type: Literal[
        "automatic_naming",
        "global_memory_management",
        "memory_compaction",
        "project_memory_management",
    ] | None = None
    created_by: Literal["user", "ai", "system"]
    history_mode: Literal["empty", "fork", "copy"]
    source_message_id: str | None = None
    sibling_index: int
    created_at: str
    deleted_at: str | None = None

    @classmethod
    def from_domain(cls, node) -> "ProjectConversationBranchNodeResponse":
        return cls(**{field: getattr(node, field) for field in cls.model_fields})


class ProjectConversationMessageVariantResponse(BaseModel):
    variant_group_id: str
    variant_index: int
    branch_id: str
    session_id: str
    message_id: str | None = None
    origin_message_id: str | None = None
    created_at: str
    deleted_at: str | None = None

    @classmethod
    def from_domain(cls, variant) -> "ProjectConversationMessageVariantResponse":
        return cls(**{field: getattr(variant, field) for field in cls.model_fields})


class ProjectConversationBranchGroupResponse(BaseModel):
    group_id: str
    root_session_id: str
    title: str
    updated_at: str
    session_ids: list[str]
    is_branched: bool

    @classmethod
    def from_domain(
        cls,
        group: ProjectConversationBranchGroup,
    ) -> "ProjectConversationBranchGroupResponse":
        return cls(
            group_id=group.group_id,
            root_session_id=group.root_session_id,
            title=group.title,
            updated_at=group.updated_at,
            session_ids=list(group.session_ids),
            is_branched=group.is_branched,
        )


class ProjectConversationBranchGroupListResponse(BaseModel):
    project_id: str
    count: int
    items: list[ProjectConversationBranchGroupResponse]


class ProjectConversationBranchTurnTargetResponse(BaseModel):
    session_id: str
    message_id: str

    @classmethod
    def from_domain(
        cls,
        target: ProjectConversationBranchTurnTarget,
    ) -> "ProjectConversationBranchTurnTargetResponse":
        return cls(session_id=target.session_id, message_id=target.message_id)


class ProjectConversationBranchTurnNodeResponse(BaseModel):
    node_id: str
    variant_group_id: str
    variant_index: int
    user_preview: str
    assistant_preview: str
    reply_status: Literal["done", "running", "missing", "error"]
    created_at: str
    targets: list[ProjectConversationBranchTurnTargetResponse]

    @classmethod
    def from_domain(
        cls,
        node: ProjectConversationBranchTurnNode,
    ) -> "ProjectConversationBranchTurnNodeResponse":
        return cls(
            node_id=node.node_id,
            variant_group_id=node.variant_group_id,
            variant_index=node.variant_index,
            user_preview=node.user_preview,
            assistant_preview=node.assistant_preview,
            reply_status=node.reply_status,  # type: ignore[arg-type]
            created_at=node.created_at,
            targets=[
                ProjectConversationBranchTurnTargetResponse.from_domain(target)
                for target in node.targets
            ],
        )


class ProjectConversationBranchTurnEdgeResponse(BaseModel):
    source_node_id: str
    target_node_id: str

    @classmethod
    def from_domain(
        cls,
        edge: ProjectConversationBranchTurnEdge,
    ) -> "ProjectConversationBranchTurnEdgeResponse":
        return cls(
            source_node_id=edge.source_node_id,
            target_node_id=edge.target_node_id,
        )


class ProjectConversationBranchGroupDetailResponse(BaseModel):
    project_id: str
    group: ProjectConversationBranchGroupResponse
    node_count: int
    edge_count: int
    nodes: list[ProjectConversationBranchTurnNodeResponse]
    edges: list[ProjectConversationBranchTurnEdgeResponse]

    @classmethod
    def from_domain(
        cls,
        project_id: str,
        detail: ProjectConversationBranchGroupDetail,
    ) -> "ProjectConversationBranchGroupDetailResponse":
        return cls(
            project_id=project_id,
            group=ProjectConversationBranchGroupResponse.from_domain(detail.group),
            node_count=len(detail.nodes),
            edge_count=len(detail.edges),
            nodes=[
                ProjectConversationBranchTurnNodeResponse.from_domain(node)
                for node in detail.nodes
            ],
            edges=[
                ProjectConversationBranchTurnEdgeResponse.from_domain(edge)
                for edge in detail.edges
            ],
        )


class ProjectConversationForkRequest(BaseModel):
    source_message_id: str = Field(min_length=1)
    draft: str = Field(default="", max_length=2_000_000)
    references: ConversationReferences = Field(default_factory=ConversationReferences)


class ProjectConversationForkResponse(BaseModel):
    session: ProjectConversationSessionResponse
    state: ProjectConversationSessionStateResponse
    branch: ProjectConversationBranchNodeResponse
    source_message: "ProjectConversationMessageResponse"
    branch_nodes: list[ProjectConversationBranchNodeResponse] = Field(default_factory=list)
    message_variants: list[ProjectConversationMessageVariantResponse] = Field(default_factory=list)


class ProjectConversationMessageResponse(BaseModel):
    message_id: str
    session_id: str
    role: str
    content: str
    thinking_content: str
    usage: dict | None = None
    context_tokens: int | None = None
    context_tokens_estimated: bool = False
    provider_id: str | None = None
    model_id: str | None = None
    target_provider_id: str | None = None
    target_model_id: str | None = None
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[ChatToolCallResponse] = Field(default_factory=list)
    content_parts: list[ChatMessageContentPartResponse] = Field(default_factory=list)
    references: ConversationReferences = Field(default_factory=ConversationReferences)
    status: str
    created_at: str
    updated_at: str
    origin_message_id: str
    variant_group_id: str | None = None
    variant_index: int = 1

    @classmethod
    def from_domain(
        cls,
        message: ProjectConversationMessage,
    ) -> "ProjectConversationMessageResponse":
        return cls(
            message_id=message.message_id,
            session_id=message.session_id,
            role=message.role,
            content=message.content,
            thinking_content=message.thinking_content,
            usage=message.usage,
            context_tokens=message.context_tokens,
            context_tokens_estimated=message.context_tokens_estimated,
            provider_id=message.provider_id,
            model_id=message.model_id,
            target_provider_id=message.target_provider_id,
            target_model_id=message.target_model_id,
            name=message.name,
            tool_call_id=message.tool_call_id,
            tool_calls=[
                ChatToolCallResponse.from_domain(tool_call)
                for tool_call in message.tool_calls
            ],
            content_parts=[
                ChatMessageContentPartResponse.from_domain(part)
                for part in message.content_parts
            ],
            references=message.references,
            status=message.status,
            created_at=message.created_at,
            updated_at=message.updated_at,
            origin_message_id=message.origin_message_id or message.message_id,
            variant_group_id=message.variant_group_id,
            variant_index=max(1, message.variant_index),
        )


class ProjectConversationMessageListResponse(BaseModel):
    project_id: str
    session_id: str
    count: int
    total_count: int | None = None
    has_more: bool = False
    next_before_message_id: str | None = None
    items: list[ProjectConversationMessageResponse]


class ProjectConversationDataViewResponse(BaseModel):
    project_id: str
    session_id: str | None = None
    name: str
    content: str
    revision_ms: int
    total_count: int | None = None
    truncated: bool = False


class ProjectConversationMessageTurnResponse(BaseModel):
    project_id: str
    session_id: str
    user_message_id: str
    count: int
    items: list[ProjectConversationMessageResponse]
