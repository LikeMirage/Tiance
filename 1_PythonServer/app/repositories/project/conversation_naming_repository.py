from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from functools import lru_cache
from json import dumps, loads
from pathlib import Path
from shutil import rmtree
from typing import Any
from uuid import uuid4

from app.core.atomic_replace import atomic_replace_path
from app.core.errors import ConflictError, NotFoundError
from app.domain.project.conversation_branch import (
    ProjectConversationBranchNode,
    build_derived_session_title,
)
from app.domain.project.project_conversation import (
    ProjectConversationSession,
    ProjectConversationSessionSettings,
    functional_session_recursion_guard_settings,
)
from app.repositories.project.conversation_branch_copy import (
    copy_message_prefix,
    write_derived_session_snapshot,
)
from app.repositories.project.conversation_branch_store import (
    CREATED_BY_SYSTEM,
    FUNCTION_TYPE_AUTOMATIC_NAMING,
    RELATION_KIND_FUNCTIONAL,
    ConversationBranchStore,
)
from app.repositories.project.conversation_serialization import (
    _merge_session_state,
    _new_session_id,
    _next_session_sequence_number,
    _normalize_session_title,
    _session_state_to_payload,
    _utc_now,
)
from app.repositories.project.conversation_storage import (
    atomic_write_text,
    conversation_write_lock,
)
from app.repositories.project.conversation_stores import (
    ConversationMessageStore,
    ConversationSessionStore,
    ConversationStateStore,
)
from app.repositories.project.project_repository import (
    ProjectRepository,
    get_project_repository,
)
from app.repositories.project.conversation_database import read_document, write_document


AUTOMATIC_NAMING_TASK_FILE = "automatic_naming_task.json"
AUTOMATIC_NAMING_TASK_VERSION = 1
DEFAULT_SESSION_TITLE = "新对话"
ACTIVE_TASK_STATUSES = {"pending", "running"}


@dataclass(frozen=True, slots=True)
class ConversationNamingTaskCreation:
    session: ProjectConversationSession
    branch: ProjectConversationBranchNode
    task: dict[str, Any]


