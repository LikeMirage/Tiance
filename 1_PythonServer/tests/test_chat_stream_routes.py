import asyncio

import pytest

from app.api.routes.llm import chat as chat_routes
from app.core.errors import NotFoundError
from app.schemas.llm.chat import ChatStreamStopRequestBody
from app.services.project.project_conversations import ProjectConversationService


class _MissingRunManager:
    async def subscribe(
        self,
        project_id: str,
        session_id: str,
        checkpoint_message_id: str | None = None,
    ):
        raise NotFoundError("当前会话没有正在运行的生成任务。")


class _StoppedRunManager:
    async def stop(self, project_id: str, session_id: str) -> bool:
        return False


class _ConversationService:
    def __init__(self) -> None:
        self.runtime_statuses: list[tuple[str, str, str]] = []

    def save_session_runtime_status(
        self,
        project_id: str,
        session_id: str,
        runtime_status: str,
    ) -> None:
        self.runtime_statuses.append((project_id, session_id, runtime_status))

    def reconcile_missing_run_runtime_status(
        self,
        project_id: str,
        session_id: str,
    ) -> None:
        self.runtime_statuses.append((project_id, session_id, "idle"))


def test_missing_active_stream_reconciles_persisted_runtime_status(monkeypatch):
    conversation_service = _ConversationService()
    monkeypatch.setattr(chat_routes, "get_conversation_run_manager", lambda: _MissingRunManager())
    monkeypatch.setattr(
        chat_routes,
        "get_project_conversation_service",
        lambda: conversation_service,
    )

    with pytest.raises(NotFoundError):
        asyncio.run(chat_routes.subscribe_active_chat_completion_stream("project-1", "session-1"))

    assert conversation_service.runtime_statuses == [
        ("project-1", "session-1", "idle"),
    ]


def test_stopping_missing_run_also_reconciles_persisted_runtime_status(monkeypatch):
    conversation_service = _ConversationService()
    monkeypatch.setattr(chat_routes, "get_conversation_run_manager", lambda: _StoppedRunManager())
    monkeypatch.setattr(
        chat_routes,
        "get_project_conversation_service",
        lambda: conversation_service,
    )
    payload = ChatStreamStopRequestBody(project_id="project-1", session_id="session-1")

    response = asyncio.run(chat_routes.stop_chat_completion_stream(payload))

    assert response.stopped is False
    assert conversation_service.runtime_statuses == [
        ("project-1", "session-1", "idle"),
    ]


def test_missing_run_reconciliation_preserves_existing_error_status():
    repository = _RuntimeStateRepository("error")
    service = ProjectConversationService(repository)

    service.reconcile_missing_run_runtime_status("project-1", "session-1")

    assert repository.saved_statuses == []


def test_missing_run_reconciliation_clears_only_stale_running_status():
    repository = _RuntimeStateRepository("running")
    service = ProjectConversationService(repository)

    service.reconcile_missing_run_runtime_status("project-1", "session-1")

    assert repository.saved_statuses == [
        ("project-1", "session-1", "idle"),
    ]


class _RuntimeStateRepository:
    def __init__(self, runtime_status: str) -> None:
        self.runtime_status = runtime_status
        self.saved_statuses: list[tuple[str, str, str]] = []

    def get_state(self, project_id: str):
        state = type("RuntimeState", (), {"runtime_status": self.runtime_status})()
        return "AI", "session-1", {"session-1": state}

    def save_session_runtime_status(
        self,
        project_id: str,
        session_id: str,
        runtime_status: str,
    ) -> None:
        self.saved_statuses.append((project_id, session_id, runtime_status))
