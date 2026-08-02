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
)
from app.repositories.project.conversation_branch_copy import (
    GLOBAL_MEMORY_MANAGEMENT_STATE_FILE,
    PROJECT_MEMORY_MANAGEMENT_STATE_FILE,
    copy_message_prefix,
    write_inherited_compressions,
    write_inherited_long_term_memory_state,
    write_inherited_memory_delivery_state,
)
from app.repositories.project.conversation_branch_store import (
    CREATED_BY_SYSTEM,
    FUNCTION_TYPE_GLOBAL_MEMORY_MANAGEMENT,
    FUNCTION_TYPE_PROJECT_MEMORY_MANAGEMENT,
    RELATION_KIND_FUNCTIONAL,
    ConversationBranchStore,
)
from app.repositories.project.conversation_serialization import (
    _new_session_id,
    _next_session_sequence_number,
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


LONG_TERM_MEMORY_TASK_FILE = "long_term_memory_task.json"
LONG_TERM_MEMORY_TASK_VERSION = 1
LONG_TERM_MEMORY_STATE_VERSION = 1
ACTIVE_TASK_STATUSES = {"pending", "running"}


@dataclass(frozen=True, slots=True)
class LongTermMemoryRepositoryDefinition:
    function_type: str
    label: str
    scope: str
    state_file: str


PROJECT_MEMORY_REPOSITORY_DEFINITION = LongTermMemoryRepositoryDefinition(
    function_type=FUNCTION_TYPE_PROJECT_MEMORY_MANAGEMENT,
    label="项目记忆管理",
    scope="project",
    state_file=PROJECT_MEMORY_MANAGEMENT_STATE_FILE,
)
GLOBAL_MEMORY_REPOSITORY_DEFINITION = LongTermMemoryRepositoryDefinition(
    function_type=FUNCTION_TYPE_GLOBAL_MEMORY_MANAGEMENT,
    label="全局记忆管理",
    scope="global",
    state_file=GLOBAL_MEMORY_MANAGEMENT_STATE_FILE,
)
MEMORY_MANAGEMENT_FUNCTION_TYPES = {
    definition.function_type
    for definition in (
        PROJECT_MEMORY_REPOSITORY_DEFINITION,
        GLOBAL_MEMORY_REPOSITORY_DEFINITION,
    )
}


@dataclass(frozen=True, slots=True)
class LongTermMemoryTaskCreation:
    branch: ProjectConversationBranchNode
    session: ProjectConversationSession
    task: dict[str, Any]


class ProjectConversationLongTermMemoryRepository:
    def __init__(
        self,
        project_repository: ProjectRepository,
        definition: LongTermMemoryRepositoryDefinition,
        *,
        state_store: ConversationStateStore | None = None,
        session_store: ConversationSessionStore | None = None,
        message_store: ConversationMessageStore | None = None,
        branch_store: ConversationBranchStore | None = None,
    ) -> None:
        self.definition = definition
        state = state_store or ConversationStateStore()
        self._session_store = session_store or ConversationSessionStore(
            project_repository,
            state_store=state,
        )
        self._message_store = message_store or ConversationMessageStore()
        self._branch_store = branch_store or ConversationBranchStore()

    def read_state(
        self,
        project_id: str,
        session_id: str,
    ) -> dict[str, Any] | None:
        session_dir = self._session_store.require_session_dir(
            project_id,
            session_id,
        )
        return _read_json_object(session_dir / self.definition.state_file)

    def is_long_term_memory_function_session(
        self,
        project_id: str,
        session_id: str,
    ) -> bool:
        conversations_dir = self._session_store.conversations_dir(project_id)
        graph = self._branch_store.read_graph(conversations_dir)
        node = self._branch_store.node_for_session(graph, session_id)
        return bool(
            node is not None
            and node.relation_kind == RELATION_KIND_FUNCTIONAL
            and node.function_type in MEMORY_MANAGEMENT_FUNCTION_TYPES
            and node.deleted_at is None
        )

    def create_task(
        self,
        project_id: str,
        source_session_id: str,
        *,
        task_id: str,
        previous_boundary_message_id: str | None,
        snapshot_boundary_message_id: str,
        newly_covered_message_ids: tuple[str, ...],
        target_provider_id: str,
        target_model_id: str,
        target_reasoning_mode: str | None,
        target_settings: ProjectConversationSessionSettings,
        mode: str,
        trigger: dict[str, Any],
        attempt_index: int,
        retry_of: str | None,
    ) -> LongTermMemoryTaskCreation:
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
            current_state = _read_json_object(
                source_session_dir / self.definition.state_file
            )
            current_boundary = (
                current_state.get("last_completed_boundary_message_id")
                if current_state is not None
                else None
            )
            if current_boundary != previous_boundary_message_id:
                raise ConflictError(
                    f"{self.definition.label}边界已经变化，任务未创建。"
                )

            original_graph = self._branch_store.read_graph(conversations_dir)
            if self._has_active_task(
                project_id,
                source_session_id,
                original_graph,
            ):
                raise ConflictError(
                    f"当前会话已有{self.definition.label}任务正在处理。"
                )

            source_messages = self._message_store.list_messages(source_session_dir)
            boundary_index = _message_index(
                source_messages,
                snapshot_boundary_message_id,
            )
            if boundary_index is None:
                raise ConflictError(
                    f"{self.definition.label}快照边界已不在来源会话中。"
                )

            graph = deepcopy(original_graph)
            index = self._session_store.read_index(conversations_dir)
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
                function_type=self.definition.function_type,
            )
            copied_messages, message_id_map = copy_message_prefix(
                source_messages[: boundary_index + 1],
                target_session_id=function_session_id,
            )
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
                settings=target_settings,
            )
            task = {
                "version": LONG_TERM_MEMORY_TASK_VERSION,
                "task_type": self.definition.function_type,
                "memory_scope": self.definition.scope,
                "task_id": task_id,
                "project_id": project_id,
                "source_session_id": source_session_id,
                "function_session_id": function_session_id,
                "previous_boundary_message_id": previous_boundary_message_id,
                "snapshot_boundary_message_id": snapshot_boundary_message_id,
                "newly_covered_message_ids": list(newly_covered_message_ids),
                "mode": mode,
                "provider_id": target_provider_id,
                "model_id": target_model_id,
                "attempt_index": attempt_index,
                "retry_of": retry_of,
                "status": "pending",
                "trigger": trigger,
                "created_at": now,
                "started_at": None,
                "completed_at": None,
                "failure": None,
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
                write_inherited_compressions(
                    source_session_dir,
                    temporary_dir,
                    target_session_id=function_session_id,
                    message_id_map=message_id_map,
                )
                write_inherited_long_term_memory_state(
                    source_session_dir,
                    temporary_dir,
                    target_session_id=function_session_id,
                    message_id_map=message_id_map,
                )
                write_inherited_memory_delivery_state(
                    source_session_dir,
                    temporary_dir,
                    message_id_map=message_id_map,
                )
                _write_json_object(
                    temporary_dir / LONG_TERM_MEMORY_TASK_FILE,
                    task,
                )
                atomic_replace_path(temporary_dir, target_session_dir)

                next_index = self._session_store.index_with_session(
                    conversations_dir,
                    function_session,
                    set_active=False,
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
            return LongTermMemoryTaskCreation(
                branch=branch,
                session=function_session,
                task=task,
            )

    def mark_task_running(
        self,
        project_id: str,
        function_session_id: str,
    ) -> dict[str, Any]:
        return self._update_task(
            project_id,
            function_session_id,
            lambda task: {
                **task,
                "status": "running",
                "started_at": task.get("started_at") or _utc_now(),
            },
        )

    def mark_task_completed(
        self,
        project_id: str,
        function_session_id: str,
    ) -> dict[str, Any]:
        conversations_dir = self._session_store.conversations_dir(
            project_id,
            for_write=True,
        )
        with conversation_write_lock(conversations_dir):
            task_path = self._task_path(project_id, function_session_id)
            task = _require_task(task_path, self.definition.function_type)
            if task.get("status") == "completed":
                return task
            if task.get("status") not in ACTIVE_TASK_STATUSES:
                raise ConflictError(f"{self.definition.label}任务已经结束。")

            source_session_id = str(task.get("source_session_id") or "")
            source_session_dir = self._session_store.require_session_dir(
                project_id,
                source_session_id,
                for_write=True,
            )
            state_path = source_session_dir / self.definition.state_file
            current_state = _read_json_object(state_path)
            current_boundary = (
                current_state.get("last_completed_boundary_message_id")
                if current_state is not None
                else None
            )
            if current_boundary != task.get("previous_boundary_message_id"):
                raise ConflictError(
                    f"{self.definition.label}结果已经过期，未推进处理边界。"
                )

            completed_at = _utc_now()
            completed_task = {
                **task,
                "status": "completed",
                "completed_at": completed_at,
                "failure": None,
            }
            state = {
                "version": LONG_TERM_MEMORY_STATE_VERSION,
                "session_id": source_session_id,
                "last_completed_task_id": task.get("task_id"),
                "last_completed_boundary_message_id": task.get(
                    "snapshot_boundary_message_id"
                ),
                "updated_at": completed_at,
            }
            _write_json_object(task_path, completed_task)
            _write_json_object(state_path, state)
            return completed_task

    def mark_task_failed(
        self,
        project_id: str,
        function_session_id: str,
        *,
        reason: str,
        message: str,
    ) -> dict[str, Any]:
        return self._update_task(
            project_id,
            function_session_id,
            lambda task: {
                **task,
                "status": "failed",
                "completed_at": _utc_now(),
                "failure": {
                    "reason": reason,
                    "message": message,
                },
            },
        )

    def read_task(
        self,
        project_id: str,
        function_session_id: str,
    ) -> dict[str, Any] | None:
        return _read_json_object(
            self._task_path(project_id, function_session_id)
        )

    def _update_task(
        self,
        project_id: str,
        function_session_id: str,
        update,
    ) -> dict[str, Any]:
        conversations_dir = self._session_store.conversations_dir(
            project_id,
            for_write=True,
        )
        with conversation_write_lock(conversations_dir):
            task_path = self._task_path(project_id, function_session_id)
            task = _require_task(task_path, self.definition.function_type)
            updated = update(task)
            _write_json_object(task_path, updated)
            return updated

    def _task_path(self, project_id: str, function_session_id: str) -> Path:
        return (
            self._session_store.require_session_dir(
                project_id,
                function_session_id,
                for_write=True,
            )
            / LONG_TERM_MEMORY_TASK_FILE
        )

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
                or node.function_type != self.definition.function_type
                or node.deleted_at is not None
            ):
                continue
            task_path = (
                self._session_store.session_dir(project_id, node.session_id)
                / LONG_TERM_MEMORY_TASK_FILE
            )
            task = _read_json_object(task_path)
            if task is None or task.get("status") not in ACTIVE_TASK_STATUSES:
                continue
            state = session_states.get(node.session_id)
            state_payload = state if isinstance(state, dict) else {}
            runtime_status = state_payload.get("runtime_status")
            if runtime_status == "running":
                return True
            failed = {
                **task,
                "status": "failed",
                "completed_at": _utc_now(),
                "failure": {
                    "reason": "orphaned_functional_run",
                    "message": f"{self.definition.label}功能会话未处于运行状态。",
                },
            }
            _write_json_object(task_path, failed)
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


def _require_task(path: Path, function_type: str) -> dict[str, Any]:
    task = _read_json_object(path)
    if (
        task is None
        or task.get("task_type") != function_type
    ):
        raise ConflictError("当前会话不是对应的记忆管理任务会话。")
    return task


def _read_json_object(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    payload = loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Invalid JSON object in {path.name}.")
    return payload


def _write_json_object(path: Path, payload: dict[str, Any]) -> None:
    atomic_write_text(
        path,
        f"{dumps(payload, ensure_ascii=False, indent=2)}\n",
    )


@lru_cache
def get_project_conversation_long_term_memory_repository(
    scope: str = "project",
) -> ProjectConversationLongTermMemoryRepository:
    definitions = {
        "project": PROJECT_MEMORY_REPOSITORY_DEFINITION,
        "global": GLOBAL_MEMORY_REPOSITORY_DEFINITION,
    }
    if scope not in definitions:
        raise ValueError(f"Unsupported memory management scope: {scope}")
    return ProjectConversationLongTermMemoryRepository(
        get_project_repository(),
        definitions[scope],
    )
