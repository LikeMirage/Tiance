from __future__ import annotations

from dataclasses import asdict, replace
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from uuid import uuid4

from app.core.errors import BadRequestError, ConflictError, NotFoundError
from app.domain.llm.chat import (
    ChatMessageContentPart,
    ChatProtocolContinuation,
    ChatToolCall,
)
from app.domain.project.project_conversation import (
    conversation_session_configuration_hash,
    ProjectConversationMessage,
    ProjectConversationMessageRole,
    ProjectConversationMessageStatus,
    ProjectConversationMessagePage,
    ProjectConversationMessageTurn,
    ProjectConversationRunOutcome,
    ProjectConversationNamingCallRecord,
    ProjectConversationSession,
    ProjectConversationSessionState,
)
from app.domain.project.conversation_branch import (
    ProjectConversationBranchNode,
    ProjectConversationForkResult,
    ProjectConversationMessageVariant,
)
from app.repositories.project.conversation_branch_repository import (
    ProjectConversationBranchRepository,
)
from app.repositories.project.conversation_branch_store import ConversationBranchStore
from app.repositories.project.conversation_relation_repository import (
    ProjectConversationRelationRepository,
)
from app.repositories.project.conversation_serialization import (
    _index_pinned_session_ids,
    _merge_session_settings,
    _new_session_id,
    _normalize_session_title,
    _optional_reasoning_mode,
    _runtime_status_for_appended_message,
    _session_settings_from_payload,
    _utc_now,
)
from app.repositories.project.conversation_storage import conversation_write_lock
from app.repositories.project.conversation_stores import (
    ConversationMessageStore,
    ConversationSessionStore,
    ConversationStateStore,
)
from app.repositories.project.project_repository import ProjectRepository, get_project_repository
from app.repositories.project.conversation_database import (
    append_journal_event,
    begin_conversation_run,
    latest_user_message_id,
    list_conversation_run_outcomes,
    read_conversation_run,
    settle_conversation_run,
    write_document,
)


