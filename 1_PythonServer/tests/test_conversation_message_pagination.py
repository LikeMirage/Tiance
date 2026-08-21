from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes.project import conversations as conversation_routes
from app.core.errors import BadRequestError, register_exception_handlers
from app.domain.project import Project
from app.repositories.project.conversation_repository import ProjectConversationRepository
from app.repositories.project.conversation_database import append_journal_event
from app.services.project.project_conversations import ProjectConversationService


PROJECT_ID = "00000000-0000-0000-0000-000000000987"


class FakeProjectRepository:
    def __init__(self, root_path: str) -> None:
        now = datetime.now(UTC).isoformat()
        self.project = Project(
            project_id=PROJECT_ID,
            name="pagination-test",
            root_path=root_path,
            is_default=False,
            sort_order=0,
            created_at=now,
            updated_at=now,
        )

    def get_project(self, project_id: str) -> Project | None:
        return self.project if project_id == PROJECT_ID else None


def test_repository_rejects_unknown_before_message_id(tmp_path):
    repository, session_id = _repository_with_message(tmp_path)

    with pytest.raises(BadRequestError) as error:
        repository.list_messages_page(
            PROJECT_ID,
            session_id,
            limit=20,
            before_message_id="missing-message-id",
        )

    assert error.value.code == "bad_request"
    assert error.value.details == {"parameter": "before_message_id"}


def test_messages_api_returns_stable_parameter_error_for_unknown_cursor(
    monkeypatch,
    tmp_path,
):
    repository, session_id = _repository_with_message(tmp_path)
    service = ProjectConversationService(repository)
    monkeypatch.setattr(
        conversation_routes,
        "get_project_conversation_service",
        lambda: service,
    )
    application = FastAPI()
    register_exception_handlers(application)
    application.include_router(conversation_routes.router)

    response = TestClient(application).get(
        f"/projects/{PROJECT_ID}/conversations/{session_id}/messages",
        params={"limit": 20, "before_message_id": "missing-message-id"},
    )

    assert response.status_code == 400
    assert response.json() == {
        "detail": "before_message_id does not reference a message in this conversation.",
        "error": {
            "code": "bad_request",
            "message": "before_message_id does not reference a message in this conversation.",
            "details": {"parameter": "before_message_id"},
        },
    }


def test_messages_api_returns_durable_run_outcomes(monkeypatch, tmp_path):
    repository, session_id = _repository_with_message(tmp_path)
    user_message = repository.list_messages(PROJECT_ID, session_id)[0]
    repository.begin_run(
        PROJECT_ID,
        session_id,
        run_id="run-failed",
        user_message_id=user_message.message_id,
        started_at="2026-08-19T00:00:00+00:00",
    )
    for attempt_index, error_message in (
        (1, "第一次连接失败。"),
        (2, "上游响应在完成标记前结束。"),
    ):
        append_journal_event(
            tmp_path / ".Tiance",
            session_id=session_id,
            run_id="run-failed",
            turn_id=None,
            tool_call_id=None,
            event_type="model.request_attempt.failed",
            occurred_at=f"2026-08-19T00:00:0{attempt_index}+00:00",
            payload={
                "attempt_index": attempt_index,
                "attempt_count": 2,
                "error_code": "upstream_stream_incomplete",
                "error_message": error_message,
            },
        )
    repository.settle_run(
        PROJECT_ID,
        session_id,
        run_id="run-failed",
        status="error",
        error_code="upstream_stream_incomplete",
        error_message="上游响应在完成标记前结束。",
        attempt_count=2,
        settled_at="2026-08-19T00:00:01+00:00",
    )
    monkeypatch.setattr(
        conversation_routes,
        "get_project_conversation_service",
        lambda: ProjectConversationService(repository),
    )
    application = FastAPI()
    register_exception_handlers(application)
    application.include_router(conversation_routes.router)

    response = TestClient(application).get(
        f"/projects/{PROJECT_ID}/conversations/{session_id}/messages",
        params={"limit": 20},
    )

    assert response.status_code == 200
    payload = response.json()
    assert [item["role"] for item in payload["items"]] == ["user"]
    assert payload["run_outcomes"] == [
        {
            "run_id": "run-failed",
            "session_id": session_id,
            "user_message_id": user_message.message_id,
            "status": "error",
            "error_code": None,
            "error_message": None,
            "attempt_count": 2,
            "started_at": "2026-08-19T00:00:00+00:00",
            "settled_at": "2026-08-19T00:00:01+00:00",
        }
    ]
    assert [
        (failure["attempt_index"], failure["attempt_count"], failure["error_message"])
        for failure in payload["run_attempt_failures"]
    ] == [
        (1, 2, "第一次连接失败。"),
        (2, 2, "上游响应在完成标记前结束。"),
    ]


def test_branch_group_list_does_not_depend_on_message_page(monkeypatch):
    class EmptyBranchService:
        def list_branch_groups(self, project_id):
            assert project_id == PROJECT_ID
            return ()

    monkeypatch.setattr(
        conversation_routes,
        "get_project_conversation_service",
        lambda: EmptyBranchService(),
    )
    application = FastAPI()
    register_exception_handlers(application)
    application.include_router(conversation_routes.router)

    response = TestClient(application).get(
        f"/projects/{PROJECT_ID}/conversation-branches"
    )

    assert response.status_code == 200
    assert response.json() == {
        "project_id": PROJECT_ID,
        "count": 0,
        "items": [],
    }


def _repository_with_message(tmp_path) -> tuple[ProjectConversationRepository, str]:
    repository = ProjectConversationRepository(FakeProjectRepository(str(tmp_path)))
    session = repository.create_session(
        PROJECT_ID,
        title="Pagination",
        provider_id="provider-a",
        model_id="model-a",
        reasoning_mode="off",
    )
    repository.append_message(
        PROJECT_ID,
        session.session_id,
        role="user",
        content="hello",
    )
    return repository, session.session_id
