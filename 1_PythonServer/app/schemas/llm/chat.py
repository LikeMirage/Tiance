from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.llm.chat import (
    ChatClientCapability,
    ChatCompletionRequest,
    ChatCompletionResult,
    ChatImageRef,
    ChatImageUrl,
    ChatMessage,
    ChatMessageContentPart,
    ChatMessageContentPartType,
    ChatMessageRole,
    ChatToolCall,
    ChatToolDefinition,
    ChatUsage,
)
from app.domain.llm.generation_params import (
    LlmGenerationParams,
    LlmOutputFormat,
    LlmOutputOptions,
    LlmReasoningMode,
    LlmReasoningOptions,
)
from app.schemas.conversation_references import ConversationReferences


class ChatClientCapabilityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    version: int = Field(ge=1)

    def to_domain(self) -> ChatClientCapability:
        return ChatClientCapability(name=self.name.strip(), version=self.version)


class ChatToolCallRequest(BaseModel):
    call_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    arguments: str = ""

    def to_domain(self) -> ChatToolCall:
        return ChatToolCall(
            call_id=self.call_id,
            name=self.name,
            arguments=self.arguments,
        )


class ChatToolDefinitionRequest(BaseModel):
    name: str = Field(min_length=1)
    description: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)

    def to_domain(self) -> ChatToolDefinition:
        return ChatToolDefinition(
            name=self.name,
            description=self.description,
            parameters=self.parameters,
        )


class ChatImageUrlRequest(BaseModel):
    url: str = Field(min_length=1)
    detail: Literal["auto", "low", "high"] | None = None

    def to_domain(self) -> ChatImageUrl:
        return ChatImageUrl(
            url=self.url,
            detail=self.detail,
        )


class ChatImageRefRequest(BaseModel):
    path: str = Field(min_length=1)
    mime_type: str | None = None
    detail: Literal["auto", "low", "high"] | None = None
    name: str | None = None
    size_bytes: int | None = Field(default=None, ge=0)
    attachment_id: str | None = None
    source_path: str | None = None
    source_kind: str | None = None

    def to_domain(self) -> ChatImageRef:
        return ChatImageRef(
            path=self.path,
            mime_type=self.mime_type,
            detail=self.detail,
            name=self.name,
            size_bytes=self.size_bytes,
            attachment_id=self.attachment_id,
            source_path=self.source_path,
            source_kind=self.source_kind,
        )


class ChatMessageContentPartRequest(BaseModel):
    type: ChatMessageContentPartType
    text: str | None = None
    image_url: ChatImageUrlRequest | None = None
    image_ref: ChatImageRefRequest | None = None

    @model_validator(mode="after")
    def validate_part_payload(self) -> "ChatMessageContentPartRequest":
        if self.type == ChatMessageContentPartType.TEXT and self.text is None:
            raise ValueError("text content part requires text")
        if self.type == ChatMessageContentPartType.IMAGE_URL and self.image_url is None:
            raise ValueError("image_url content part requires image_url")
        if self.type == ChatMessageContentPartType.IMAGE_REF and self.image_ref is None:
            raise ValueError("image_ref content part requires image_ref")
        return self

    def to_domain(self) -> ChatMessageContentPart:
        return ChatMessageContentPart(
            type=self.type,
            text=self.text,
            image_url=self.image_url.to_domain() if self.image_url else None,
            image_ref=self.image_ref.to_domain() if self.image_ref else None,
        )


class ChatMessageRequest(BaseModel):
    role: ChatMessageRole
    content: str = ""
    message_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    content_parts: list[ChatMessageContentPartRequest] = Field(default_factory=list)
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[ChatToolCallRequest] = Field(default_factory=list)
    thinking_content: str = ""
    references: ConversationReferences = Field(default_factory=ConversationReferences)

    def to_domain(self) -> ChatMessage:
        internal_metadata = {}
        if self.role == ChatMessageRole.USER:
            internal_metadata["conversation_references"] = self.references.to_payload()
        return ChatMessage(
            role=self.role,
            content=self.content,
            message_id=self.message_id,
            name=self.name,
            tool_call_id=self.tool_call_id,
            tool_calls=tuple(tool_call.to_domain() for tool_call in self.tool_calls),
            content_parts=tuple(part.to_domain() for part in self.content_parts),
            thinking_content=self.thinking_content,
            internal_metadata=internal_metadata,
        )


class ChatReasoningOptionsRequest(BaseModel):
    mode: LlmReasoningMode = LlmReasoningMode.DEFAULT
    budget_tokens: int | None = Field(default=None, ge=1)

    def to_domain(self) -> LlmReasoningOptions:
        return LlmReasoningOptions(
            mode=self.mode,
            budget_tokens=self.budget_tokens,
        )


class ChatGenerationParamsRequest(BaseModel):
    temperature: float | None = Field(default=None, ge=0)
    top_p: float | None = Field(default=None, ge=0)
    presence_penalty: float | None = None
    frequency_penalty: float | None = None
    max_output_tokens: int | None = Field(default=None, ge=1)
    reasoning: ChatReasoningOptionsRequest | None = None

    def to_domain(self) -> LlmGenerationParams:
        return LlmGenerationParams(
            temperature=self.temperature,
            top_p=self.top_p,
            presence_penalty=self.presence_penalty,
            frequency_penalty=self.frequency_penalty,
            max_output_tokens=self.max_output_tokens,
            reasoning=self.reasoning.to_domain() if self.reasoning else None,
        )


