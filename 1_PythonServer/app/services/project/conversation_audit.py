from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from functools import lru_cache
from gzip import compress as gzip_compress
from hashlib import sha256
from json import dumps
import logging
from pathlib import Path
from typing import Any, Coroutine
from uuid import uuid4

from app.domain.llm.chat import ChatCompletionRequest
from app.domain.llm.chat_http_exchange import ChatHttpExchange, exchange_to_payload
from app.repositories.project.conversation_database import (
    append_journal_event,
    complete_artifact_record,
    fail_artifact_record,
    find_model_exchange_artifact_id,
    transaction_for_conversations,
    write_artifact_record,
)
from app.repositories.project.conversation_audit_payloads import (
    externalize_audit_payload,
)
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


class ConversationAuditService:
    def __init__(self, projects: ProjectRepository) -> None:
        self._projects = projects
        self._workspace = ProjectWorkspaceDirectoryResolver()
        self._tasks: dict[_AuditTaskKey, set[asyncio.Task[Any]]] = {}

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
        await asyncio.to_thread(
            self._begin_http_exchange,
            workspace_dir,
            conversations_dir,
            request,
            artifact_id,
            metadata,
        )
        task = asyncio.create_task(
            asyncio.to_thread(
                self._complete_http_exchange,
                workspace_dir,
                conversations_dir,
                request,
                exchange,
                artifact_id,
                metadata,
            ),
            name="conversation-http-audit",
        )
        self._track_task(request.project_id, request.session_id, task)

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
        tasks = tuple(task for values in self._tasks.values() for task in values)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def _begin_http_exchange(
        self,
        workspace_dir: Path,
        conversations_dir: Path,
        request: ChatCompletionRequest,
        artifact_id: str,
        metadata: dict[str, Any],
    ) -> None:
        created_at = datetime.now(UTC).isoformat()
        with conversation_write_lock(conversations_dir):
            with transaction_for_conversations(conversations_dir):
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
            payload = exchange_to_payload(exchange)
            content = dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
            manifest = externalize_audit_payload(workspace_dir, payload)
            stored_content = dumps(
                manifest,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
            compressed_content = gzip_compress(stored_content, mtime=0)
            completed_metadata = {
                **metadata,
                "storage": "content_addressed_audit_manifest_v1",
            }
            with conversation_write_lock(conversations_dir):
                with transaction_for_conversations(conversations_dir):
                    complete_artifact_record(
                        workspace_dir,
                        artifact_id=artifact_id,
                        size_bytes=len(content),
                        sha256=sha256(content).hexdigest(),
                        metadata=completed_metadata,
                        payload_blob=compressed_content,
                        compression="gzip+audit-manifest-v1",
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
                            "response_bytes": len(exchange.response_body),
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
