from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes.project import conversations as conversation_routes
from app.core.errors import BadRequestError, register_exception_handlers
from app.domain.project import Project
from app.repositories.project.conversation_repository import ProjectConversationRepository
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
