from functools import lru_cache
from typing import Protocol

from app.core.errors import NotFoundError
from app.domain.project.project_conversation import (
    ProjectConversationMessage,
    ProjectConversationMessagePage,
    ProjectConversationMessageTurn,
    ProjectConversationNamingCallRecord,
    ProjectConversationSession,
    ProjectConversationSessionState,
)
from app.domain.project.conversation_branch import (
    ProjectConversationBranchNode,
    ProjectConversationForkResult,
    ProjectConversationMessageVariant,
)
from app.domain.project.conversation_branch_overview import (
    ProjectConversationBranchGroup,
    ProjectConversationBranchGroupDetail,
    build_conversation_branch_group_detail,
    build_conversation_branch_groups,
)
from app.domain.llm.chat import (
    ChatMessageContentPart,
    ChatProtocolContinuation,
    ChatToolCall,
)
from app.repositories.project.conversation_repository import (
    ProjectConversationRepository,
    get_project_conversation_repository,
)


class ConversationActivityRecorder(Protocol):
    def record_conversation_created(self, session: ProjectConversationSession) -> bool: ...

    def record_user_message_sent(self, message: ProjectConversationMessage) -> bool: ...

    def record_ai_run_elapsed(
        self,
        *,
        user_message_id: str,
        started_at: str,
        finished_at: str | None,
        elapsed_ms: int | None,
    ) -> bool: ...


