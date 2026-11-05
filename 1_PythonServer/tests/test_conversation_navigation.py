import json
from dataclasses import asdict

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes.project import conversations as routes
from app.repositories.project import conversation_stores
from app.repositories.project.conversation_database import read_message_sync_state
from app.repositories.project.conversation_navigation_repository import read_navigation
from app.repositories.project.conversation_repository import ProjectConversationRepository
from app.services.project.project_conversations import ProjectConversationService
from tests.test_conversation_message_turn import FakeProjectRepository, PROJECT_ID, _message, _session_dir


def test_navigation_is_complete_bounded_and_does_not_materialize_message_bodies(tmp_path, monkeypatch):
    session_dir = _session_dir(tmp_path, "session")
    messages = []
    for index in range(121):
        messages.extend((
            _message(f"user-{index}", role="user", content=f"Question {index}"),
            _message(f"tool-{index}", role="tool", content="secret tool result " * 4096),
            _message(f"reply-{index}", role="assistant", content=f"Answer {index}" + "X" * 1000),
        ))
    conversation_stores.ConversationMessageStore().write_messages(session_dir, tuple(messages))

    def reject_full_message_parse(*_args):
        raise AssertionError("Navigation must not load complete message bodies")

    monkeypatch.setattr(conversation_stores, "_message_from_payload", reject_full_message_parse)
    navigation = read_navigation(session_dir)
    assert len(navigation.items) == 121
    assert [item.turn_number for item in navigation.items] == list(range(1, 122))
    assert navigation.items[0].user_message_id == "user-0"
    assert navigation.items[-1].assistant_message_id == "reply-120"
    assert all(len(item.assistant_preview) <= 161 for item in navigation.items)
    assert "secret tool result" not in json.dumps(asdict(navigation))
    assert navigation.revision == read_message_sync_state(session_dir)["revision"]


def test_navigation_keeps_running_failed_unanswered_and_attachment_only_turns(tmp_path):
    session_dir = _session_dir(tmp_path, "session")
    store = conversation_stores.ConversationMessageStore()
    store.write_messages(session_dir, (
        _message("unanswered", role="user", content="Waiting"),
        _message("failed", role="user", content="Failed"),
        _message("failure", role="error", status="error", content="Local error"),
        _message("attachment", role="user", content=""),
        _message("running", role="assistant", status="running", content="incomplete"),
        _message("tools", role="user", content="Execute"),
        _message("before-tool", role="assistant", content="About to execute"),
        _message("tool", role="tool", content="must not be a reply preview"),
    ))
    navigation = read_navigation(session_dir)
    assert [item.user_message_id for item in navigation.items] == ["unanswered", "failed", "attachment", "tools"]
    assert [item.assistant_preview for item in navigation.items] == ["", "Local error", "", ""]
    assert navigation.items[2].user_preview == ""
    store.write_messages(session_dir, (_message("replacement", role="user", content="Replaced"),))
    replacement = read_navigation(session_dir)
    assert [item.user_message_id for item in replacement.items] == ["replacement"]
    assert replacement.items[0].turn_number == 1


def test_navigation_route_is_scoped_to_requested_session(tmp_path, monkeypatch):
    repository = ProjectConversationRepository(FakeProjectRepository(str(tmp_path)))
    sessions = [repository.create_session(PROJECT_ID, title=f"Session {i}", provider_id="test",
        model_id="test", reasoning_mode="off") for i in range(2)]
    for i, session in enumerate(sessions):
        repository.append_message(PROJECT_ID, session.session_id, role="user", content=f"Question {i}", message_id=f"user-{i}")
    monkeypatch.setattr(routes, "get_project_conversation_service", lambda: ProjectConversationService(repository))
    app = FastAPI()
    app.include_router(routes.router)
    with TestClient(app) as client:
        response = client.get(f"/projects/{PROJECT_ID}/conversations/{sessions[1].session_id}/messages/navigation")
    assert response.status_code == 200
    assert [item["user_message_id"] for item in response.json()["items"]] == ["user-1"]
