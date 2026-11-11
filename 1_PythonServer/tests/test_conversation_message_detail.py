from dataclasses import replace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes.project import conversations as routes
from app.core.errors import register_exception_handlers
from app.repositories.project import conversation_stores
from app.repositories.project.conversation_repository import ProjectConversationRepository
from app.services.project.project_conversations import ProjectConversationService
from tests.test_conversation_message_turn import FakeProjectRepository, PROJECT_ID, _message, _session_dir


REFERENCE = {"type": "file", "reference": {"id": "ref", "kind": "folder", "projectId": None,
    "source": "external_path", "filePath": "C:/work/project", "displayPath": "C:/work/project",
    "fileName": "示例（Tiance 项目）"}}


def test_message_detail_reads_only_selected_body_and_preserves_references(tmp_path, monkeypatch):
    store = conversation_stores.ConversationMessageStore()
    session_dir = _session_dir(tmp_path, "session")
    target = replace(_message("target", role="user", content="full text\n" * 1000), references=[REFERENCE])
    store.write_messages(session_dir, (
        *(_message(f"older-{i}", role="user", content="old") for i in range(150)),
        target, _message("tool", role="tool", content="LARGE TOOL RESULT " * 100_000),
    ))
    parsed = []
    original = conversation_stores._message_from_payload

    def track(payload):
        parsed.append(payload["message_id"])
        return original(payload)

    monkeypatch.setattr(conversation_stores, "_message_from_payload", track)
    actual = store.get_message(session_dir, "target")
    assert actual.content == target.content
    assert actual.references == target.references
    assert parsed == ["target"]


def test_message_detail_route_is_scoped_and_keeps_static_routes(tmp_path, monkeypatch):
    repository = ProjectConversationRepository(FakeProjectRepository(str(tmp_path)))
    sessions = [repository.create_session(PROJECT_ID, title=f"Session {i}", provider_id="test",
        model_id="test", reasoning_mode="off") for i in range(2)]
    repository.append_message(PROJECT_ID, sessions[0].session_id, role="user", content="full question",
        message_id="target", references=[REFERENCE])
    monkeypatch.setattr(routes, "get_project_conversation_service", lambda: ProjectConversationService(repository))
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(routes.router)
    with TestClient(app) as client:
        base = f"/projects/{PROJECT_ID}/conversations/{sessions[0].session_id}/messages"
        response = client.get(f"{base}/target")
        assert response.status_code == 200
        assert response.json()["content"] == "full question"
        assert response.json()["references"] == [REFERENCE]
        assert client.get(f"{base}/navigation").status_code == 200
        assert client.get(f"{base}/state").status_code == 200
        assert client.get(f"{base}/missing").status_code == 404
        assert client.get(f"/projects/{PROJECT_ID}/conversations/{sessions[1].session_id}/messages/target").status_code == 404
