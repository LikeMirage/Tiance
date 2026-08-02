from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from app.core.errors import BadRequestError, NotFoundError
from app.domain.project.conversation_export import (
    ConversationExportDocument,
    ConversationExportRange,
)
from app.domain.project.project_conversation import ProjectConversationMessage
from app.services.project.project_conversations import ProjectConversationService
from app.services.project.projects import ProjectService


class ConversationExportAssembler:
    """Loads the complete persisted conversation and applies message range selection."""

    def __init__(
        self,
        conversation_service: ProjectConversationService,
        project_service: ProjectService,
    ) -> None:
        self._conversation_service = conversation_service
        self._project_service = project_service

    def assemble(
        self,
        project_id: str,
        session_id: str,
        *,
        export_range: ConversationExportRange,
        message_id: str | None,
    ) -> ConversationExportDocument:
        project = self._project_service.get_project(project_id)
        if project is None:
            raise NotFoundError(f"项目 '{project_id}' 不存在。")
        session = self._conversation_service.get_session(project_id, session_id)
        if session is None:
            raise NotFoundError(f"Conversation session '{session_id}' was not found.")

        # This deliberately uses the unpaged repository method. Export correctness must
        # never depend on how many messages the current UI happens to have loaded.
        all_messages = self._conversation_service.list_messages(project_id, session_id)
        messages = select_conversation_export_messages(
            all_messages,
            export_range=export_range,
            message_id=message_id,
        )
        return ConversationExportDocument(
            project_root=Path(project.root_path).resolve(),
            session=session,
            messages=messages,
            export_range=export_range,
            exported_at=datetime.now(UTC),
        )


def select_conversation_export_messages(
    messages: tuple[ProjectConversationMessage, ...],
    *,
    export_range: ConversationExportRange,
    message_id: str | None,
) -> tuple[ProjectConversationMessage, ...]:
    if export_range == ConversationExportRange.CONVERSATION:
        return messages
    if not message_id:
        raise BadRequestError("按消息导出时必须指定消息。")

    anchor_index = next(
        (index for index, message in enumerate(messages) if message.message_id == message_id),
        None,
    )
    if anchor_index is None:
        raise BadRequestError("导出锚点消息不属于当前会话。")

    if export_range == ConversationExportRange.MESSAGE:
        return messages[anchor_index : anchor_index + 1]
    if export_range == ConversationExportRange.THROUGH_MESSAGE:
        return messages[: anchor_index + 1]
    if export_range == ConversationExportRange.FROM_MESSAGE:
        return messages[anchor_index:]
    raise BadRequestError("不支持的会话导出范围。")
