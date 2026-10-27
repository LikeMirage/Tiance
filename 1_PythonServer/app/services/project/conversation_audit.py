from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from gzip import compress as gzip_compress
from json import dumps
import logging
from pathlib import Path
from typing import Any, Coroutine
from uuid import uuid4

from app.domain.llm.chat import ChatCompletionRequest
from app.core.shutdown_tasks import finish_thread
from app.domain.llm.chat_http_exchange import ChatHttpExchange, exchange_payload
from app.domain.llm.response_body import body_size
from app.repositories.project.conversation_database import (
    append_journal_event,
    complete_artifact_record,
    fail_artifact_record,
    find_model_exchange_artifact_id,
    transaction_for_conversations,
    write_artifact_record,
)
from app.repositories.project.conversation_audit_snapshots import (
    store_prepared_audit_snapshot,
)
from app.repositories.project.conversation_audit_streaming import prepare_audit_snapshot, response_text
from app.repositories.project.conversation_storage import (
    ProjectWorkspaceDirectoryResolver,
    conversation_write_lock,
)
from app.repositories.project.project_repository import (
    ProjectRepository,
    get_project_repository,
)


logger = logging.getLogger(__name__)
_AuditTaskKey = tuple[str, str]


@dataclass(slots=True)
class _HttpExchangeWrite:
    workspace: Path
    conversations: Path
    request: ChatCompletionRequest
    exchange: ChatHttpExchange
    artifact_id: str
    metadata: dict[str, Any]
    begun: bool = False


