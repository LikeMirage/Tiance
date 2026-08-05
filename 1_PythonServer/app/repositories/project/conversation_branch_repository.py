from dataclasses import replace
from pathlib import Path
from shutil import rmtree
from uuid import uuid4

from app.core.atomic_replace import atomic_replace_path
from app.core.errors import ConflictError, NotFoundError
from app.domain.project.conversation_branch import (
    ProjectConversationForkResult,
    build_derived_session_title,
)
from app.repositories.project.conversation_branch_copy import (
    copy_message_prefix,
    write_inherited_compressions,
    write_inherited_long_term_memory_state,
    write_inherited_memory_delivery_state,
)
from app.repositories.project.conversation_attachment_repository import (
    copy_referenced_attachments,
)
from app.repositories.project.conversation_branch_store import (
    CREATED_BY_USER,
    RELATION_KIND_FORK,
    ConversationBranchStore,
)
from app.repositories.project.conversation_serialization import (
    _merge_session_state,
    _new_session_id,
    _next_session_sequence_number,
    _session_state_from_payload,
    _session_state_to_payload,
    _utc_now,
)
from app.repositories.project.conversation_storage import conversation_write_lock
from app.repositories.project.conversation_stores import (
    ConversationMessageStore,
    ConversationSessionStore,
)


class ProjectConversationBranchRepository:
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

    def fork_session(
        self,
        project_id: str,
        source_session_id: str,
        *,
        source_message_id: str,
        draft: str,
        references: list[dict],
    ) -> ProjectConversationForkResult:
        conversations_dir = self._session_store.conversations_dir(project_id, for_write=True)
        with conversation_write_lock(conversations_dir):
            source_session_dir = self._session_store.require_session_dir(
                project_id,
                source_session_id,
                for_write=True,
            )
            source_session = self._session_store.read_session(project_id, source_session_id)
            if source_session is None:
                raise NotFoundError(f"Conversation session '{source_session_id}' was not found.")
            index = self._session_store.read_index(conversations_dir)
            states = index.get("session_states")
            source_state = _session_state_from_payload(
                source_session_id,
                states.get(source_session_id) if isinstance(states, dict) else None,
            )
            if source_state.runtime_status == "running":
                raise ConflictError("当前会话正在生成，完成或停止后才能创建分支。")

            source_messages = self._message_store.list_messages(source_session_dir)
            source_index = next(
                (
                    message_index
                    for message_index, message in enumerate(source_messages)
                    if message.message_id == source_message_id
                ),
                None,
            )
            if source_index is None:
                raise NotFoundError(f"Conversation message '{source_message_id}' was not found.")
            source_message = source_messages[source_index]
            if source_message.role != "user" or source_message.status != "done":
                raise ConflictError("只能从已完成的用户消息创建分支。")

            now = _utc_now()
            graph = self._branch_store.read_graph(conversations_dir)
            parent_branch = self._branch_store.ensure_root_node(
                graph,
                source_session,
                created_at=source_session.created_at or now,
            )
            target_session_id = _new_session_id()
            branch = self._branch_store.create_child_node(
                graph,
                parent=parent_branch,
                session_id=target_session_id,
                created_at=now,
                created_by=CREATED_BY_USER,
                relation_kind=RELATION_KIND_FORK,
                source_message_id=source_message_id,
            )
            source_origin_id = source_message.origin_message_id or source_message.message_id
            variant_group_id = source_message.variant_group_id or source_origin_id
            self._branch_store.ensure_source_variant(
                graph,
                branch=parent_branch,
                session_id=source_session_id,
                message_id=source_message.message_id,
                origin_message_id=source_origin_id,
                variant_group_id=variant_group_id,
                variant_index=max(1, source_message.variant_index),
                created_at=source_message.created_at or now,
            )
            self._branch_store.create_pending_variant(
                graph,
                branch=branch,
                variant_group_id=variant_group_id,
                created_at=now,
            )

            copied_messages, message_id_map = copy_message_prefix(
                source_messages[:source_index],
                target_session_id=target_session_id,
            )
            child_session = replace(
                source_session,
                session_id=target_session_id,
                sequence_number=_next_session_sequence_number(index),
                title=build_derived_session_title(
                    source_session.title,
                    branch.sibling_index,
                ),
                created_at=now,
                updated_at=now,
                message_count=len(copied_messages),
                manual_title=False,
            )
            child_state = _merge_session_state(
                target_session_id,
                {
                    "runtime_status": "idle",
                    "draft": draft,
                    "references": references,
                },
                None,
            )

            target_session_dir = self._session_store.session_dir(
                project_id,
                target_session_id,
                for_write=True,
            )
            temporary_dir = Path(f"{target_session_dir}.tmp-{uuid4().hex}")
            index_written = False
            try:
                temporary_dir.mkdir(parents=True, exist_ok=False)
                self._session_store.write_session(temporary_dir, child_session)
                self._message_store.write_messages(temporary_dir, copied_messages)
                copy_referenced_attachments(
                    source_session_dir,
                    temporary_dir,
                    copied_messages,
                    references,
                )
                write_inherited_compressions(
                    source_session_dir,
                    temporary_dir,
                    target_session_id=target_session_id,
                    message_id_map=message_id_map,
                )
                write_inherited_long_term_memory_state(
                    source_session_dir,
                    temporary_dir,
                    target_session_id=target_session_id,
                    message_id_map=message_id_map,
                )
                write_inherited_memory_delivery_state(
                    source_session_dir,
                    temporary_dir,
                    message_id_map=message_id_map,
                )
                atomic_replace_path(temporary_dir, target_session_dir)
                next_index = self._session_store.index_with_session(
                    conversations_dir,
                    child_session,
                    set_active=True,
                )
                session_states = next_index.setdefault("session_states", {})
                if isinstance(session_states, dict):
                    session_states[target_session_id] = _session_state_to_payload(child_state)
                self._session_store.write_index(conversations_dir, next_index)
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

            return ProjectConversationForkResult(
                session=child_session,
                state=child_state,
                branch=branch,
                source_message=source_message,
            )
