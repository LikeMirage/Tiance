from __future__ import annotations

from datetime import UTC, datetime
from functools import lru_cache
import logging
import sqlite3
from typing import TYPE_CHECKING

from app.domain.project.project_conversation import (
    ProjectConversationMessage,
    ProjectConversationSession,
)
from app.repositories.workspace_activity_repository import (
    WorkspaceActivityRepository,
    get_workspace_activity_repository,
)

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from app.services.project.project_conversations import ProjectConversationService
    from app.services.project.projects import ProjectService


class WorkspaceActivityService:
    def __init__(self, repository: WorkspaceActivityRepository) -> None:
        self._repository = repository

    def record_conversation_created(self, session: ProjectConversationSession) -> bool:
        try:
            self._repository.record_conversation_created(
                session_id=session.session_id,
                created_at=session.created_at,
            )
        except sqlite3.Error:
            logger.exception(
                "Failed to record conversation creation for session %s.",
                session.session_id,
            )
            return False
        return True

    def get_conversation_count(self) -> int:
        return self._repository.count_conversations_created()

    def record_user_message_sent(self, message: ProjectConversationMessage) -> bool:
        try:
            self._repository.record_user_message_sent(
                message_id=message.message_id,
                sent_at=message.created_at,
            )
        except sqlite3.Error:
            logger.exception(
                "Failed to record sent user message %s.",
                message.message_id,
            )
            return False
        return True

    def get_sent_message_count(self) -> int:
        return self._repository.count_user_messages_sent()

    def record_ai_run_elapsed(
        self,
        *,
        user_message_id: str,
        started_at: str,
        finished_at: str | None,
        elapsed_ms: int | None,
    ) -> bool:
        resolved_finished_at = finished_at or datetime.now(UTC).isoformat()
        resolved_elapsed_ms = elapsed_ms
        if resolved_elapsed_ms is None:
            resolved_elapsed_ms = _elapsed_ms_between(started_at, resolved_finished_at)
        if resolved_elapsed_ms is None:
            logger.warning(
                "Skipped AI runtime record for message %s because its timestamps are invalid.",
                user_message_id,
            )
            return False
        try:
            self._repository.record_ai_run_elapsed(
                user_message_id=user_message_id,
                elapsed_ms=resolved_elapsed_ms,
                finished_at=resolved_finished_at,
            )
        except sqlite3.Error:
            logger.exception(
                "Failed to record AI runtime for user message %s.",
                user_message_id,
            )
            return False
        return True

    def get_ai_runtime_ms(self) -> int:
        return self._repository.sum_ai_run_elapsed_ms()

    def clear_conversation_count(self) -> int:
        return self._repository.set_conversation_baseline(0)

    def set_conversation_count_baseline(self, count: int) -> int:
        return self._repository.set_conversation_baseline(count)


class WorkspaceActivityManagementService:
    def __init__(
        self,
        activity_service: WorkspaceActivityService,
        project_service: ProjectService,
        conversation_service: ProjectConversationService,
    ) -> None:
        self._activity_service = activity_service
        self._project_service = project_service
        self._conversation_service = conversation_service

    def clear_conversation_count(self) -> int:
        return self._activity_service.clear_conversation_count()

    def synchronize_conversation_count(self) -> int:
        current_count = sum(
            len(self._conversation_service.list_sessions(project.project_id))
            for project in self._project_service.list_projects()
        )
        return self._activity_service.set_conversation_count_baseline(current_count)


@lru_cache
def get_workspace_activity_service() -> WorkspaceActivityService:
    return WorkspaceActivityService(get_workspace_activity_repository())


@lru_cache
def get_workspace_activity_management_service() -> WorkspaceActivityManagementService:
    from app.services.project import get_project_conversation_service, get_project_service

    return WorkspaceActivityManagementService(
        get_workspace_activity_service(),
        get_project_service(),
        get_project_conversation_service(),
    )


def _elapsed_ms_between(started_at: str, finished_at: str) -> int | None:
    try:
        start = datetime.fromisoformat(started_at)
        finish = datetime.fromisoformat(finished_at)
    except ValueError:
        return None
    if start.tzinfo is None or finish.tzinfo is None:
        return None
    return max(0, round((finish - start).total_seconds() * 1000))
