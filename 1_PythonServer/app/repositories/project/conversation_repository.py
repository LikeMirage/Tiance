from __future__ import annotations

from dataclasses import asdict, replace
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from uuid import uuid4

from app.core.errors import ConflictError, NotFoundError
from app.domain.llm.chat import ChatMessageContentPart, ChatToolCall
from app.domain.project.project_conversation import (
    conversation_session_configuration_hash,
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
from app.repositories.project.conversation_branch_repository import (
    ProjectConversationBranchRepository,
)
from app.repositories.project.conversation_branch_store import ConversationBranchStore
from app.repositories.project.conversation_relation_repository import (
    ProjectConversationRelationRepository,
)
from app.repositories.project.conversation_serialization import (
    _index_pinned_session_ids,
    _index_session_items,
    _merge_session_settings,
    _merge_session_state,
    _new_session_id,
    _next_session_sequence_number,
    _normalize_session_title,
    _optional_reasoning_mode,
    _runtime_status_for_appended_message,
    _session_settings_from_payload,
    _session_state_from_payload,
    _session_state_to_payload,
    _utc_now,
)
from app.repositories.project.conversation_storage import conversation_write_lock
from app.repositories.project.conversation_stores import (
    ConversationMessageStore,
    ConversationSessionStore,
    ConversationStateStore,
)
from app.repositories.project.project_repository import ProjectRepository, get_project_repository
from app.repositories.project.conversation_database import write_document


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
        return self._list_sessions_from_index(conversations_dir, index)

    def _list_sessions_from_index(
        self,
        conversations_dir: Path,
        index: dict,
    ) -> tuple[ProjectConversationSession, ...]:
        if not _index_session_items(index):
            return ()
        pinned_session_ids = _index_pinned_session_ids(index)
        sessions: list[ProjectConversationSession] = []
        for item in _index_session_items(index):
            if not isinstance(item, dict):
                continue
            session_id = str(item.get("session_id") or "")
            session = self._session_store.read_session_from_conversations_dir(
                conversations_dir,
                session_id,
            )
            if session is not None:
                sessions.append(
                    replace(session, pinned=session_id in pinned_session_ids)
                )
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
    ) -> tuple[str, str | None, dict[str, ProjectConversationSessionState]]:
        conversations_dir = self._session_store.conversations_dir(project_id)
        index = self._session_store.read_index(conversations_dir)
        sessions = self._list_sessions_from_index(conversations_dir, index)
        return self._state_store.conversation_state(sessions, index)

    def get_overview_data(
        self,
        project_id: str,
    ) -> tuple[
        tuple[ProjectConversationSession, ...],
        tuple[ProjectConversationBranchNode, ...],
        str | None,
        dict[str, ProjectConversationSessionState],
    ]:
        conversations_dir = self._session_store.conversations_dir(project_id)
        index = self._session_store.read_index(conversations_dir)
        sessions = self._list_sessions_from_index(conversations_dir, index)
        graph = self._branch_store.read_graph(conversations_dir)
        _assistant_title, active_session_id, session_states = (
            self._state_store.conversation_state(sessions, index)
        )
        return (
            sessions,
            self._branch_store.list_nodes(graph),
            active_session_id,
            session_states,
        )

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
        _ = assistant_title, should_update_assistant_title
        conversations_dir = self._session_store.conversations_dir(project_id, for_write=True)
        with conversation_write_lock(conversations_dir):
            index = self._session_store.read_index(conversations_dir)
            sessions = self._list_sessions_from_index(conversations_dir, index)
            _assistant_title, existing_active_session_id, existing_states = (
                self._state_store.conversation_state(
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

            updated_states = dict(existing_states)
            for session_id, payload in session_states.items():
                if session_id not in session_ids:
                    raise NotFoundError(f"Conversation session '{session_id}' was not found.")
                updated_states[session_id] = _merge_session_state(
                    session_id,
                    payload,
                    updated_states.get(session_id),
                )

            index["session_states"] = {
                session_id: _session_state_to_payload(state)
                for session_id, state in updated_states.items()
                if session_id in session_ids
            }
            self._session_store.write_index(conversations_dir, index)
            return self._state_store.conversation_state(sessions, index)

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

            live_session_ids = {
                str(item.get("session_id") or "")
                for item in _index_session_items(index)
                if isinstance(item, dict)
            }
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
            sequence_number=_next_session_sequence_number(self._session_store.read_index(conversations_dir)),
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
            self._session_store.index_with_session(
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
                self._session_store.index_with_session(conversations_dir, updated, set_active=False),
            )
            return updated

    def save_session_runtime_status(
        self,
        project_id: str,
        session_id: str,
        runtime_status: str,
    ) -> None:
        if runtime_status not in {"idle", "running", "error"}:
            runtime_status = "idle"
        conversations_dir = self._session_store.conversations_dir(project_id, for_write=True)
        with conversation_write_lock(conversations_dir):
            self._session_store.require_session_dir(
                project_id,
                session_id,
                for_write=True,
            )
            index = self._session_store.read_index(conversations_dir)
            session_states = index.setdefault("session_states", {})
            if not isinstance(session_states, dict):
                session_states = {}
                index["session_states"] = session_states
            existing_state = _session_state_from_payload(session_id, session_states.get(session_id))
            session_states[session_id] = _session_state_to_payload(
                _merge_session_state(
                    session_id,
                    {"runtime_status": runtime_status},
                    existing_state,
                )
            )
            self._session_store.write_index(conversations_dir, index)

    def delete_session(
        self,
        project_id: str,
        session_id: str,
    ) -> ProjectConversationSession | None:
        conversations_dir = self._session_store.conversations_dir(project_id, for_write=True)
        with conversation_write_lock(conversations_dir):
            session_dir = self._session_store.require_session_dir(project_id, session_id, for_write=True)
            deleted_session = self.get_session(project_id, session_id)
            if deleted_session is None:
                raise NotFoundError(
                    f"Conversation session '{session_id}' was not found."
                )
            graph = self._branch_store.read_graph(conversations_dir)
            graph_changed = self._branch_store.mark_session_deleted(
                graph,
                session_id,
                deleted_at=_utc_now(),
            )
            self._session_store.delete_session_dir(session_dir, session_id)
            if graph_changed:
                self._branch_store.write_graph(conversations_dir, graph)

            index = self._session_store.read_index(conversations_dir)
            index["sessions"] = [
                item for item in index.get("sessions", [])
                if isinstance(item, dict) and item.get("session_id") != session_id
            ]
            index["pinned_session_ids"] = sorted(
                _index_pinned_session_ids(index) - {session_id}
            )

            session_states = index.get("session_states")
            if isinstance(session_states, dict):
                session_states.pop(session_id, None)

            remaining_session_items = _index_session_items(index)
            if not remaining_session_items:
                index["active_session_id"] = None
                index["session_states"] = {}
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

            if index.get("active_session_id") == session_id:
                remaining_sessions = [
                    self.get_session(project_id, str(item.get("session_id") or ""))
                    for item in remaining_session_items
                    if isinstance(item, dict)
                ]
                remaining_sessions = [session for session in remaining_sessions if session is not None]
                index["active_session_id"] = remaining_sessions[0].session_id if remaining_sessions else None

            self._session_store.write_index(conversations_dir, index)
            return None

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
        return self._message_store.list_messages_page(
            session_dir,
            limit=limit,
            before_message_id=before_message_id,
        )

    def get_message_turn(
        self,
        project_id: str,
        session_id: str,
        user_message_id: str,
    ) -> ProjectConversationMessageTurn:
        session_dir = self._session_store.require_session_dir(project_id, session_id)
        return self._message_store.get_message_turn(session_dir, user_message_id)

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
        content_parts: tuple[ChatMessageContentPart, ...] = (),
        references: list[dict] | None = None,
        status: str = "done",
        sync_session_model: bool = True,
        message_id: str | None = None,
    ) -> ProjectConversationMessage:
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
                content_parts=content_parts if role in {"user", "assistant", "tool"} else (),
                references=references if role == "user" and references is not None else [],
                origin_message_id=origin_message_id,
                variant_group_id=variant_group_id,
                variant_index=variant_index,
            )

            self._message_store.append_message(session_dir, message)

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
                index = self._session_store.index_with_session(conversations_dir, updated, set_active=False)
                runtime_status = _runtime_status_for_appended_message(role)
                if runtime_status is not None:
                    session_states = index.setdefault("session_states", {})
                    if not isinstance(session_states, dict):
                        session_states = {}
                        index["session_states"] = session_states
                    existing_state = _session_state_from_payload(
                        session_id,
                        session_states.get(session_id),
                    )
                    session_states[session_id] = _session_state_to_payload(
                        _merge_session_state(
                            session_id,
                            {"runtime_status": runtime_status},
                            existing_state,
                        )
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
        status: str = "done",
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

            session = self.get_session(project_id, session_id)
            if session is not None:
                updated = replace(
                    session,
                    updated_at=now,
                    message_count=session.message_count + 1,
                )
                self._session_store.write_session(session_dir, updated)
                index = self._session_store.index_with_session(
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
            return cancelled

    def append_naming_call_record(
        self,
        project_id: str,
        session_id: str,
        record: ProjectConversationNamingCallRecord,
    ) -> None:
        session_dir = self._session_store.require_session_dir(project_id, session_id, for_write=True)
        self._message_store.append_naming_call_record(session_dir, record)

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


@lru_cache
def get_project_conversation_repository() -> ProjectConversationRepository:
    return ProjectConversationRepository(get_project_repository())