class ProjectConversationNamingRepository:
    def __init__(
        self,
        project_repository: ProjectRepository,
        *,
        state_store: ConversationStateStore | None = None,
        session_store: ConversationSessionStore | None = None,
        message_store: ConversationMessageStore | None = None,
        branch_store: ConversationBranchStore | None = None,
    ) -> None:
        state = state_store or ConversationStateStore()
        self._session_store = session_store or ConversationSessionStore(
            project_repository,
            state_store=state,
        )
        self._message_store = message_store or ConversationMessageStore()
        self._branch_store = branch_store or ConversationBranchStore()

    def create_task(
        self,
        project_id: str,
        source_session_id: str,
        *,
        snapshot_boundary_message_id: str,
        target_provider_id: str,
        target_model_id: str,
        target_reasoning_mode: str | None,
        target_settings: ProjectConversationSessionSettings,
        mode: str,
        trigger: dict[str, Any],
        task_prompt: str,
    ) -> ConversationNamingTaskCreation | None:
        conversations_dir = self._session_store.conversations_dir(
            project_id,
            for_write=True,
        )
        with conversation_write_lock(conversations_dir):
            source_session_dir = self._session_store.require_session_dir(
                project_id,
                source_session_id,
                for_write=True,
            )
            source_session = self._session_store.read_session(
                project_id,
                source_session_id,
            )
            if source_session is None:
                raise NotFoundError(
                    f"Conversation session '{source_session_id}' was not found."
                )
            if (
                source_session.title != DEFAULT_SESSION_TITLE
                or source_session.manual_title
            ):
                return None

            original_graph = self._branch_store.read_graph(conversations_dir)
            if self._has_active_task(
                project_id,
                source_session_id,
                original_graph,
            ):
                return None

            source_messages = self._message_store.list_messages(source_session_dir)
            boundary_index = _message_index(
                source_messages,
                snapshot_boundary_message_id,
            )
            if boundary_index is None:
                raise ConflictError("自动命名快照边界已不在来源会话中，任务未创建。")

            graph = deepcopy(original_graph)
            now = _utc_now()
            parent = self._branch_store.ensure_root_node(
                graph,
                source_session,
                created_at=source_session.created_at or now,
            )
            function_session_id = _new_session_id()
            branch = self._branch_store.create_child_node(
                graph,
                parent=parent,
                session_id=function_session_id,
                created_at=now,
                created_by=CREATED_BY_SYSTEM,
                relation_kind=RELATION_KIND_FUNCTIONAL,
                source_message_id=snapshot_boundary_message_id,
                function_type=FUNCTION_TYPE_AUTOMATIC_NAMING,
            )
            copied_messages, message_id_map = copy_message_prefix(
                source_messages[: boundary_index + 1],
                target_session_id=function_session_id,
            )
            index = self._session_store.read_index(conversations_dir)
            function_session = replace(
                source_session,
                session_id=function_session_id,
                sequence_number=_next_session_sequence_number(index),
                title=build_derived_session_title(
                    source_session.title,
                    branch.sibling_index,
                ),
                provider_id=target_provider_id,
                model_id=target_model_id,
                reasoning_mode=target_reasoning_mode,
                created_at=now,
                updated_at=now,
                message_count=len(copied_messages),
                manual_title=True,
                settings=functional_session_recursion_guard_settings(
                    target_settings
                ),
            )
            function_state = _merge_session_state(
                function_session_id,
                {
                    "runtime_status": "idle",
                    "draft": task_prompt,
                    "references": [],
                },
                None,
            )
            task = {
                "version": AUTOMATIC_NAMING_TASK_VERSION,
                "task_type": FUNCTION_TYPE_AUTOMATIC_NAMING,
                "task_id": f"naming_{uuid4().hex[:16]}",
                "project_id": project_id,
                "source_session_id": source_session_id,
                "function_session_id": function_session_id,
                "snapshot_boundary_message_id": snapshot_boundary_message_id,
                "mode": mode,
                "provider_id": target_provider_id,
                "model_id": target_model_id,
                "trigger": trigger,
                "status": "pending",
                "selected_title": None,
                "created_at": now,
                "completed_at": None,
            }

            target_session_dir = self._session_store.session_dir(
                project_id,
                function_session_id,
                for_write=True,
            )
            temporary_dir = Path(f"{target_session_dir}.tmp-{uuid4().hex}")
            index_written = False
            graph_written = False
            try:
                temporary_dir.mkdir(parents=True, exist_ok=False)
                self._session_store.write_session(
                    temporary_dir,
                    function_session,
                )
                self._message_store.write_messages(
                    temporary_dir,
                    copied_messages,
                )
                write_derived_session_snapshot(
                    source_session_dir,
                    temporary_dir,
                    copied_messages=copied_messages,
                    target_session_id=function_session_id,
                    message_id_map=message_id_map,
                )
                _write_json_object(
                    temporary_dir / AUTOMATIC_NAMING_TASK_FILE,
                    task,
                )
                atomic_replace_path(temporary_dir, target_session_dir)

                next_index = self._session_store.index_with_session(
                    conversations_dir,
                    function_session,
                    set_active=False,
                )
                states = next_index.setdefault("session_states", {})
                if isinstance(states, dict):
                    states[function_session_id] = _session_state_to_payload(
                        function_state
                    )
                self._session_store.write_index(conversations_dir, next_index)
                index_written = True
                self._branch_store.write_graph(conversations_dir, graph)
                graph_written = True
            except Exception:
                if temporary_dir.exists():
                    rmtree(temporary_dir, ignore_errors=True)
                if graph_written:
                    self._branch_store.write_graph(
                        conversations_dir,
                        original_graph,
                    )
                if index_written:
                    self._session_store.write_index(conversations_dir, index)
                if target_session_dir.exists():
                    rmtree(target_session_dir, ignore_errors=True)
                raise

            return ConversationNamingTaskCreation(
                session=function_session,
                branch=branch,
                task=task,
            )

    def apply_title(
        self,
        project_id: str,
        function_session_id: str,
        *,
        title: str,
    ) -> dict[str, Any]:
        conversations_dir = self._session_store.conversations_dir(
            project_id,
            for_write=True,
        )
        with conversation_write_lock(conversations_dir):
            function_session_dir = self._session_store.require_session_dir(
                project_id,
                function_session_id,
                for_write=True,
            )
            task_path = function_session_dir / AUTOMATIC_NAMING_TASK_FILE
            task = _read_json_object(task_path)
            if task is None:
                raise ConflictError("当前会话不是自动命名任务会话。")
            if task.get("task_type") != FUNCTION_TYPE_AUTOMATIC_NAMING:
                raise ConflictError("当前功能会话不是自动命名会话。")
            source_session_id = task.get("source_session_id")
            if not isinstance(source_session_id, str) or not source_session_id:
                raise ConflictError("自动命名任务缺少有效的来源会话。")

            graph = self._branch_store.read_graph(conversations_dir)
            node = self._branch_store.node_for_session(
                graph,
                function_session_id,
            )
            if (
                node is None
                or node.relation_kind != RELATION_KIND_FUNCTIONAL
                or node.function_type != FUNCTION_TYPE_AUTOMATIC_NAMING
                or node.parent_session_id != source_session_id
            ):
                raise ConflictError("自动命名功能会话与来源会话关系不一致。")
            if task.get("status") == "completed":
                return {
                    "applied": True,
                    "source_session_id": source_session_id,
                    "title": task.get("selected_title"),
                    "status": "completed",
                }
            if task.get("status") not in ACTIVE_TASK_STATUSES:
                raise ConflictError("自动命名任务已经结束，不能再次提交标题。")

            source_session_dir = self._session_store.require_session_dir(
                project_id,
                source_session_id,
                for_write=True,
            )
            source_session = self._session_store.read_session(
                project_id,
                source_session_id,
            )
            if source_session is None:
                raise NotFoundError(
                    f"Conversation session '{source_session_id}' was not found."
                )
            if (
                source_session.title != DEFAULT_SESSION_TITLE
                or source_session.manual_title
            ):
                superseded = {
                    **task,
                    "status": "superseded",
                    "completed_at": _utc_now(),
                }
                _write_json_object(task_path, superseded)
                return {
                    "applied": False,
                    "source_session_id": source_session_id,
                    "title": source_session.title,
                    "status": "superseded",
                }

            normalized_title = _normalize_session_title(title)
            if normalized_title == DEFAULT_SESSION_TITLE:
                raise ConflictError("自动命名结果不能为空或仍为默认标题。")
            now = _utc_now()
            updated_session = replace(
                source_session,
                title=normalized_title,
                manual_title=False,
                updated_at=now,
            )
            completed_task = {
                **task,
                "status": "completed",
                "selected_title": normalized_title,
                "completed_at": now,
            }
            original_index = self._session_store.read_index(conversations_dir)
            try:
                self._session_store.write_session(
                    source_session_dir,
                    updated_session,
                )
                self._session_store.write_index(
                    conversations_dir,
                    self._session_store.index_with_session(
                        conversations_dir,
                        updated_session,
                        set_active=False,
                    ),
                )
                _write_json_object(task_path, completed_task)
            except Exception:
                self._session_store.write_session(
                    source_session_dir,
                    source_session,
                )
                self._session_store.write_index(
                    conversations_dir,
                    original_index,
                )
                _write_json_object(task_path, task)
                raise
            return {
                "applied": True,
                "source_session_id": source_session_id,
                "title": normalized_title,
                "status": "completed",
            }

    def settle_task(
        self,
        project_id: str,
        function_session_id: str,
        *,
        outcome: str,
    ) -> dict[str, Any]:
        conversations_dir = self._session_store.conversations_dir(
            project_id,
            for_write=True,
        )
        with conversation_write_lock(conversations_dir):
            function_session_dir = self._session_store.require_session_dir(
                project_id,
                function_session_id,
                for_write=True,
            )
            task_path = function_session_dir / AUTOMATIC_NAMING_TASK_FILE
            task = _read_json_object(task_path)
            if task is None or task.get("task_type") != FUNCTION_TYPE_AUTOMATIC_NAMING:
                raise ConflictError("当前会话不是自动命名任务会话。")
            if task.get("status") not in ACTIVE_TASK_STATUSES:
                return task

            failed_task = {
                **task,
                "status": "failed",
                "completed_at": _utc_now(),
                "failure": {
                    "outcome": outcome,
                    "reason": "automatic_title_not_submitted",
                },
            }
            _write_json_object(task_path, failed_task)
            return failed_task

    def _has_active_task(
        self,
        project_id: str,
        source_session_id: str,
        graph: dict,
    ) -> bool:
        conversations_dir = self._session_store.conversations_dir(project_id)
        index = self._session_store.read_index(conversations_dir)
        raw_states = index.get("session_states")
        session_states = raw_states if isinstance(raw_states, dict) else {}
        for node in self._branch_store.list_nodes(graph):
            if (
                node.parent_session_id != source_session_id
                or node.relation_kind != RELATION_KIND_FUNCTIONAL
                or node.function_type != FUNCTION_TYPE_AUTOMATIC_NAMING
                or node.deleted_at is not None
            ):
                continue
            task = _read_json_object(
                self._session_store.session_dir(
                    project_id,
                    node.session_id,
                ) / AUTOMATIC_NAMING_TASK_FILE
            )
            if task is None or task.get("status") not in ACTIVE_TASK_STATUSES:
                continue
            state = session_states.get(node.session_id)
            state_payload = state if isinstance(state, dict) else {}
            runtime_status = state_payload.get("runtime_status")
            draft = state_payload.get("draft")
            if runtime_status == "running" or (
                isinstance(draft, str) and draft.strip()
            ):
                return True

            task_path = self._session_store.session_dir(
                project_id,
                node.session_id,
            ) / AUTOMATIC_NAMING_TASK_FILE
            _write_json_object(
                task_path,
                {
                    **task,
                    "status": "failed",
                    "completed_at": _utc_now(),
                    "failure": {
                        "outcome": "error",
                        "reason": "orphaned_functional_run",
                    },
                },
            )
        return False


def _message_index(messages, message_id: str) -> int | None:
    return next(
        (
            index
            for index, message in enumerate(messages)
            if message.message_id == message_id
        ),
        None,
    )


def _read_json_object(path: Path) -> dict[str, Any] | None:
    return read_document(path.parent, path.stem)


def _write_json_object(path: Path, payload: dict[str, Any]) -> None:
    write_document(path.parent, path.stem, payload)


@lru_cache
def get_project_conversation_naming_repository(
) -> ProjectConversationNamingRepository:
    return ProjectConversationNamingRepository(get_project_repository())