class ConversationAuditService:
    def __init__(self, projects: ProjectRepository) -> None:
        self._projects = projects
        self._workspace = ProjectWorkspaceDirectoryResolver()
        self._tasks: dict[_AuditTaskKey, set[asyncio.Task[Any]]] = {}
        self._write_slots = asyncio.Semaphore(2)
        self._failed_http_exchanges: dict[str, _HttpExchangeWrite] = {}

    async def record_http_exchange(
        self,
        request: ChatCompletionRequest,
        exchange: ChatHttpExchange,
    ) -> None:
        target = self._resolve_target(request)
        if target is None:
            return
        workspace_dir, conversations_dir = target
        artifact_id = f"artifact_{uuid4().hex}"
        metadata = self._exchange_metadata(request)
        if not isinstance(exchange.response_body, bytes):
            exchange.response_body.retain()
        job = _HttpExchangeWrite(workspace_dir, conversations_dir, request, exchange, artifact_id, metadata)
        try:
            await finish_thread(self._begin_http_exchange, workspace_dir, conversations_dir, request, artifact_id, metadata)
            job.begun = True
        except BaseException:
            self._failed_http_exchanges[artifact_id] = job
            raise
        self._schedule_http_exchange(job)

    def _schedule_http_exchange(self, job: _HttpExchangeWrite) -> None:
        task = asyncio.create_task(self._save_http_exchange(job), name="conversation-http-audit")
        self._track_task(job.request.project_id, job.request.session_id, task)

    async def _save_http_exchange(self, job: _HttpExchangeWrite) -> None:
        try:
            async with self._write_slots:
                await finish_thread(self._write_http_exchange, job)
        except BaseException:
            # Retain the source for an exit retry after e.g. a disk error.
            job.begun = False
            self._failed_http_exchanges[job.artifact_id] = job
            raise
        else:
            if not isinstance(job.exchange.response_body, bytes):
                job.exchange.response_body.release()

    def _write_http_exchange(self, job: _HttpExchangeWrite) -> None:
        if not job.begun:
            if not self._begin_http_exchange(job.workspace, job.conversations, job.request, job.artifact_id, job.metadata):
                return
            job.begun = True
        self._complete_http_exchange(job.workspace, job.conversations, job.request,
                                     job.exchange, job.artifact_id, job.metadata)

    def create_session_task(
        self,
        project_id: str,
        session_id: str,
        coroutine: Coroutine[Any, Any, Any],
        *,
        name: str,
    ) -> asyncio.Task[Any]:
        task = asyncio.create_task(coroutine, name=name)
        self._track_task(project_id, session_id, task)
        return task

    async def wait_session(self, project_id: str, session_id: str) -> None:
        tasks = tuple(self._tasks.get((project_id, session_id), ()))
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def close(self) -> None:
        retries = tuple(self._failed_http_exchanges.values())
        self._failed_http_exchanges.clear()
        for job in retries:
            self._schedule_http_exchange(job)
        # Producers must be stopped first. Re-check tasks registered by the final
        # cancellation handlers instead of draining a single stale snapshot.
        while tasks := tuple(task for values in self._tasks.values() for task in values):
            await asyncio.gather(*(asyncio.shield(task) for task in tasks), return_exceptions=True)
        if self._failed_http_exchanges:
            raise RuntimeError("原始响应记录保存失败，请检查磁盘后重试退出。")

    def _begin_http_exchange(
        self,
        workspace_dir: Path,
        conversations_dir: Path,
        request: ChatCompletionRequest,
        artifact_id: str,
        metadata: dict[str, Any],
    ) -> bool:
        created_at = datetime.now(UTC).isoformat()
        with conversation_write_lock(conversations_dir):
            with transaction_for_conversations(conversations_dir) as connection:
                existing = connection.execute(
                    "SELECT status FROM conversation_artifacts WHERE artifact_id = ?", (artifact_id,),
                ).fetchone()
                if existing is not None:
                    if existing[0] == "complete":
                        return False
                    connection.execute("UPDATE conversation_artifacts SET status = 'pending' WHERE artifact_id = ?", (artifact_id,))
                    return True
                write_artifact_record(
                    workspace_dir,
                    artifact_id=artifact_id,
                    session_id=request.session_id,
                    kind="model_http_exchange",
                    relative_path=(
                        f"conversations/sessions/{request.session_id}/"
                        "model_http_exchanges.jsonl"
                    ),
                    media_type="application/json",
                    encoding="utf-8",
                    size_bytes=0,
                    sha256="",
                    status="pending",
                    created_at=created_at,
                    metadata=metadata,
                )
                append_journal_event(
                    workspace_dir,
                    session_id=request.session_id,
                    run_id=request.run_id,
                    turn_id=request.user_message_id,
                    tool_call_id=None,
                    event_type="model.http_exchange.pending",
                    occurred_at=created_at,
                    payload={
                        "provider_id": request.provider_id,
                        "model_id": request.model_id,
                        "attempt_index": request.upstream_attempt_index,
                        "attempt_count": request.upstream_attempt_count,
                    },
                    artifact_id=artifact_id,
                )
        return True

    def _complete_http_exchange(
        self,
        workspace_dir: Path,
        conversations_dir: Path,
        request: ChatCompletionRequest,
        exchange: ChatHttpExchange,
        artifact_id: str,
        metadata: dict[str, Any],
    ) -> None:
        try:
            encoding, text = response_text(exchange.response_body)
            payload = exchange_payload(exchange, {"encoding": encoding, "content": text})
            completed_metadata = {
                **metadata,
                "storage": "incremental_audit_manifest_v2",
            }
            with prepare_audit_snapshot(payload) as prepared:
                with conversation_write_lock(conversations_dir):
                    with transaction_for_conversations(conversations_dir) as connection:
                        manifest = store_prepared_audit_snapshot(
                            connection, request.session_id, "model_http_exchange", prepared,
                        )
                        compressed_content = gzip_compress(
                            dumps(manifest, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
                            mtime=0,
                        )
                        complete_artifact_record(
                            workspace_dir,
                            artifact_id=artifact_id,
                            size_bytes=prepared.size_bytes,
                            sha256=prepared.digest,
                            metadata=completed_metadata,
                            payload_blob=compressed_content,
                            compression="gzip+audit-manifest-v2",
                        )
                        append_journal_event(
                            workspace_dir,
                            session_id=request.session_id,
                            run_id=request.run_id,
                            turn_id=request.user_message_id,
                            tool_call_id=None,
                            event_type=(
                                "model.http_exchange.failed"
                                if exchange.error_type is not None
                                else "model.http_exchange.completed"
                            ),
                            occurred_at=exchange.completed_at,
                            payload={
                                "provider_id": request.provider_id,
                                "model_id": request.model_id,
                                "status": exchange.response_status,
                                "response_bytes": body_size(exchange.response_body),
                                "attempt_index": request.upstream_attempt_index,
                                "attempt_count": request.upstream_attempt_count,
                            },
                            artifact_id=artifact_id,
                        )
        except Exception as error:
            logger.exception("Failed to persist a complete model HTTP exchange audit.")
            failed_metadata = {
                **metadata,
                "audit_error_type": type(error).__name__,
                "audit_error_message": str(error),
            }
            try:
                with conversation_write_lock(conversations_dir):
                    with transaction_for_conversations(conversations_dir):
                        fail_artifact_record(
                            workspace_dir,
                            artifact_id=artifact_id,
                            metadata=failed_metadata,
                        )
                        append_journal_event(
                            workspace_dir,
                            session_id=request.session_id,
                            run_id=request.run_id,
                            turn_id=request.user_message_id,
                            tool_call_id=None,
                            event_type="model.http_exchange.audit_failed",
                            occurred_at=datetime.now(UTC).isoformat(),
                            payload={
                                "attempt_index": request.upstream_attempt_index,
                                "attempt_count": request.upstream_attempt_count,
                                "error_type": type(error).__name__,
                                "error_message": str(error),
                            },
                            artifact_id=artifact_id,
                        )
            except Exception:
                logger.exception("Failed to record the HTTP exchange audit failure.")
            raise

    def _resolve_target(
        self,
        request: ChatCompletionRequest,
    ) -> tuple[Path, Path] | None:
        if not request.project_id or not request.session_id:
            return None
        project = self._projects.get_project(request.project_id)
        if project is None:
            return None
        workspace_dir = self._workspace.resolve_workspace_dir(
            Path(project.root_path),
            for_write=True,
        )
        return workspace_dir, workspace_dir / "conversations"

    @staticmethod
    def _exchange_metadata(request: ChatCompletionRequest) -> dict[str, Any]:
        return {
            "provider_id": request.provider_id,
            "model_id": request.model_id,
            "attempt_index": request.upstream_attempt_index,
            "attempt_count": request.upstream_attempt_count,
        }

    def _track_task(
        self,
        project_id: str,
        session_id: str,
        task: asyncio.Task[Any],
    ) -> None:
        key = (project_id, session_id)
        self._tasks.setdefault(key, set()).add(task)
        task.add_done_callback(lambda completed: self._finish_task(key, completed))

    def _finish_task(self, key: _AuditTaskKey, task: asyncio.Task[Any]) -> None:
        tasks = self._tasks.get(key)
        if tasks is not None:
            tasks.discard(task)
            if not tasks:
                self._tasks.pop(key, None)
        try:
            task.result()
        except asyncio.CancelledError:
            logger.error("A conversation audit task was cancelled before completion.")
        except Exception:
            logger.exception("A conversation audit task failed.")

    def record_attempt_outcome(
        self,
        request: ChatCompletionRequest,
        *,
        status: str,
        error_code: str | None,
        error_message: str | None,
    ) -> None:
        self.record_event(
            request,
            event_type=f"model.request_attempt.{status}",
            payload={
                "provider_id": request.provider_id,
                "model_id": request.model_id,
                "attempt_index": request.upstream_attempt_index,
                "attempt_count": request.upstream_attempt_count,
                "error_code": error_code,
                "error_message": error_message,
            },
            attach_model_exchange=status == "failed",
        )

    def record_event(
        self,
        request: ChatCompletionRequest,
        *,
        event_type: str,
        payload: dict[str, object],
        tool_call_id: str | None = None,
        occurred_at: str | None = None,
        attach_model_exchange: bool = False,
    ) -> None:
        if not request.project_id or not request.session_id:
            return
        project = self._projects.get_project(request.project_id)
        if project is None:
            return
        workspace_dir = self._workspace.resolve_workspace_dir(
            Path(project.root_path),
            for_write=True,
        )
        conversations_dir = workspace_dir / "conversations"
        with conversation_write_lock(conversations_dir):
            artifact_id = (
                find_model_exchange_artifact_id(
                    workspace_dir,
                    session_id=request.session_id,
                    run_id=request.run_id,
                    attempt_index=request.upstream_attempt_index,
                )
                if attach_model_exchange and request.run_id
                else None
            )
            append_journal_event(
                workspace_dir,
                session_id=request.session_id,
                run_id=request.run_id,
                turn_id=request.user_message_id,
                tool_call_id=tool_call_id,
                event_type=event_type,
                occurred_at=occurred_at or datetime.now(UTC).isoformat(),
                payload=payload,
                artifact_id=artifact_id,
            )


@lru_cache
def get_conversation_audit_service() -> ConversationAuditService:
    return ConversationAuditService(get_project_repository())
