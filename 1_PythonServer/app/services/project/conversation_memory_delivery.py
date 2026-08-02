from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.domain.llm.chat import ChatCompletionRequest, ChatMessageRole
from app.domain.project.project_conversation import ProjectConversationSession
from app.repositories.project.conversation_memory_repository import (
    ProjectConversationMemoryRepository,
)
from app.repositories.llm.provider_adaptation_rules_repository import (
    ProviderAdaptationRulesRepository,
)
from app.services.project.conversation_memory_delivery_context import (
    draft_user_message_id,
    inject_memory_delivery_context,
)
from app.services.project.conversation_memory_delivery_state import (
    fold_missing_leading_memory_deliveries,
    prepare_memory_delivery_state,
)
from app.services.project.conversation_request_provenance import (
    conversation_message_id,
)
from app.services.project.project_conversations import ProjectConversationService


class ProjectConversationMemoryDeliveryService:
    """Prepare and inject global/project memory delivery state for a conversation."""

    def __init__(
        self,
        conversation_service: ProjectConversationService,
        memory_repository: ProjectConversationMemoryRepository,
        adaptation_rules_repository: ProviderAdaptationRulesRepository,
    ) -> None:
        self._conversation_service = conversation_service
        self._memory_repository = memory_repository
        self._adaptation_rules_repository = adaptation_rules_repository

    def prepare(
        self,
        project_id: str,
        session_id: str,
        user_message_id: str,
        *,
        provider_id: str,
        model_id: str,
    ) -> None:
        session = self._conversation_service.get_session(project_id, session_id)
        if session is None:
            return
        created_at = _utc_now()
        self._memory_repository.update_session_memory_delivery_state(
            project_id,
            session_id,
            lambda existing: prepare_memory_delivery_state(
                existing,
                user_message_id=user_message_id,
                created_at=created_at,
                global_events=self._memory_repository.list_global_memory_events(),
                project_events=self._memory_repository.list_project_memory_events(
                    project_id
                ),
                global_enabled=session.settings.global_memory_enabled,
                project_enabled=session.settings.project_memory_enabled,
                cache_provider_id=provider_id,
                cache_model_id=model_id,
                cache_retention_seconds=self._cache_retention_seconds(
                    provider_id,
                    model_id,
                ),
            ),
        )

    def inject(
        self,
        request: ChatCompletionRequest,
        *,
        include_pending_changes: bool = False,
    ) -> ChatCompletionRequest:
        if not request.project_id or not request.session_id:
            return request
        session = self._conversation_service.get_session(
            request.project_id,
            request.session_id,
        )
        if session is None:
            return request
        state = self._memory_repository.read_session_memory_delivery_state(
            request.project_id,
            request.session_id,
        )
        draft_target: str | None = None
        if include_pending_changes:
            draft_target = draft_user_message_id()
            state = self._prepared_state(
                state,
                project_id=request.project_id,
                session=session,
                user_message_id=draft_target,
                provider_id=request.provider_id,
                model_id=request.model_id,
            )
        elif state is None:
            state = self._prepared_state(
                None,
                project_id=request.project_id,
                session=session,
                user_message_id=(
                    _last_request_user_message_id(request)
                    or draft_user_message_id()
                ),
                provider_id=request.provider_id,
                model_id=request.model_id,
            )
        else:
            visible_message_ids = {
                message_id
                for message in request.messages
                if (message_id := conversation_message_id(message)) is not None
            }
            compacted_at = _utc_now()
            compacted_state = fold_missing_leading_memory_deliveries(
                state,
                visible_message_ids=visible_message_ids,
                updated_at=compacted_at,
            )
            if compacted_state != state:
                state = self._memory_repository.update_session_memory_delivery_state(
                    request.project_id,
                    request.session_id,
                    lambda current: fold_missing_leading_memory_deliveries(
                        _required_memory_delivery_state(current),
                        visible_message_ids=visible_message_ids,
                        updated_at=compacted_at,
                    ),
                )
        return inject_memory_delivery_context(
            request,
            state,
            global_enabled=session.settings.global_memory_enabled,
            project_enabled=session.settings.project_memory_enabled,
            draft_delivery_target=draft_target,
        )

    def _prepared_state(
        self,
        state: dict[str, Any] | None,
        *,
        project_id: str,
        session: ProjectConversationSession,
        user_message_id: str,
        provider_id: str,
        model_id: str,
    ) -> dict[str, Any]:
        return prepare_memory_delivery_state(
            state,
            user_message_id=user_message_id,
            created_at=_utc_now(),
            global_events=self._memory_repository.list_global_memory_events(),
            project_events=self._memory_repository.list_project_memory_events(project_id),
            global_enabled=session.settings.global_memory_enabled,
            project_enabled=session.settings.project_memory_enabled,
            cache_provider_id=provider_id,
            cache_model_id=model_id,
            cache_retention_seconds=self._cache_retention_seconds(
                provider_id,
                model_id,
            ),
        )

    def _cache_retention_seconds(self, provider_id: str, model_id: str) -> int:
        return self._adaptation_rules_repository.resolve_prompt_cache_retention_seconds(
            provider_id=provider_id,
            model_id=model_id,
        )


def _last_request_user_message_id(
    request: ChatCompletionRequest,
) -> str | None:
    for message in reversed(request.messages):
        if message.role == ChatMessageRole.USER:
            return conversation_message_id(message)
    return None


def _required_memory_delivery_state(
    value: dict[str, Any] | None,
) -> dict[str, Any]:
    if value is None:
        raise ValueError("Conversation memory delivery state is missing.")
    return value


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
