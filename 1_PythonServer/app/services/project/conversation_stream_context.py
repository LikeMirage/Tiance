from __future__ import annotations

from dataclasses import replace
from typing import Any

from app.domain.llm.chat import ChatCompletionRequest, ChatMessage, ChatMessageRole
from app.domain.project.project_conversation import ProjectConversationMessage

from app.services.project.conversation_injection_preview import (
    InjectionPreviewSource,
    build_conversation_injection_preview,
)
from app.services.project.conversation_request_messages import build_conversation_request_messages
from app.services.project.conversation_references import (
    normalize_conversation_references,
    references_from_chat_message,
)
from app.services.project.conversation_memory import ProjectConversationMemoryService
from app.services.project.project_conversations import ProjectConversationService
from app.services.tools.chat_tool_injection import ChatToolInjectionService


class ConversationStreamContextBuilder:
    def __init__(
        self,
        *,
        conversation_service: ProjectConversationService,
        memory_service: ProjectConversationMemoryService,
        tool_injection_service: ChatToolInjectionService | None,
    ) -> None:
        self._conversation_service = conversation_service
        self._memory_service = memory_service
        self._tool_injection_service = tool_injection_service

    def inject_session_tools(self, request: ChatCompletionRequest) -> ChatCompletionRequest:
        if self._tool_injection_service is None:
            return request
        if not request.project_id or not request.session_id:
            return request
        session = self._conversation_service.get_session(request.project_id, request.session_id)
        if session is None:
            return request
        if not session.settings.tools_enabled:
            return replace(request, tools=())
        return self._tool_injection_service.inject_request_tools(
            request,
            enabled_tool_names=session.settings.enabled_tool_names,
        )

    def rebuild_session_request_messages(
        self,
        request: ChatCompletionRequest,
        *,
        drop_matching_last_user: bool = False,
    ) -> ChatCompletionRequest:
        if not request.project_id or not request.session_id:
            return request
        session = self._conversation_service.get_session(request.project_id, request.session_id)
        if session is None:
            return request
        current_user_message = _last_user_message(request.messages)
        session_messages = self._conversation_service.list_messages(
            request.project_id,
            request.session_id,
        )
        history_messages = (
            _history_without_current_user(session_messages, current_user_message)
            if drop_matching_last_user
            else session_messages
        )
        persisted_current_user = _matching_current_user_message(
            session_messages,
            current_user_message,
        )
        return replace(
            request,
            inject_message_timestamps=session.settings.inject_message_timestamps,
            cache_affinity_id=self._conversation_service.get_cache_affinity_id(
                request.project_id,
                request.session_id,
            ),
            messages=build_conversation_request_messages(
                history_messages,
                current_user_message.content if current_user_message is not None else None,
                session.settings,
                next_user_content_parts=(
                    current_user_message.content_parts
                    if current_user_message is not None
                    else ()
                ),
                next_user_references=references_from_chat_message(current_user_message),
                next_user_message_id=(
                    persisted_current_user.message_id
                    if persisted_current_user is not None
                    else None
                ),
                next_user_created_at=(
                    persisted_current_user.created_at_local
                    or persisted_current_user.created_at
                    if persisted_current_user is not None
                    else None
                ),
            ),
        )

    def replace_session_compressed_history(
        self,
        request: ChatCompletionRequest,
    ) -> ChatCompletionRequest:
        return self._memory_service.build_request_with_compressed_context(request)

    def inject_session_long_term_memory(
        self,
        request: ChatCompletionRequest,
        *,
        include_pending_changes: bool = False,
    ) -> ChatCompletionRequest:
        return self._memory_service.inject_long_term_memory_context(
            request,
            include_pending_changes=include_pending_changes,
        )

    def write_injection_preview(
        self,
        request: ChatCompletionRequest,
        *,
        preview_source: InjectionPreviewSource = "real_request",
    ) -> dict[str, Any] | None:
        if not request.project_id or not request.session_id:
            return None
        payload = build_conversation_injection_preview(
            request,
            preview_source=preview_source,
        )
        self._conversation_service.write_injection_preview(
            request.project_id,
            request.session_id,
            payload,
        )
        return payload


def _last_user_message(messages: tuple[ChatMessage, ...]) -> ChatMessage | None:
    for message in reversed(messages):
        if message.role == ChatMessageRole.USER:
            return message
    return None


def _history_without_current_user(
    messages: tuple[ProjectConversationMessage, ...],
    current_user_message: ChatMessage | None,
) -> tuple[ProjectConversationMessage, ...]:
    if current_user_message is None or not messages:
        return messages
    last_message = messages[-1]
    current_references = references_from_chat_message(current_user_message)
    if (
        last_message.role == "user"
        and last_message.content == current_user_message.content
        and last_message.content_parts == current_user_message.content_parts
        and normalize_conversation_references(last_message.references) == current_references
    ):
        return messages[:-1]
    return messages


def _matching_current_user_message(
    messages: tuple[ProjectConversationMessage, ...],
    current_user_message: ChatMessage | None,
) -> ProjectConversationMessage | None:
    if current_user_message is None or not messages:
        return None
    last_message = messages[-1]
    current_references = references_from_chat_message(current_user_message)
    if (
        last_message.role == "user"
        and last_message.content == current_user_message.content
        and last_message.content_parts == current_user_message.content_parts
        and normalize_conversation_references(last_message.references) == current_references
    ):
        return last_message
    return None
