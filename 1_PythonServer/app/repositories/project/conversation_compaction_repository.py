from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import UTC, datetime
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
    ProjectConversationMessage,
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
    FUNCTION_TYPE_MEMORY_COMPACTION,
    RELATION_KIND_FUNCTIONAL,
    ConversationBranchStore,
)
from app.repositories.project.conversation_memory_repository import COMPRESSIONS_FILE
from app.repositories.project.conversation_serialization import (
    _new_session_id,
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
from app.repositories.project.conversation_database import (
    delete_document,
    read_document,
    read_events,
    replace_events,
    write_document,
)


COMPACTION_TASK_FILE = "memory_compaction_task.json"
MANUAL_COMPACTION_REQUEST_FILE = "memory_compaction_request.json"
COMPACTION_TASK_VERSION = 2
COMPACTION_SOURCE_TYPE = "conversation_context"
ACTIVE_TASK_STATUSES = {"pending", "running"}
STALE_TASK_GRACE_SECONDS = 300


@dataclass(frozen=True, slots=True)
class ConversationCompactionTaskCreation:
    session: ProjectConversationSession
    branch: ProjectConversationBranchNode
    task: dict[str, Any]


class ProjectConversationCompactionRepository:
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

    def is_memory_compaction_function_session(
        self,
        project_id: str,
        session_id: str,
    ) -> bool:
        conversations_dir = self._session_store.conversations_dir(project_id)
        self._session_store.require_session_dir(project_id, session_id)
        node = self._branch_store.node_for_session(
            self._branch_store.read_graph(conversations_dir),
            session_id,
        )
        return bool(
            node is not None
            and node.relation_kind == RELATION_KIND_FUNCTIONAL
            and node.function_type == FUNCTION_TYPE_MEMORY_COMPACTION
        )

    def request_manual_compaction(
        self,
        project_id: str,
        source_session_id: str,
        *,
        newly_covered_token_count: int,
        protected_tail_token_count: int,
    ) -> dict[str, Any]:
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
            request_path = source_session_dir / MANUAL_COMPACTION_REQUEST_FILE
            existing = _read_json_object(request_path)
            if existing is not None:
                return existing

            index = self._session_store.read_index(conversations_dir)
            records = _read_jsonl(source_session_dir / COMPRESSIONS_FILE)
            records, has_active_task = _recover_stale_tasks(
                records,
                conversations_dir=conversations_dir,
                session_store=self._session_store,
                now=_utc_now(),
            )
            _write_jsonl(source_session_dir / COMPRESSIONS_FILE, records)
            if has_active_task:
                raise ConflictError("当前会话已有记忆压缩任务正在处理。")

            request = {
                "request_id": f"mcr_{uuid4().hex[:16]}",
                "source_session_id": source_session_id,
                "status": "pending",
                "trigger_type": "manual_tool",
                "newly_covered_token_count": max(
                    0,
                    int(newly_covered_token_count),
                ),
                "protected_tail_token_count": max(
                    0,
                    int(protected_tail_token_count),
                ),
                "created_at": _utc_now(),
            }
            _write_json_object(request_path, request)
            return request

    def read_manual_compaction_request(
        self,
        project_id: str,
        source_session_id: str,
    ) -> dict[str, Any] | None:
        session_dir = self._session_store.require_session_dir(
            project_id,
            source_session_id,
        )
        return _read_json_object(
            session_dir / MANUAL_COMPACTION_REQUEST_FILE
        )

    def clear_manual_compaction_request(
        self,
        project_id: str,
        source_session_id: str,
        *,
        request_id: str,
    ) -> None:
        conversations_dir = self._session_store.conversations_dir(
            project_id,
            for_write=True,
        )
        with conversation_write_lock(conversations_dir):
            session_dir = self._session_store.require_session_dir(
                project_id,
                source_session_id,
                for_write=True,
            )
            request_path = session_dir / MANUAL_COMPACTION_REQUEST_FILE
            current = _read_json_object(request_path)
            if current is None or current.get("request_id") != request_id:
                return
            delete_document(session_dir, request_path.stem)

    def create_task(
        self,
        project_id: str,
        source_session_id: str,
        *,
        compression_id: str,
        source_boundary_message_id: str,
        snapshot_boundary_message_id: str,
        source_message_ids: tuple[str, ...],
        newly_covered_message_ids: tuple[str, ...],
        supersedes_compression_id: str | None,
        target_provider_id: str,
        target_model_id: str,
        target_reasoning_mode: str | None,
        target_settings: ProjectConversationSessionSettings,
        mode: str,
        trigger: dict[str, Any],
        configuration_fingerprint: str,
    ) -> ConversationCompactionTaskCreation:
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
            source_messages = self._message_store.list_messages(source_session_dir)
            snapshot_boundary_index = _message_index(
                source_messages,
                snapshot_boundary_message_id,
            )
            if snapshot_boundary_index is None:
                raise ConflictError("记忆压缩快照边界已不在来源会话中，任务未创建。")

            index = self._session_store.read_index(conversations_dir)
            source_records = _read_jsonl(source_session_dir / COMPRESSIONS_FILE)
            source_records, has_active_task = _recover_stale_tasks(
                source_records,
                conversations_dir=conversations_dir,
                session_store=self._session_store,
                now=_utc_now(),
            )
            if has_active_task:
                raise ConflictError("当前会话已有记忆压缩任务正在处理。")
            _write_jsonl(
                source_session_dir / COMPRESSIONS_FILE,
                source_records,
            )
            current_active_id = _latest_completed_compression_id(source_records)
            if current_active_id != supersedes_compression_id:
                raise ConflictError("来源会话的压缩边界已经变化，任务未创建。")

            original_graph = self._branch_store.read_graph(conversations_dir)
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
                function_type=FUNCTION_TYPE_MEMORY_COMPACTION,
            )
            copied_messages, message_id_map = copy_message_prefix(
                source_messages[: snapshot_boundary_index + 1],
                target_session_id=function_session_id,
            )
            function_source_message_ids = tuple(
                message_id_map[message.message_id]
                for message in source_messages[: snapshot_boundary_index + 1]
            )
            function_session = replace(
                source_session,
                session_id=function_session_id,
                sequence_number=self._session_store.next_sequence_number(conversations_dir),
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
            task = {
                "version": COMPACTION_TASK_VERSION,
                "task_type": FUNCTION_TYPE_MEMORY_COMPACTION,
                "compression_id": compression_id,
                "project_id": project_id,
                "source_session_id": source_session_id,
                "function_session_id": function_session_id,
                "source_boundary_message_id": source_boundary_message_id,
                "snapshot_boundary_message_id": snapshot_boundary_message_id,
                "source_message_ids": list(source_message_ids),
                "newly_covered_message_ids": list(newly_covered_message_ids),
                "function_source_message_ids": list(function_source_message_ids),
                "supersedes_compression_id": supersedes_compression_id,
                "mode": mode,
                "provider_id": target_provider_id,
                "model_id": target_model_id,
                "configuration_fingerprint": configuration_fingerprint,
                "status": "pending",
                "trigger": trigger,
                "created_at": now,
                "started_at": None,
                "completed_at": None,
                "failure": None,
            }
            pending_record = {
                "compression_id": compression_id,
                "status": "pending",
                "project_id": project_id,
                "session_id": source_session_id,
                "function_session_id": function_session_id,
                "source_type": COMPACTION_SOURCE_TYPE,
                "source_message_ids": list(source_message_ids),
                "newly_covered_message_ids": list(newly_covered_message_ids),
                "source_message_count": len(source_message_ids),
                "supersedes_compression_id": supersedes_compression_id,
                "trigger": trigger,
                "mode": mode,
                "provider_id": target_provider_id,
                "model_id": target_model_id,
                "configuration_fingerprint": configuration_fingerprint,
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
            records_written = False
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
                    temporary_dir / COMPACTION_TASK_FILE,
                    task,
                )
                atomic_replace_path(temporary_dir, target_session_dir)

                next_index = self._session_store.index_after_session_write(
                    conversations_dir,
                    function_session,
                    set_active=False,
                )
                self._session_store.write_index(conversations_dir, next_index)
                index_written = True
                self._branch_store.write_graph(conversations_dir, graph)
                graph_written = True
                _write_jsonl(
                    source_session_dir / COMPRESSIONS_FILE,
                    [*source_records, pending_record],
                )
                records_written = True
            except Exception:
                if temporary_dir.exists():
                    rmtree(temporary_dir, ignore_errors=True)
                if records_written:
                    _write_jsonl(
                        source_session_dir / COMPRESSIONS_FILE,
                        source_records,
                    )
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

            return ConversationCompactionTaskCreation(
                session=function_session,
                branch=branch,
                task=task,
            )

    def mark_task_running(
        self,
        project_id: str,
        function_session_id: str,
    ) -> dict[str, Any]:
        return self._update_task_status(
            project_id,
            function_session_id,
            status="running",
            started_at=_utc_now(),
        )

    def mark_task_failed(
        self,
        project_id: str,
        function_session_id: str,
        *,
        stage: str,
        reason: str,
        message: str,
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
            task_path = function_session_dir / COMPACTION_TASK_FILE
            original_task = _read_json_object(task_path)
            if original_task is None:
                raise NotFoundError("记忆压缩任务不存在。")
            if original_task.get("status") == "completed":
                return original_task
            failure = {
                "stage": stage,
                "reason": reason,
                "message": message,
            }
            task = {
                **original_task,
                "status": "failed",
                "completed_at": _utc_now(),
                "failure": failure,
            }
            source_session_id = _required_text(
                task.get("source_session_id"),
                "source_session_id",
            )
            source_session_dir = self._session_store.require_session_dir(
                project_id,
                source_session_id,
                for_write=True,
            )
            records = _read_jsonl(source_session_dir / COMPRESSIONS_FILE)
            next_records = _replace_record(
                records,
                str(task["compression_id"]),
                {
                    "status": "failed",
                    "completed_at": task["completed_at"],
                    "failure": failure,
                },
            )
            try:
                _write_json_object(task_path, task)
                _write_jsonl(
                    source_session_dir / COMPRESSIONS_FILE,
                    next_records,
                )
            except Exception:
                _write_json_object(task_path, original_task)
                _write_jsonl(
                    source_session_dir / COMPRESSIONS_FILE,
                    records,
                )
                raise
            return task

    def submit_result(
        self,
        project_id: str,
        function_session_id: str,
        *,
        result: dict[str, Any],
        token_measurements: tuple[int, str, int, str],
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
            graph = self._branch_store.read_graph(conversations_dir)
            node = self._branch_store.node_for_session(
                graph,
                function_session_id,
            )
            if (
                node is None
                or node.relation_kind != RELATION_KIND_FUNCTIONAL
                or node.function_type != FUNCTION_TYPE_MEMORY_COMPACTION
            ):
                raise ConflictError("当前会话不是记忆压缩功能会话。")
            task_path = function_session_dir / COMPACTION_TASK_FILE
            task = _read_json_object(task_path)
            if task is None:
                raise NotFoundError("记忆压缩任务不存在。")
            if task.get("status") == "completed":
                return task
            if task.get("status") not in ACTIVE_TASK_STATUSES:
                raise ConflictError("当前记忆压缩任务已经结束，不能再次提交。")

            source_session_id = _required_text(
                task.get("source_session_id"),
                "source_session_id",
            )
            source_session_dir = self._session_store.require_session_dir(
                project_id,
                source_session_id,
                for_write=True,
            )
            source_records = _read_jsonl(
                source_session_dir / COMPRESSIONS_FILE
            )
            current_active_id = _latest_completed_compression_id(
                source_records
            )
            if current_active_id != task.get("supersedes_compression_id"):
                raise ConflictError("来源会话已有更新的压缩结果，本次提交已失效。")

            source_tokens, source_token_source, compressed_tokens, compressed_token_source = (
                token_measurements
            )
            completed_at = _utc_now()
            completed_fields = {
                "status": "completed",
                "source_token_count": source_tokens,
                "source_token_source": source_token_source,
                "compressed_token_count": compressed_tokens,
                "compressed_token_source": compressed_token_source,
                "compression_ratio": _compression_ratio(
                    source_tokens,
                    compressed_tokens,
                ),
                "result": result,
                "completed_at": completed_at,
            }
            compression_id = _required_text(
                task.get("compression_id"),
                "compression_id",
            )
            next_source_records = _replace_record(
                source_records,
                compression_id,
                completed_fields,
            )
            function_records = _read_jsonl(
                function_session_dir / COMPRESSIONS_FILE
            )
            function_record = {
                **{
                    key: value
                    for key, value in _record_for_id(
                        source_records,
                        compression_id,
                    ).items()
                    if key not in {"session_id", "source_message_ids", "newly_covered_message_ids"}
                },
                **completed_fields,
                "compression_id": f"cmp_{uuid4().hex[:16]}",
                "session_id": function_session_id,
                "source_message_ids": list(
                    _string_list(task.get("function_source_message_ids"))
                ),
                "newly_covered_message_ids": list(
                    _string_list(task.get("function_source_message_ids"))
                ),
                "supersedes_compression_id": (
                    _latest_completed_compression_id(function_records)
                ),
                "inherited_from": {
                    "session_id": source_session_id,
                    "compression_id": compression_id,
                },
            }
            completed_task = {
                **task,
                "status": "completed",
                "completed_at": completed_at,
                "result": result,
                "failure": None,
            }
            try:
                _write_jsonl(
                    source_session_dir / COMPRESSIONS_FILE,
                    next_source_records,
                )
                _write_jsonl(
                    function_session_dir / COMPRESSIONS_FILE,
                    [*function_records, function_record],
                )
                _write_json_object(task_path, completed_task)
            except Exception:
                _write_jsonl(
                    source_session_dir / COMPRESSIONS_FILE,
                    source_records,
                )
                _write_jsonl(
                    function_session_dir / COMPRESSIONS_FILE,
                    function_records,
                )
                _write_json_object(task_path, task)
                raise
            return completed_task

    def read_task(
        self,
        project_id: str,
        function_session_id: str,
    ) -> dict[str, Any] | None:
        session_dir = self._session_store.require_session_dir(
            project_id,
            function_session_id,
        )
        return _read_json_object(session_dir / COMPACTION_TASK_FILE)

    def _update_task_status(
        self,
        project_id: str,
        function_session_id: str,
        *,
        status: str,
        started_at: str,
    ) -> dict[str, Any]:
        conversations_dir = self._session_store.conversations_dir(
            project_id,
            for_write=True,
        )
        with conversation_write_lock(conversations_dir):
            session_dir = self._session_store.require_session_dir(
                project_id,
                function_session_id,
                for_write=True,
            )
            task_path = session_dir / COMPACTION_TASK_FILE
            task = _read_json_object(task_path)
            if task is None:
                raise NotFoundError("记忆压缩任务不存在。")
            if task.get("status") not in ACTIVE_TASK_STATUSES:
                return task
            task = {
                **task,
                "status": status,
                "started_at": task.get("started_at") or started_at,
            }
            source_session_dir = self._session_store.require_session_dir(
                project_id,
                str(task["source_session_id"]),
                for_write=True,
            )
            records = _read_jsonl(source_session_dir / COMPRESSIONS_FILE)
            next_records = _replace_record(
                records,
                str(task["compression_id"]),
                {"status": status},
            )
            original_task = _read_json_object(task_path)
            try:
                _write_json_object(task_path, task)
                _write_jsonl(
                    source_session_dir / COMPRESSIONS_FILE,
                    next_records,
                )
            except Exception:
                if original_task is not None:
                    _write_json_object(task_path, original_task)
                _write_jsonl(
                    source_session_dir / COMPRESSIONS_FILE,
                    records,
                )
                raise
            return task


def _message_index(
    messages: tuple[ProjectConversationMessage, ...],
    message_id: str,
) -> int | None:
    return next(
        (
            index
            for index, message in enumerate(messages)
            if message.message_id == message_id
        ),
        None,
    )


def _recover_stale_tasks(
    records: list[dict[str, Any]],
    *,
    conversations_dir: Path,
    session_store: ConversationSessionStore,
    now: str,
) -> tuple[list[dict[str, Any]], bool]:
    active_remains = False
    recovered: list[dict[str, Any]] = []
    for record in records:
        if (
            record.get("source_type") != COMPACTION_SOURCE_TYPE
            or record.get("status") not in ACTIVE_TASK_STATUSES
        ):
            recovered.append(record)
            continue
        function_session_id = record.get("function_session_id")
        runtime_status = (
            session_store.read_session_state(
                conversations_dir,
                function_session_id,
            ).runtime_status
            if isinstance(function_session_id, str)
            else None
        )
        if runtime_status == "running" or not _task_is_older_than_grace(
            record.get("created_at"),
            now,
        ):
            active_remains = True
            recovered.append(record)
            continue

        failure = {
            "stage": "stale_task_recovery",
            "reason": "orphaned_task",
            "message": "记忆压缩任务已不再运行，系统已释放陈旧任务锁。",
        }
        recovered_record = {
            **record,
            "status": "failed",
            "completed_at": now,
            "failure": failure,
        }
        recovered.append(recovered_record)
        if isinstance(function_session_id, str):
            task_path = (
                conversations_dir
                / "sessions"
                / function_session_id
                / COMPACTION_TASK_FILE
            )
            task = _read_json_object(task_path)
            if task is not None and task.get("status") in ACTIVE_TASK_STATUSES:
                _write_json_object(
                    task_path,
                    {
                        **task,
                        "status": "failed",
                        "completed_at": now,
                        "failure": failure,
                    },
                )
    return recovered, active_remains


def _task_is_older_than_grace(created_at: object, now: str) -> bool:
    if not isinstance(created_at, str):
        return True
    try:
        created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        current = datetime.fromisoformat(now.replace("Z", "+00:00"))
    except ValueError:
        return True
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    return (current - created).total_seconds() >= STALE_TASK_GRACE_SECONDS


def _latest_completed_compression_id(
    records: list[dict[str, Any]],
) -> str | None:
    for record in reversed(records):
        if (
            record.get("source_type") == COMPACTION_SOURCE_TYPE
            and record.get("status") == "completed"
            and isinstance(record.get("compression_id"), str)
        ):
            return str(record["compression_id"])
    return None


def _replace_record(
    records: list[dict[str, Any]],
    compression_id: str,
    fields: dict[str, Any],
) -> list[dict[str, Any]]:
    changed = False
    updated: list[dict[str, Any]] = []
    for record in records:
        if record.get("compression_id") == compression_id:
            updated.append({**record, **fields})
            changed = True
        else:
            updated.append(record)
    if not changed:
        raise ConflictError("记忆压缩记录不存在，未写入结果。")
    return updated


def _record_for_id(
    records: list[dict[str, Any]],
    compression_id: str,
) -> dict[str, Any]:
    for record in records:
        if record.get("compression_id") == compression_id:
            return record
    raise ConflictError("记忆压缩记录不存在。")


def _compression_ratio(source_tokens: int, compressed_tokens: int) -> float | None:
    if source_tokens <= 0:
        return None
    return round(compressed_tokens / source_tokens * 100, 4)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return read_events(path.parent, path.stem)


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    replace_events(path.parent, path.stem, records)


def _read_json_object(path: Path) -> dict[str, Any] | None:
    return read_document(path.parent, path.stem)


def _write_json_object(path: Path, payload: dict[str, Any]) -> None:
    write_document(path.parent, path.stem, payload)


def _required_text(value: object, label: str) -> str:
    if isinstance(value, str) and value:
        return value
    raise ConflictError(f"记忆压缩任务缺少 {label}。")


def _string_list(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(
        item
        for item in value
        if isinstance(item, str) and item
    )


@lru_cache
def get_project_conversation_compaction_repository(
) -> ProjectConversationCompactionRepository:
    return ProjectConversationCompactionRepository(get_project_repository())
