from __future__ import annotations

from datetime import UTC, datetime
from functools import lru_cache
from gzip import compress as gzip_compress
from hashlib import sha256
from json import dumps
from pathlib import Path
from uuid import uuid4

from app.domain.llm.chat import ChatCompletionRequest
from app.domain.llm.chat_http_exchange import ChatHttpExchange, exchange_to_payload
from app.repositories.project.conversation_database import (
    append_journal_event,
    find_model_exchange_artifact_id,
    transaction_for_conversations,
    write_artifact_record,
)
from app.repositories.project.conversation_storage import (
    ProjectWorkspaceDirectoryResolver,
    conversation_write_lock,
)
from app.repositories.project.project_repository import (
    ProjectRepository,
    get_project_repository,
)


class ConversationAuditService:
    def __init__(self, projects: ProjectRepository) -> None:
        self._projects = projects
        self._workspace = ProjectWorkspaceDirectoryResolver()

    def record_http_exchange(
        self,
        request: ChatCompletionRequest,
        exchange: ChatHttpExchange,
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
        artifact_id = f"artifact_{uuid4().hex}"
        content = dumps(
            exchange_to_payload(exchange),
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        compressed_content = gzip_compress(content, mtime=0)
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
                    size_bytes=len(content),
                    sha256=sha256(content).hexdigest(),
                    status="complete",
                    created_at=created_at,
                    metadata={
                        "provider_id": request.provider_id,
                        "model_id": request.model_id,
                        "attempt_index": request.upstream_attempt_index,
                        "attempt_count": request.upstream_attempt_count,
                    },
                    payload_blob=compressed_content,
                    compression="gzip",
                    stored_size_bytes=len(compressed_content),
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