class ProjectConversationService:
    def __init__(
        self,
        repository: ProjectConversationRepository,
        activity_recorder: ConversationActivityRecorder | None = None,
    ) -> None:
        self._repository = repository
        self._activity_recorder = activity_recorder

    def list_sessions(self, project_id: str) -> tuple[ProjectConversationSession, ...]:
        return self._repository.list_sessions(project_id)

    def get_session(self, project_id: str, session_id: str) -> ProjectConversationSession | None:
        return self._repository.get_session(project_id, session_id)

    def record_user_message_sent(self, message: ProjectConversationMessage) -> None:
        if self._activity_recorder is not None:
            self._activity_recorder.record_user_message_sent(message)

    def record_ai_run_elapsed(
        self,
        user_message: ProjectConversationMessage,
        *,
        assistant_message: ProjectConversationMessage | None,
        elapsed_ms: int | None,
    ) -> None:
        if self._activity_recorder is None:
            return
        self._activity_recorder.record_ai_run_elapsed(
            user_message_id=user_message.message_id,
            started_at=user_message.created_at,
            finished_at=assistant_message.created_at if assistant_message is not None else None,
            elapsed_ms=elapsed_ms,
        )

    def list_branch_graph(
        self,
        project_id: str,
    ) -> tuple[
        tuple[ProjectConversationBranchNode, ...],
        tuple[ProjectConversationMessageVariant, ...],
    ]:
        return self._repository.list_branch_graph(project_id)

    def get_overview_data(
        self,
        project_id: str,
    ) -> tuple[
        tuple[ProjectConversationSession, ...],
        tuple[ProjectConversationBranchNode, ...],
        str | None,
        dict[str, ProjectConversationSessionState],
    ]:
        return self._repository.get_overview_data(project_id)

    def get_cache_affinity_id(self, project_id: str, session_id: str) -> str:
        return self._repository.get_cache_affinity_id(project_id, session_id)

    def list_branch_groups(
        self,
        project_id: str,
    ) -> tuple[ProjectConversationBranchGroup, ...]:
        sessions = self.list_sessions(project_id)
        branch_nodes, _message_variants = self.list_branch_graph(project_id)
        return build_conversation_branch_groups(sessions, branch_nodes)

    def get_branch_group_detail(
        self,
        project_id: str,
        group_id: str,
    ) -> ProjectConversationBranchGroupDetail:
        groups = self.list_branch_groups(project_id)
        group = next((item for item in groups if item.group_id == group_id), None)
        if group is None:
            raise NotFoundError(f"Conversation branch group '{group_id}' was not found.")
        sessions_by_id = {
            session.session_id: session
            for session in self.list_sessions(project_id)
        }
        session_messages = tuple(
            (
                sessions_by_id[session_id],
                self.list_messages(project_id, session_id),
            )
            for session_id in group.session_ids
            if session_id in sessions_by_id
        )
        return build_conversation_branch_group_detail(group, session_messages)

    def get_state(
        self,
        project_id: str,
    ) -> tuple[str, str | None, dict[str, ProjectConversationSessionState]]:
        return self._repository.get_state(project_id)

    def save_state(
        self,
        project_id: str,
        *,
        assistant_title: str | None,
        should_update_assistant_title: bool,
        active_session_id: str | None,
        should_update_active_session: bool,
        session_states: dict[str, dict],
    ) -> tuple[str, str | None, dict[str, ProjectConversationSessionState]]:
        return self._repository.save_state(
            project_id,
            assistant_title=assistant_title,
            should_update_assistant_title=should_update_assistant_title,
            active_session_id=active_session_id,
            should_update_active_session=should_update_active_session,
            session_states=session_states,
        )

    def create_session(
        self,
        project_id: str,
        *,
        title: str | None = None,
        provider_id: str | None = None,
        model_id: str | None = None,
        reasoning_mode: str | None = None,
        manual_title: bool = False,
        set_active: bool = True,
        settings: dict | None = None,
        role_project_id: str | None = None,
        parent_session_id: str | None = None,
        created_by: str = "user",
    ) -> ProjectConversationSession:
        session = self._repository.create_session(
            project_id,
            title=title,
            provider_id=provider_id,
            model_id=model_id,
            reasoning_mode=reasoning_mode,
            manual_title=manual_title,
            set_active=set_active,
            settings=settings,
            role_project_id=role_project_id,
            parent_session_id=parent_session_id,
            created_by=created_by,
        )
        self._record_conversation_created(session)
        return session

    def update_session(
        self,
        project_id: str,
        session_id: str,
        *,
        title: str | None = None,
        should_update_title: bool = False,
        provider_id: str | None = None,
        should_update_provider: bool = False,
        model_id: str | None = None,
        should_update_model: bool = False,
        reasoning_mode: str | None = None,
        should_update_reasoning: bool = False,
        manual_title: bool | None = None,
        should_update_manual_title: bool = False,
        settings: dict | None = None,
        should_update_settings: bool = False,
        role_project_id: str | None = None,
        should_update_role_project_id: bool = False,
    ) -> ProjectConversationSession:
        return self._repository.update_session(
            project_id,
            session_id,
            title=title,
            should_update_title=should_update_title,
            provider_id=provider_id,
            should_update_provider=should_update_provider,
            model_id=model_id,
            should_update_model=should_update_model,
            reasoning_mode=reasoning_mode,
            should_update_reasoning=should_update_reasoning,
            manual_title=manual_title,
            should_update_manual_title=should_update_manual_title,
            settings=settings,
            should_update_settings=should_update_settings,
            role_project_id=role_project_id,
            should_update_role_project_id=should_update_role_project_id,
        )

    def set_session_pinned(
        self,
        project_id: str,
        session_id: str,
        *,
        pinned: bool,
    ) -> ProjectConversationSession:
        return self._repository.set_session_pinned(
            project_id,
            session_id,
            pinned=pinned,
        )

    def delete_session(self, project_id: str, session_id: str) -> None:
        replacement = self._repository.delete_session(project_id, session_id)
        if replacement is not None:
            self._record_conversation_created(replacement)

    def fork_session(
        self,
        project_id: str,
        source_session_id: str,
        *,
        source_message_id: str,
        draft: str,
        references: list[dict],
    ) -> ProjectConversationForkResult:
        result = self._repository.fork_session(
            project_id,
            source_session_id,
            source_message_id=source_message_id,
            draft=draft,
            references=references,
        )
        self._record_conversation_created(result.session)
        return result

    def _record_conversation_created(self, session: ProjectConversationSession) -> None:
        if self._activity_recorder is not None:
            self._activity_recorder.record_conversation_created(session)

    def save_session_runtime_status(
        self,
        project_id: str,
        session_id: str,
        runtime_status: str,
    ) -> None:
        self._repository.save_session_runtime_status(
            project_id,
            session_id,
            runtime_status,
        )

    def reconcile_missing_run_runtime_status(
        self,
        project_id: str,
        session_id: str,
    ) -> None:
        _assistant_title, _active_session_id, session_states = self.get_state(project_id)
        state = session_states.get(session_id)
        if state is None:
            return
        if state.runtime_status == "running":
            self.save_session_runtime_status(project_id, session_id, "idle")

    def list_messages(
        self,
        project_id: str,
        session_id: str,
    ) -> tuple[ProjectConversationMessage, ...]:
        return self._repository.list_messages(project_id, session_id)

    def list_messages_page(
        self,
        project_id: str,
        session_id: str,
        *,
        limit: int | None = None,
        before_message_id: str | None = None,
    ) -> ProjectConversationMessagePage:
        return self._repository.list_messages_page(
            project_id,
            session_id,
            limit=limit,
            before_message_id=before_message_id,
        )

    def get_message_turn(
        self,
        project_id: str,
        session_id: str,
        user_message_id: str,
    ) -> ProjectConversationMessageTurn:
        return self._repository.get_message_turn(
            project_id,
            session_id,
            user_message_id,
        )

    def append_message(
        self,
        project_id: str,
        session_id: str,
        *,
        role: str,
        content: str,
        thinking_content: str = "",
        usage: dict | None = None,
        context_tokens: int | None = None,
        context_tokens_estimated: bool = False,
        provider_id: str | None = None,
        model_id: str | None = None,
        name: str | None = None,
        tool_call_id: str | None = None,
        tool_calls: tuple[ChatToolCall, ...] = (),
        protocol_continuation: ChatProtocolContinuation | None = None,
        content_parts: tuple[ChatMessageContentPart, ...] = (),
        references: list[dict] | None = None,
        status: str = "done",
        sync_session_model: bool = True,
        message_id: str | None = None,
    ) -> ProjectConversationMessage:
        return self._repository.append_message(
            project_id,
            session_id,
            role=role,
            content=content,
            thinking_content=thinking_content,
            usage=usage,
            context_tokens=context_tokens,
            context_tokens_estimated=context_tokens_estimated,
            provider_id=provider_id,
            model_id=model_id,
            name=name,
            tool_call_id=tool_call_id,
            tool_calls=tool_calls,
            protocol_continuation=protocol_continuation,
            content_parts=content_parts,
            references=references,
            status=status,
            sync_session_model=sync_session_model,
            message_id=message_id,
        )

    def insert_system_message_after(
        self,
        project_id: str,
        session_id: str,
        *,
        after_message_id: str,
        content: str,
        name: str | None = None,
        status: str = "done",
    ) -> ProjectConversationMessage:
        return self._repository.insert_system_message_after(
            project_id,
            session_id,
            after_message_id=after_message_id,
            content=content,
            name=name,
            status=status,
        )

    def cancel_assistant_message(
        self,
        project_id: str,
        session_id: str,
        message_id: str,
        *,
        usage: dict | None = None,
        context_tokens: int | None = None,
        context_tokens_estimated: bool = False,
    ) -> ProjectConversationMessage:
        return self._repository.cancel_assistant_message(
            project_id,
            session_id,
            message_id,
            usage=usage,
            context_tokens=context_tokens,
            context_tokens_estimated=context_tokens_estimated,
        )

    def append_naming_call_record(
        self,
        project_id: str,
        session_id: str,
        record: ProjectConversationNamingCallRecord,
    ) -> None:
        self._repository.append_naming_call_record(project_id, session_id, record)

    def write_injection_preview(
        self,
        project_id: str,
        session_id: str,
        payload: dict,
    ) -> None:
        self._repository.write_injection_preview(project_id, session_id, payload)


@lru_cache
def get_project_conversation_service() -> ProjectConversationService:
    from app.services.workspace_activity import get_workspace_activity_service

    return ProjectConversationService(
        get_project_conversation_repository(),
        get_workspace_activity_service(),
    )