class ProjectConversationRepository:
    def __init__(
        self,
        project_repository: ProjectRepository,
        *,
        session_store: ConversationSessionStore | None = None,
        message_store: ConversationMessageStore | None = None,
        state_store: ConversationStateStore | None = None,
        branch_store: ConversationBranchStore | None = None,
    ) -> None:
        self._state_store = state_store or ConversationStateStore()
        self._session_store = session_store or ConversationSessionStore(
            project_repository,
            state_store=self._state_store,
        )
        self._message_store = message_store or ConversationMessageStore()
        self._branch_store = branch_store or ConversationBranchStore()
        self._branch_repository = ProjectConversationBranchRepository(
            session_store=self._session_store,
            message_store=self._message_store,
            branch_store=self._branch_store,
        )
        self._relation_repository = ProjectConversationRelationRepository(
            session_store=self._session_store,
            message_store=self._message_store,
            branch_store=self._branch_store,
        )

    def list_branch_graph(
        self,
        project_id: str,
    ) -> tuple[
        tuple[ProjectConversationBranchNode, ...],
        tuple[ProjectConversationMessageVariant, ...],
    ]:
        conversations_dir = self._session_store.conversations_dir(project_id)
        graph = self._branch_store.read_graph(conversations_dir)
        return self._branch_store.list_nodes(graph), self._branch_store.list_variants(graph)

    def get_cache_affinity_id(self, project_id: str, session_id: str) -> str:
        conversations_dir = self._session_store.conversations_dir(project_id)
        graph = self._branch_store.read_graph(conversations_dir)
        return self._branch_store.cache_affinity_session_id(graph, session_id)

    def list_sessions(self, project_id: str) -> tuple[ProjectConversationSession, ...]:
        conversations_dir = self._session_store.conversations_dir(project_id)
        index = self._session_store.read_index(conversations_dir)
        return self._list_sessions(conversations_dir, index)

    def _list_sessions(
        self,
        conversations_dir: Path,
        index: dict,
        *,
        stored_sessions: dict[str, ProjectConversationSession] | None = None,
    ) -> tuple[ProjectConversationSession, ...]:
        pinned_session_ids = _index_pinned_session_ids(index)
        if stored_sessions is None:
            stored_sessions = self._session_store.read_sessions_from_conversations_dir(
                conversations_dir,
            )
        sessions = [
            replace(session, pinned=session_id in pinned_session_ids)
            for session_id, session in stored_sessions.items()
        ]
        if not sessions:
            return ()
        return tuple(
            sorted(
                sessions,
                key=lambda session: (
                    session.pinned,
                    session.created_at,
                    session.sequence_number,
                ),
                reverse=True,
            )
        )

    def get_state(
        self,
        project_id: str,
    ) -> tuple[str | None, dict[str, ProjectConversationSessionState]]:
        conversations_dir = self._session_store.conversations_dir(project_id)
        index = self._session_store.read_index(conversations_dir)
        sessions = self._list_sessions(conversations_dir, index)
        return self._state_store.conversation_state(conversations_dir, sessions, index)

    def get_overview_data(
        self,
        project_id: str,
    ) -> tuple[
        tuple[ProjectConversationSession, ...],
        tuple[ProjectConversationBranchNode, ...],
        str | None,
        dict[str, ProjectConversationSessionState],
    ]:
        (
            _revision,
            sessions,
            branch_nodes,
            _message_variants,
            active_session_id,
            session_states,
        ) = self.get_list_data(project_id)
        return (
            sessions,
            branch_nodes,
            active_session_id,
            session_states,
        )

    def get_list_data(
        self,
        project_id: str,
    ) -> tuple[
        int,
        tuple[ProjectConversationSession, ...],
        tuple[ProjectConversationBranchNode, ...],
        tuple[ProjectConversationMessageVariant, ...],
        str | None,
        dict[str, ProjectConversationSessionState],
    ]:
        """Return the complete conversation-list projection from one snapshot."""
        conversations_dir = self._session_store.conversations_dir(project_id)
        revision, index, stored_sessions, stored_states, raw_graph = self._session_store.read_list_snapshot(
            conversations_dir,
        )
        sessions = self._list_sessions(
            conversations_dir,
            index,
            stored_sessions=stored_sessions,
        )
        graph = self._branch_store.normalize_graph_payload(raw_graph)
        active_session_id, session_states = (
            self._state_store.conversation_state(
                conversations_dir,
                sessions,
                index,
                stored_states=stored_states,
            )
        )
        return (
            revision,
            sessions,
            self._branch_store.list_nodes(graph),
            self._branch_store.list_variants(graph),
            active_session_id,
            session_states,
        )

    def save_state(
        self,
        project_id: str,
        *,
        active_session_id: str | None,
        should_update_active_session: bool,
        session_runtime_statuses: dict[str, str],
        session_drafts: dict[str, str],
        session_references: dict[str, list[dict]],
    ) -> tuple[str | None, dict[str, ProjectConversationSessionState]]:
        conversations_dir = self._session_store.conversations_dir(project_id, for_write=True)
        with conversation_write_lock(conversations_dir):
            index = self._session_store.read_index(conversations_dir)
            sessions = self._list_sessions(conversations_dir, index)
            existing_active_session_id, _existing_states = (
                self._state_store.conversation_state(
                    conversations_dir,
                    sessions,
                    index,
                )
            )
            session_ids = {session.session_id for session in sessions}

            if should_update_active_session:
                if active_session_id is not None and active_session_id not in session_ids:
                    raise NotFoundError(f"Conversation session '{active_session_id}' was not found.")
                index["active_session_id"] = active_session_id
            else:
                index["active_session_id"] = existing_active_session_id

            changed_session_ids = (
                set(session_runtime_statuses)
                | set(session_drafts)
                | set(session_references)
            )
            for session_id in changed_session_ids:
                if session_id not in session_ids:
                    raise NotFoundError(f"Conversation session '{session_id}' was not found.")
            now = _utc_now()
            for session_id, runtime_status in session_runtime_statuses.items():
                self._state_store.write_runtime_status(
                    conversations_dir, session_id, runtime_status, now
                )
            for session_id, draft in session_drafts.items():
                self._state_store.write_draft(
                    conversations_dir, session_id, draft, now
                )
            for session_id, references in session_references.items():
                self._state_store.write_references(
                    conversations_dir, session_id, references, now
                )
            self._session_store.write_index(conversations_dir, index)
            return self._state_store.conversation_state(
                conversations_dir, sessions, index
            )

    def get_session(
        self,
        project_id: str,
        session_id: str,
    ) -> ProjectConversationSession | None:
        session = self._session_store.read_session(project_id, session_id)
        if session is None:
            return None
        conversations_dir = self._session_store.conversations_dir(project_id)
        index = self._session_store.read_index(conversations_dir)
        return replace(
            session,
            pinned=session_id in _index_pinned_session_ids(index),
        )

    def set_session_pinned(
        self,
        project_id: str,
        session_id: str,
        *,
        pinned: bool,
    ) -> ProjectConversationSession:
        conversations_dir = self._session_store.conversations_dir(project_id, for_write=True)
        with conversation_write_lock(conversations_dir):
            self._session_store.require_session_dir(
                project_id,
                session_id,
                for_write=True,
            )
            session = self._session_store.read_session(project_id, session_id)
            if session is None:
                raise NotFoundError(f"Conversation session '{session_id}' was not found.")

            index = self._session_store.read_index(conversations_dir)
            pinned_session_ids = _index_pinned_session_ids(index)
            if pinned:
                pinned_session_ids.add(session_id)
            else:
                pinned_session_ids.discard(session_id)

            live_session_ids = set(
                self._session_store.read_sessions_from_conversations_dir(
                    conversations_dir
                )
            )
            index["pinned_session_ids"] = sorted(
                pinned_session_ids & live_session_ids
            )
            self._session_store.write_index(conversations_dir, index)
            return replace(session, pinned=pinned)

    def create_session(
        self,
        project_id: str,
        *,
        title: str | None,
        provider_id: str | None,
        model_id: str | None,
        reasoning_mode: str | None,
        manual_title: bool = False,
        set_active: bool = True,
        settings: dict | None = None,
        role_project_id: str | None = None,
        parent_session_id: str | None = None,
        created_by: str = "user",
    ) -> ProjectConversationSession:
        if created_by == "ai":
            if not parent_session_id:
                raise ConflictError("AI 创建会话必须指定父会话。")
            return self._relation_repository.create_ai_child_session(
                project_id,
                parent_session_id,
                title=title,
                provider_id=provider_id,
                model_id=model_id,
                reasoning_mode=reasoning_mode,
                manual_title=manual_title,
                set_active=set_active,
                settings=settings,
                role_project_id=role_project_id,
            )
        if parent_session_id:
            raise ConflictError("普通新建会话不能指定父会话。")
        conversations_dir = self._session_store.conversations_dir(project_id, for_write=True)
        with conversation_write_lock(conversations_dir):
            return self._create_session_unlocked(
                project_id,
                conversations_dir=conversations_dir,
                title=title,
                provider_id=provider_id,
                model_id=model_id,
                reasoning_mode=reasoning_mode,
                manual_title=manual_title,
                set_active=set_active,
                settings=settings,
                role_project_id=role_project_id,
            )

    def _create_session_unlocked(
        self,
        project_id: str,
        *,
        conversations_dir,
        title: str | None,
        provider_id: str | None,
        model_id: str | None,
        reasoning_mode: str | None,
        manual_title: bool,
        set_active: bool,
        settings: dict | None,
        role_project_id: str | None,
    ) -> ProjectConversationSession:
        conversations_dir.mkdir(parents=True, exist_ok=True)
        now = _utc_now()
        session = ProjectConversationSession(
            session_id=_new_session_id(),
            sequence_number=self._session_store.next_sequence_number(conversations_dir),
            title=title.strip() if title and title.strip() else "新对话",
            provider_id=provider_id,
            model_id=model_id,
            reasoning_mode=_optional_reasoning_mode(reasoning_mode),
            created_at=now,
            updated_at=now,
            message_count=0,
            manual_title=manual_title,
            settings=_session_settings_from_payload(settings),
            role_project_id=role_project_id,
        )
        if role_project_id:
            session = replace(
                session,
                role_configuration_hash=conversation_session_configuration_hash(
                    session
                ),
            )
        session_dir = self._session_store.session_dir(project_id, session.session_id, for_write=True)
        session_dir.mkdir(parents=True, exist_ok=False)
        self._session_store.write_session(session_dir, session)
        self._message_store.ensure_messages_file(session_dir)
        self._session_store.write_index(
            conversations_dir,
            self._session_store.index_after_session_write(
                conversations_dir,
                session,
                set_active=set_active,
            ),
        )
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
        conversations_dir = self._session_store.conversations_dir(project_id, for_write=True)
        with conversation_write_lock(conversations_dir):
            session_dir = self._session_store.require_session_dir(project_id, session_id, for_write=True)
            session = self.get_session(project_id, session_id)
            if session is None:
                raise NotFoundError(f"Conversation session '{session_id}' was not found.")

            merged_settings = (
                _merge_session_settings(session.settings, settings)
                if should_update_settings
                else session.settings
            )

            updated = replace(
                session,
                title=_normalize_session_title(title) if should_update_title else session.title,
                provider_id=provider_id if should_update_provider else session.provider_id,
                model_id=model_id if should_update_model else session.model_id,
                reasoning_mode=_optional_reasoning_mode(reasoning_mode)
                if should_update_reasoning
                else session.reasoning_mode,
                manual_title=bool(manual_title)
                if should_update_manual_title
                else session.manual_title,
                settings=merged_settings,
                updated_at=_utc_now(),
            )
            configuration_changed = (
                updated.provider_id != session.provider_id
                or updated.model_id != session.model_id
                or updated.reasoning_mode != session.reasoning_mode
                or updated.settings != session.settings
            )
            if configuration_changed:
                updated = replace(updated, role_configuration_hash=None)
            if should_update_role_project_id:
                updated = replace(
                    updated,
                    role_project_id=role_project_id,
                    role_configuration_hash=(
                        conversation_session_configuration_hash(updated)
                        if role_project_id
                        else None
                    ),
                )
            self._session_store.write_session(session_dir, updated)
            self._session_store.write_index(
                conversations_dir,
                self._session_store.index_after_session_write(conversations_dir, updated, set_active=False),
            )
            return updated

    def save_session_runtime_status(
        self,
        project_id: str,
        session_id: str,
        runtime_status: str,
    ) -> None:
        if runtime_status not in {"idle", "running", "error"}:
            raise BadRequestError("无效的会话运行状态。")
        conversations_dir = self._session_store.conversations_dir(project_id, for_write=True)
        with conversation_write_lock(conversations_dir):
            self._session_store.require_session_dir(
                project_id,
                session_id,
                for_write=True,
            )
            self._state_store.write_runtime_status(
                conversations_dir,
                session_id,
                runtime_status,
                _utc_now(),
            )

    def delete_session(
        self,
        project_id: str,
        session_id: str,
        *,
        session_ids: tuple[str, ...],
    ) -> ProjectConversationSession | None:
        conversations_dir = self._session_store.conversations_dir(project_id, for_write=True)
        with conversation_write_lock(conversations_dir):
            normalized_session_ids = self._validate_session_deletion_unlocked(
                project_id,
                conversations_dir,
                session_id,
                session_ids,
            )
            session_dirs = {
                selected_session_id: self._session_store.require_session_dir(
                    project_id,
                    selected_session_id,
                    for_write=True,
                )
                for selected_session_id in normalized_session_ids
            }
            deleted_session = self.get_session(project_id, session_id)
            if deleted_session is None:
                raise NotFoundError(
                    f"Conversation session '{session_id}' was not found."
                )
            graph = self._branch_store.read_graph(conversations_dir)
            self._branch_store.delete_sessions_and_reparent(
                graph,
                frozenset(normalized_session_ids),
                deleted_at=_utc_now(),
            )
            for selected_session_id, session_dir in session_dirs.items():
                self._session_store.delete_session_dir(
                    session_dir,
                    selected_session_id,
                )
            self._branch_store.write_graph(conversations_dir, graph)

            index = self._session_store.read_index(conversations_dir)
            index["pinned_session_ids"] = sorted(
                _index_pinned_session_ids(index) - set(normalized_session_ids)
            )

            remaining_sessions = self._session_store.read_sessions_from_conversations_dir(
                conversations_dir
            )
            if not remaining_sessions:
                index["active_session_id"] = None
                self._session_store.write_index(conversations_dir, index)
                return self._create_session_unlocked(
                    project_id,
                    conversations_dir=conversations_dir,
                    title=None,
                    provider_id=deleted_session.provider_id,
                    model_id=deleted_session.model_id,
                    reasoning_mode=deleted_session.reasoning_mode,
                    manual_title=False,
                    set_active=True,
                    settings=asdict(deleted_session.settings),
                    role_project_id=deleted_session.role_project_id,
                )

            if index.get("active_session_id") in normalized_session_ids:
                live_non_root_session_ids = {
                    node.session_id
                    for node in self._branch_store.list_nodes(graph)
                    if node.deleted_at is None and node.parent_session_id is not None
                }
                remaining_root_sessions = [
                    remaining_session
                    for remaining_session in remaining_sessions.values()
                    if remaining_session.session_id not in live_non_root_session_ids
                ]
                index["active_session_id"] = (
                    max(
                        remaining_root_sessions,
                        key=lambda session: session.sequence_number,
                    ).session_id
                    if remaining_root_sessions
                    else None
                )

            self._session_store.write_index(conversations_dir, index)
            return None

    def validate_session_deletion(
        self,
        project_id: str,
        session_id: str,
        *,
        session_ids: tuple[str, ...],
    ) -> tuple[str, ...]:
        conversations_dir = self._session_store.conversations_dir(project_id)
        return self._validate_session_deletion_unlocked(
            project_id,
            conversations_dir,
            session_id,
            session_ids,
        )

    def _validate_session_deletion_unlocked(
        self,
        project_id: str,
        conversations_dir: Path,
        session_id: str,
        session_ids: tuple[str, ...],
    ) -> tuple[str, ...]:
        normalized_session_ids = tuple(dict.fromkeys(
            selected_session_id.strip()
            for selected_session_id in session_ids
            if selected_session_id.strip()
        ))
        if session_id not in normalized_session_ids:
            raise BadRequestError("删除列表必须包含当前会话。")

        existing_session_ids = {
            session.session_id
            for session in self.list_sessions(project_id)
        }
        missing_session_ids = sorted(
            set(normalized_session_ids) - existing_session_ids
        )
        if missing_session_ids:
            raise BadRequestError(
                "删除列表包含不存在的会话。",
                details={"session_ids": missing_session_ids},
            )

        graph = self._branch_store.read_graph(conversations_dir)
        allowed_session_ids = {
            session_id,
            *self._branch_store.live_descendant_session_ids(graph, session_id),
        }
        unrelated_session_ids = sorted(
            set(normalized_session_ids) - allowed_session_ids
        )
        if unrelated_session_ids:
            raise BadRequestError(
                "只能删除当前会话及其下级会话。",
                details={"session_ids": unrelated_session_ids},
            )
        return normalized_session_ids

    def fork_session(
        self,
        project_id: str,
        source_session_id: str,
        *,
        source_message_id: str,
        draft: str,
        references: list[dict],
    ) -> ProjectConversationForkResult:
        return self._branch_repository.fork_session(
            project_id,
            source_session_id,
            source_message_id=source_message_id,
            draft=draft,
            references=references,
        )

    def list_messages(
        self,
        project_id: str,
        session_id: str,
    ) -> tuple[ProjectConversationMessage, ...]:
        session_dir = self._session_store.require_session_dir(project_id, session_id)
        return self._message_store.list_messages(session_dir)

    def list_messages_page(
        self,
        project_id: str,
        session_id: str,
        *,
        limit: int | None = None,
        before_message_id: str | None = None,
    ) -> ProjectConversationMessagePage:
        session_dir = self._session_store.require_session_dir(project_id, session_id)
        page = self._message_store.list_messages_page(
            session_dir,
            limit=limit,
            before_message_id=before_message_id,
        )
        return replace(
            page,
            run_outcomes=self._run_outcomes_for_messages(
                session_dir,
                page.items,
            ),
        )

    def get_message_turn(
        self,
        project_id: str,
        session_id: str,
        user_message_id: str,
    ) -> ProjectConversationMessageTurn:
        session_dir = self._session_store.require_session_dir(project_id, session_id)
        turn = self._message_store.get_message_turn(session_dir, user_message_id)
        return replace(
            turn,
            run_outcomes=self._run_outcomes_for_messages(session_dir, turn.items),
        )

    def begin_run(
        self,
        project_id: str,
        session_id: str,
        *,
        run_id: str,
        user_message_id: str,
        started_at: str,
    ) -> None:
        session_dir = self._session_store.require_session_dir(project_id, session_id)
        begin_conversation_run(
            session_dir.parent.parent.parent,
            run_id=run_id,
            session_id=session_id,
            user_message_id=user_message_id,
            started_at=started_at,
        )

    def settle_run(
        self,
        project_id: str,
        session_id: str,
        *,
        run_id: str,
        status: str,
        error_code: str | None,
        error_message: str | None,
        attempt_count: int,
        settled_at: str,
    ) -> bool:
        session_dir = self._session_store.require_session_dir(project_id, session_id)
        return settle_conversation_run(
            session_dir.parent.parent.parent,
            run_id=run_id,
            session_id=session_id,
            status=status,
            error_code=error_code,
            error_message=error_message,
            attempt_count=attempt_count,
            settled_at=settled_at,
        )

    def get_run(
        self,
        project_id: str,
        session_id: str,
        run_id: str,
    ) -> ProjectConversationRunOutcome | None:
        session_dir = self._session_store.require_session_dir(project_id, session_id)
        payload = read_conversation_run(
            session_dir.parent.parent.parent,
            run_id,
            session_id=session_id,
        )
        return _run_outcome_from_payload(payload) if payload is not None else None

    @staticmethod
    def _run_outcomes_for_messages(
        session_dir: Path,
        messages: tuple[ProjectConversationMessage, ...],
    ) -> tuple[ProjectConversationRunOutcome, ...]:
        user_message_ids = tuple(
            message.message_id for message in messages if message.role == "user"
        )
        return tuple(
            _run_outcome_from_payload(payload)
            for payload in list_conversation_run_outcomes(
                session_dir.parent.parent.parent,
                session_id=session_dir.name,
                user_message_ids=user_message_ids,
            )
        )

    def append_message(
        self,
        project_id: str,
        session_id: str,
        *,
        role: ProjectConversationMessageRole,
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
        status: ProjectConversationMessageStatus = "done",
        sync_session_model: bool = True,
        message_id: str | None = None,
    ) -> ProjectConversationMessage:
        if role not in {"system", "user", "assistant", "tool", "error"}:
            raise BadRequestError("无效的会话消息角色。")
        if status not in {"running", "done", "error", "cancelled"}:
            raise BadRequestError("无效的会话消息状态。")
        conversations_dir = self._session_store.conversations_dir(project_id, for_write=True)
        with conversation_write_lock(conversations_dir):
            session_dir = self._session_store.require_session_dir(project_id, session_id, for_write=True)
            now, created_at_local = _message_creation_times()
            message_provider_id = provider_id
            message_model_id = model_id
            target_provider_id = None
            target_model_id = None
            if role == "user":
                target_provider_id = provider_id
                target_model_id = model_id
                message_provider_id = None
                message_model_id = None

            resolved_message_id = message_id or f"msg_{uuid4().hex[:16]}"
            if message_id and any(
                existing.message_id == message_id
                for existing in self._message_store.list_messages(session_dir)
            ):
                raise ConflictError(f"Conversation message '{message_id}' already exists.")
            graph = self._branch_store.read_graph(conversations_dir)
            pending_variant = (
                self._branch_store.pending_variant_for_session(graph, session_id)
                if role == "user"
                else None
            )
            origin_message_id = resolved_message_id
            variant_group_id = (
                pending_variant.variant_group_id
                if pending_variant is not None
                else resolved_message_id if role == "user" else None
            )
            variant_index = pending_variant.variant_index if pending_variant is not None else 1
            message = ProjectConversationMessage(
                message_id=resolved_message_id,
                session_id=session_id,
                role=role,
                content=content,
                thinking_content=thinking_content if role in {"assistant", "error"} else "",
                usage=usage if role in {"assistant", "error"} else None,
                context_tokens=context_tokens if role in {"assistant", "error"} else None,
                context_tokens_estimated=(
                    context_tokens_estimated
                    if role in {"assistant", "error"}
                    else False
                ),
                provider_id=message_provider_id,
                model_id=message_model_id,
                status=status,
                created_at=now,
                updated_at=now,
                created_at_local=created_at_local,
                target_provider_id=target_provider_id,
                target_model_id=target_model_id,
                name=name,
                tool_call_id=tool_call_id,
                tool_calls=tool_calls if role == "assistant" else (),
                protocol_continuation=(
                    protocol_continuation if role == "assistant" else None
                ),
                content_parts=content_parts if role in {"user", "assistant", "tool"} else (),
                references=references if role == "user" and references is not None else [],
                origin_message_id=origin_message_id,
                variant_group_id=variant_group_id,
                variant_index=variant_index,
            )

            self._message_store.append_message(session_dir, message)

            turn_id = (
                resolved_message_id
                if role == "user"
                else latest_user_message_id(session_dir)
            )
            append_journal_event(
                conversations_dir.parent,
                session_id=session_id,
                run_id=f"run_{turn_id}" if turn_id else None,
                turn_id=turn_id,
                tool_call_id=tool_call_id,
                event_type=f"message.{role}.committed",
                occurred_at=now,
                payload={
                    "message_id": resolved_message_id,
                    "role": role,
                    "status": status,
                    "has_tool_calls": bool(tool_calls),
                },
            )

            session = self.get_session(project_id, session_id)
            if session is not None:
                next_provider_id = session.provider_id
                next_model_id = session.model_id
                if sync_session_model:
                    next_provider_id = provider_id or session.provider_id
                    next_model_id = model_id or session.model_id
                updated = replace(
                    session,
                    provider_id=next_provider_id,
                    model_id=next_model_id,
                    updated_at=now,
                    message_count=session.message_count + 1,
                )
                self._session_store.write_session(session_dir, updated)
                index = self._session_store.index_after_session_write(
                    conversations_dir, updated, set_active=False
                )
                runtime_status = _runtime_status_for_appended_message(role)
                if runtime_status is not None:
                    self._state_store.write_runtime_status(
                        conversations_dir,
                        session_id,
                        runtime_status,
                        now,
                    )
                self._session_store.write_index(conversations_dir, index)
            if pending_variant is not None:
                self._branch_store.complete_pending_variant(
                    graph,
                    session_id=session_id,
                    message_id=resolved_message_id,
                    origin_message_id=origin_message_id,
                )
                self._branch_store.write_graph(conversations_dir, graph)
            return message

    def insert_system_message_after(
        self,
        project_id: str,
        session_id: str,
        *,
        after_message_id: str,
        content: str,
        name: str | None = None,
        status: ProjectConversationMessageStatus = "done",
    ) -> ProjectConversationMessage:
        conversations_dir = self._session_store.conversations_dir(
            project_id,
            for_write=True,
        )
        with conversation_write_lock(conversations_dir):
            session_dir = self._session_store.require_session_dir(
                project_id,
                session_id,
                for_write=True,
            )
            messages = list(self._message_store.list_messages(session_dir))
            anchor_index = next(
                (
                    index
                    for index, message in enumerate(messages)
                    if message.message_id == after_message_id
                ),
                None,
            )
            if anchor_index is None:
                raise NotFoundError(
                    f"Conversation message '{after_message_id}' was not found."
                )

            now, created_at_local = _message_creation_times()
            message_id = f"msg_{uuid4().hex[:16]}"
            message = ProjectConversationMessage(
                message_id=message_id,
                session_id=session_id,
                role="system",
                content=content,
                thinking_content="",
                usage=None,
                provider_id=None,
                model_id=None,
                status=status,
                created_at=now,
                updated_at=now,
                created_at_local=created_at_local,
                name=name,
                origin_message_id=message_id,
            )
            messages.insert(anchor_index + 1, message)
            self._message_store.write_messages(session_dir, tuple(messages))
            turn_id = next(
                (
                    candidate.message_id
                    for candidate in reversed(messages[: anchor_index + 1])
                    if candidate.role == "user"
                ),
                None,
            )
            append_journal_event(
                conversations_dir.parent,
                session_id=session_id,
                run_id=f"run_{turn_id}" if turn_id else None,
                turn_id=turn_id,
                tool_call_id=None,
                event_type="message.system.inserted",
                occurred_at=now,
                payload={
                    "message_id": message_id,
                    "after_message_id": after_message_id,
                    "status": status,
                },
            )

            session = self.get_session(project_id, session_id)
            if session is not None:
                updated = replace(
                    session,
                    updated_at=now,
                    message_count=session.message_count + 1,
                )
                self._session_store.write_session(session_dir, updated)
                index = self._session_store.index_after_session_write(
                    conversations_dir,
                    updated,
                    set_active=False,
                )
                self._session_store.write_index(conversations_dir, index)
            return message

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
        conversations_dir = self._session_store.conversations_dir(project_id, for_write=True)
        with conversation_write_lock(conversations_dir):
            session_dir = self._session_store.require_session_dir(
                project_id,
                session_id,
                for_write=True,
            )
            messages = list(self._message_store.list_messages(session_dir))
            message_index = next(
                (
                    index
                    for index, message in enumerate(messages)
                    if message.message_id == message_id
                ),
                None,
            )
            if message_index is None:
                raise NotFoundError(
                    f"Conversation message '{message_id}' was not found."
                )
            current = messages[message_index]
            if current.role not in {"assistant", "error"}:
                raise ConflictError(
                    f"Conversation message '{message_id}' is not an assistant message."
                )
            cancelled = replace(
                current,
                status="cancelled",
                usage=usage if usage is not None else current.usage,
                context_tokens=(
                    context_tokens
                    if context_tokens is not None
                    else current.context_tokens
                ),
                context_tokens_estimated=(
                    context_tokens_estimated
                    if context_tokens is not None
                    else current.context_tokens_estimated
                ),
                updated_at=_utc_now(),
            )
            messages[message_index] = cancelled
            self._message_store.write_messages(session_dir, tuple(messages))
            turn_id = next(
                (
                    candidate.message_id
                    for candidate in reversed(messages[:message_index])
                    if candidate.role == "user"
                ),
                None,
            )
            append_journal_event(
                conversations_dir.parent,
                session_id=session_id,
                run_id=f"run_{turn_id}" if turn_id else None,
                turn_id=turn_id,
                tool_call_id=None,
                event_type="message.assistant.cancelled",
                occurred_at=cancelled.updated_at,
                payload={"message_id": message_id, "status": "cancelled"},
            )
            return cancelled

    def append_naming_call_record(
        self,
        project_id: str,
        session_id: str,
        record: ProjectConversationNamingCallRecord,
    ) -> None:
        session_dir = self._session_store.require_session_dir(project_id, session_id, for_write=True)
        self._message_store.append_naming_call_record(session_dir, record)

    def append_model_exchange(
        self,
        project_id: str,
        session_id: str,
        payload: dict,
    ) -> None:
        session_dir = self._session_store.require_session_dir(
            project_id,
            session_id,
            for_write=True,
        )
        self._message_store.append_model_exchange(session_dir, payload)

    def write_injection_preview(
        self,
        project_id: str,
        session_id: str,
        payload: dict,
    ) -> None:
        session_dir = self._session_store.require_session_dir(project_id, session_id, for_write=True)
        write_document(session_dir, "injection_preview", payload)


def _message_creation_times() -> tuple[str, str]:
    local_now = datetime.now().astimezone()
    return (
        local_now.astimezone(UTC).isoformat(),
        local_now.isoformat(timespec="seconds"),
    )


def _run_outcome_from_payload(payload: dict) -> ProjectConversationRunOutcome:
    return ProjectConversationRunOutcome(
        run_id=str(payload["run_id"]),
        session_id=str(payload["session_id"]),
        user_message_id=str(payload["user_message_id"]),
        status=payload["status"],
        error_code=payload.get("error_code"),
        error_message=payload.get("error_message"),
        attempt_count=max(0, int(payload.get("attempt_count") or 0)),
        started_at=str(payload["started_at"]),
        settled_at=(str(payload["settled_at"]) if payload.get("settled_at") else None),
    )


@lru_cache
def get_project_conversation_repository() -> ProjectConversationRepository:
    return ProjectConversationRepository(get_project_repository())
