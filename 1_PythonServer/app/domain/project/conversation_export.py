from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from app.domain.project.project_conversation import (
    ProjectConversationMessage,
    ProjectConversationSession,
)


class ConversationExportFormat(StrEnum):
    DOCX = "docx"
    MARKDOWN = "markdown"
    TXT = "txt"
    HTML = "html"
    JSON = "json"


class ConversationExportRange(StrEnum):
    CONVERSATION = "conversation"
    MESSAGE = "message"
    THROUGH_MESSAGE = "through-message"
    FROM_MESSAGE = "from-message"


@dataclass(frozen=True, slots=True)
class ConversationExportContentSelection:
    session_info: bool
    assistant_content: bool
    user_messages: bool
    thinking: bool
    tool_calls: bool
    tool_results: bool
    error_messages: bool
    system_messages: bool
    timestamps: bool
    images: bool
    model_info: bool
    token_usage: bool
    message_metadata: bool

    def has_supported_content(self, export_format: ConversationExportFormat) -> bool:
        values = [
            self.session_info,
            self.assistant_content,
            self.user_messages,
            self.thinking,
            self.tool_calls,
            self.tool_results,
            self.error_messages,
            self.system_messages,
            self.timestamps,
            self.model_info,
            self.token_usage,
        ]
        if export_format not in {ConversationExportFormat.TXT, ConversationExportFormat.JSON}:
            values.append(self.images)
        if export_format == ConversationExportFormat.JSON:
            values.append(self.message_metadata)
        return any(values)


@dataclass(frozen=True, slots=True)
class ConversationExportDocument:
    project_root: Path
    session: ProjectConversationSession
    messages: tuple[ProjectConversationMessage, ...]
    export_range: ConversationExportRange
    exported_at: datetime


@dataclass(frozen=True, slots=True)
class ConversationExportImage:
    asset_name: str
    alt_text: str
    content: bytes
    embedded: bool
    message_id: str
    mime_type: str
    source: str


@dataclass(frozen=True, slots=True)
class PreparedConversationExport:
    document: ConversationExportDocument
    images: tuple[ConversationExportImage, ...]

    def images_for_message(self, message_id: str) -> tuple[ConversationExportImage, ...]:
        return tuple(image for image in self.images if image.message_id == message_id)


@dataclass(frozen=True, slots=True)
class ConversationExportFile:
    relative_path: str
    content: bytes


@dataclass(frozen=True, slots=True)
class RenderedConversationExport:
    content: bytes
    extension: str
    bundle: bool = False
    files: tuple[ConversationExportFile, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class StoredConversationExport:
    container_path: Path
    output_path: Path


@dataclass(frozen=True, slots=True)
class ConversationExportResult:
    container_path: Path
    output_path: Path
    message_count: int
    warnings: tuple[str, ...]