class ChatOutputOptionsRequest(BaseModel):
    format: LlmOutputFormat = LlmOutputFormat.TEXT

    def to_domain(self) -> LlmOutputOptions:
        return LlmOutputOptions(format=self.format)


class ChatCompletionRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_id: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    project_id: str | None = None
    session_id: str | None = None
    messages: list[ChatMessageRequest] = Field(default_factory=list)
    max_tool_calls: int = Field(default=99999, ge=1)
    tools: list[ChatToolDefinitionRequest] = Field(default_factory=list)
    generation: ChatGenerationParamsRequest | None = None
    output: ChatOutputOptionsRequest | None = None
    client_capabilities: list[ChatClientCapabilityRequest] = Field(default_factory=list)

    def to_domain(self) -> ChatCompletionRequest:
        return ChatCompletionRequest(
            provider_id=self.provider_id.strip(),
            model_id=self.model_id.strip(),
            messages=tuple(message.to_domain() for message in self.messages),
            project_id=self.project_id.strip() if self.project_id else None,
            session_id=self.session_id.strip() if self.session_id else None,
            tools=tuple(tool.to_domain() for tool in self.tools),
            generation=self.generation.to_domain() if self.generation else LlmGenerationParams(),
            output=self.output.to_domain() if self.output else LlmOutputOptions(),
            max_tool_calls=self.max_tool_calls,
            client_capabilities=tuple(
                capability.to_domain() for capability in self.client_capabilities
            ),
        )


class ChatStreamStopRequestBody(BaseModel):
    project_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)


class ChatStreamStopResponse(BaseModel):
    stopped: bool


class ChatToolCallResponse(BaseModel):
    call_id: str
    name: str
    arguments: str

    @classmethod
    def from_domain(cls, tool_call: ChatToolCall) -> "ChatToolCallResponse":
        return cls(
            call_id=tool_call.call_id,
            name=tool_call.name,
            arguments=tool_call.arguments,
        )


class ChatMessageResponse(BaseModel):
    role: ChatMessageRole
    content: str
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[ChatToolCallResponse] = Field(default_factory=list)
    content_parts: list["ChatMessageContentPartResponse"] = Field(default_factory=list)
    thinking_content: str = ""

    @classmethod
    def from_domain(cls, message: ChatMessage) -> "ChatMessageResponse":
        return cls(
            role=message.role,
            content=message.content,
            name=message.name,
            tool_call_id=message.tool_call_id,
            tool_calls=[ChatToolCallResponse.from_domain(tool_call) for tool_call in message.tool_calls],
            content_parts=[
                ChatMessageContentPartResponse.from_domain(part)
                for part in message.content_parts
            ],
            thinking_content=message.thinking_content,
        )


class ChatUsageResponse(BaseModel):
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    prompt_cache_hit_tokens: int | None = None
    prompt_cache_miss_tokens: int | None = None
    reasoning_tokens: int | None = None
    estimated_fields: list[str] = Field(default_factory=list)

    @classmethod
    def from_domain(cls, usage: ChatUsage) -> "ChatUsageResponse":
        return cls(
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            total_tokens=usage.total_tokens,
            prompt_cache_hit_tokens=usage.prompt_cache_hit_tokens,
            prompt_cache_miss_tokens=usage.prompt_cache_miss_tokens,
            reasoning_tokens=usage.reasoning_tokens,
            estimated_fields=list(usage.estimated_fields),
        )


class ChatImageRefResponse(BaseModel):
    path: str
    mime_type: str | None = None
    detail: str | None = None
    name: str | None = None
    size_bytes: int | None = None
    attachment_id: str | None = None
    source_path: str | None = None
    source_kind: str | None = None


class ChatMessageContentPartResponse(BaseModel):
    type: ChatMessageContentPartType
    text: str | None = None
    image_url: ChatImageUrlRequest | None = None
    image_ref: ChatImageRefResponse | None = None

    @classmethod
    def from_domain(cls, part: ChatMessageContentPart) -> "ChatMessageContentPartResponse":
        return cls(
            type=part.type,
            text=part.text,
            image_url=ChatImageUrlRequest(
                url=part.image_url.url,
                detail=part.image_url.detail,
            ) if part.image_url else None,
            image_ref=ChatImageRefResponse(
                path=part.image_ref.path,
                mime_type=part.image_ref.mime_type,
                detail=part.image_ref.detail,
                name=part.image_ref.name,
                size_bytes=part.image_ref.size_bytes,
                attachment_id=part.image_ref.attachment_id,
                source_path=part.image_ref.source_path,
                source_kind=part.image_ref.source_kind,
            ) if part.image_ref else None,
        )


class ChatCompletionResponse(BaseModel):
    provider_id: str
    model_id: str
    message: ChatMessageResponse
    thinking_content: str = ""
    finish_reason: str | None = None
    usage: ChatUsageResponse | None = None
    selected_key_id: str | None = None
    selected_api_key_hint: str | None = None

    @classmethod
    def from_domain(cls, result: ChatCompletionResult) -> "ChatCompletionResponse":
        return cls(
            provider_id=result.provider_id,
            model_id=result.model_id,
            message=ChatMessageResponse.from_domain(result.message),
            thinking_content=result.thinking_content,
            finish_reason=result.finish_reason,
            usage=ChatUsageResponse.from_domain(result.usage) if result.usage else None,
            selected_key_id=result.selected_key_id,
            selected_api_key_hint=result.selected_api_key_hint,
        )
