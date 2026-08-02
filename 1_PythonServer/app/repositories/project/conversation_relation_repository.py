from dataclasses import replace
from pathlib import Path
from shutil import rmtree
from uuid import uuid4

from app.core.atomic_replace import atomic_replace_path
from app.core.errors import ConflictError, NotFoundError
from app.domain.project.project_conversation import (
    ProjectConversationSession,
    conversation_session_configuration_hash,
)
from app.repositories.project.conversation_branch_store import (
    CREATED_BY_AI,
    RELATION_KIND_CHILD,
    ConversationBranchStore,
)
from app.repositories.project.conversation_serialization import (
    _merge_session_settings,
    _new_session_id,
    _next_session_sequence_number,
    _optional_reasoning_mode,
    _utc_now,
)
from app.repositories.project.conversation_storage import conversation_write_lock
from app.repositories.project.conversation_stores import (
    ConversationMessageStore,
    ConversationSessionStore,
)


class ProjectConversationRelationRepository:
    """Creates a fresh child session and its lineage edge as one repository action."""

    def __init__(
        self,
        *,
        session_store: ConversationSessionStore,
        message_store: ConversationMessageStore,
        branch_store: ConversationBranchStore,
    ) -> None:
        self._session_store = session_store
        self._message_store = message_store
        self._branch_store = branch_store

    def create_ai_child_session(
        self,
        project_id: str,
        parent_session_id: str,
        *,
        title: str | None,
        provider_id: str | None,
        model_id: str | None,
        reasoning_mode: str | None,
        manual_title: bool,
        set_active: bool,
        settings: dict | None,
        role_project_id: str | None = None,
    ) -> ProjectConversationSession:
        conversations_dir = self._session_store.conversations_dir(
            project_id,
            for_write=True,
        )
        with conversation_write_lock(conversations_dir):
            parent_session = self._session_store.read_session(
                project_id,
                parent_session_id,
            )
            if parent_session is None:
                raise NotFoundError(
                    f"Conversation session '{parent_session_id}' was not found."
                )
            if (provider_id is None) != (model_id is None):
                raise ConflictError("覆盖子会话模型时必须同时指定供应商和模型。")

            index = self._session_store.read_index(conversations_dir)
            graph = self._branch_store.read_graph(conversations_dir)
            now = _utc_now()
            parent_node = self._branch_store.ensure_root_node(
                graph,
                parent_session,
                created_at=parent_session.created_at or now,
            )
            session_id = _new_session_id()
            self._branch_store.create_child_node(
                graph,
                parent=parent_node,
                session_id=session_id,
                created_at=now,
                created_by=CREATED_BY_AI,
                relation_kind=RELATION_KIND_CHILD,
                source_message_id=None,
            )
            session = ProjectConversationSession(
                session_id=session_id,
                sequence_number=_next_session_sequence_number(index),
                title=title.strip() if title and title.strip() else "新对话",
                provider_id=(
                    provider_id
                    if provider_id is not None
                    else parent_session.provider_id
                ),
                model_id=(
                    model_id
                    if model_id is not None
                    else parent_session.model_id
                ),
                reasoning_mode=(
                    _optional_reasoning_mode(reasoning_mode)
                    if reasoning_mode is not None
                    else parent_session.reasoning_mode
                ),
                created_at=now,
                updated_at=now,
                message_count=0,
                manual_title=manual_title,
                settings=_merge_session_settings(parent_session.settings, settings),
                role_project_id=role_project_id or parent_session.role_project_id,
                role_configuration_hash=parent_session.role_configuration_hash,
            )
            if role_project_id:
                session = replace(
                    session,
                    role_configuration_hash=conversation_session_configuration_hash(
                        session
                    ),
                )

            target_session_dir = self._session_store.session_dir(
                project_id,
                session_id,
                for_write=True,
            )
            temporary_dir = Path(f"{target_session_dir}.tmp-{uuid4().hex}")
            index_written = False
            try:
                temporary_dir.mkdir(parents=True, exist_ok=False)
                self._session_store.write_session(temporary_dir, session)
                self._message_store.ensure_messages_file(temporary_dir)
                atomic_replace_path(temporary_dir, target_session_dir)
                self._session_store.write_index(
                    conversations_dir,
                    self._session_store.index_with_session(
                        conversations_dir,
                        session,
                        set_active=set_active,
                    ),
                )
                index_written = True
                self._branch_store.write_graph(conversations_dir, graph)
            except Exception:
                if temporary_dir.exists():
                    rmtree(temporary_dir, ignore_errors=True)
                index_restored = not index_written
                if index_written:
                    try:
                        self._session_store.write_index(conversations_dir, index)
                        index_restored = True
                    except Exception:
                        index_restored = False
                if index_restored and target_session_dir.exists():
                    rmtree(target_session_dir, ignore_errors=True)
                raise

            return session
