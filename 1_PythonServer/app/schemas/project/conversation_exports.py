from __future__ import annotations

from typing import Self

from pydantic import BaseModel, Field, model_validator

from app.domain.project.conversation_export import (
    ConversationExportContentSelection,
    ConversationExportFormat,
    ConversationExportRange,
    ConversationExportResult,
)


class ConversationExportContentRequest(BaseModel):
    session_info: bool = True
    assistant_content: bool = True
    user_messages: bool = True
    thinking: bool = False
    tool_calls: bool = False
    tool_results: bool = False
    error_messages: bool = True
    system_messages: bool = False
    timestamps: bool = False
    images: bool = True
    model_info: bool = False
    token_usage: bool = False
    message_metadata: bool = False

    def to_domain(self) -> ConversationExportContentSelection:
        return ConversationExportContentSelection(**self.model_dump())


class ConversationExportRequest(BaseModel):
    format: ConversationExportFormat
    range: ConversationExportRange
    message_id: str | None = Field(default=None, min_length=1, max_length=160)
    content: ConversationExportContentRequest
    target_directory: str = Field(min_length=1, max_length=4096)
    base_name: str = Field(min_length=1, max_length=120)
    open_after_export: bool = False

    @model_validator(mode="after")
    def validate_range_anchor(self) -> Self:
        if self.range == ConversationExportRange.CONVERSATION:
            if self.message_id is not None:
                raise ValueError("完整会话导出不能指定消息锚点。")
        elif not self.message_id:
            raise ValueError("按消息导出时必须指定消息锚点。")
        return self


class ConversationExportResponse(BaseModel):
    format: ConversationExportFormat
    container_path: str
    output_path: str
    message_count: int
    warnings: list[str]

    @classmethod
    def from_domain(
        cls,
        export_format: ConversationExportFormat,
        result: ConversationExportResult,
    ) -> "ConversationExportResponse":
        return cls(
            format=export_format,
            container_path=str(result.container_path),
            output_path=str(result.output_path),
            message_count=result.message_count,
            warnings=list(result.warnings),
        )
