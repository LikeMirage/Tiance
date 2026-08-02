from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes.project import conversations as conversation_routes
from app.core.errors import BadRequestError, NotFoundError, register_exception_handlers
from app.domain.project import Project
from app.domain.project.project_conversation import ProjectConversationMessage
from app.repositories.project import conversation_stores
from app.repositories.project.conversation_repository import ProjectConversationRepository
from app.repositories.project.conversation_stores import ConversationMessageStore
from app.services.project.project_conversations import ProjectConversationService


PROJECT_ID = "00000000-0000-0000-0000-000000000986"
TIMESTAMP = "2026-07-17T00:00:00+00:00"


class FakeProjectRepository:
    def __init__(self, root_path: str) -> None:
        now = datetime.now(UTC).isoformat()
        self.project = Project(
            project_id=PROJECT_ID,
            name="message-turn-test",
            root_path=root_path,
            is_default=False,
            sort_order=0,
            created_at=now,
            updated_at=now,
        )

    def get_project(self, project_id: str) -> Project | None:
        return self.project if project_id == PROJECT_ID else None


def test_store_reads_exact_turn_from_more_than_ten_thousand_messages_in_one_scan(
    monkeypatch,
    tmp_path,
):
    store = ConversationMessageStore()
    session_dir = tmp_path / "session"
    older_messages = tuple(
        _message(
            f"older-{index}",
            role="user" if index % 2 == 0 else "assistant",
        )
        for index in range(10_001)
    )
    target_messages = (
        _message("target-user", role="user", content="same content as a decoy"),
        _message("target-tool", role="tool", status="done"),
        _message("target-reply", role="assistant", status="cancelled"),
    )
    boundary = _message("next-user", role="user")
    messages_after_boundary = tuple(
        _message(f"newer-{index}", role="assistant")
        for index in range(250)
    )
    store.write_messages(
        session_dir,
        (*older_messages, *target_messages, boundary, *messages_after_boundary),
    )

    parsed_message_count = _track_message_parsing(monkeypatch)

    turn = store.get_message_turn(session_dir, "target-user")

    assert [message.message_id for message in turn.items] == [
        "target-user",
        "target-tool",
        "target-reply",
    ]
    assert turn.items[-1].status == "cancelled"
    assert parsed_message_count() == len(older_messages) + len(target_messages) + 1


def test_store_stops_at_next_user_when_target_is_the_oldest_turn(
    monkeypatch,
    tmp_path,
):
    store = ConversationMessageStore()
    session_dir = tmp_path / "oldest-target-session"
    target_messages = (
        _message("oldest-user", role="user"),
        _message("oldest-reply", role="assistant"),
    )
    boundary = _message("second-user", role="user")
    newer_messages = tuple(
        _message(f"newer-{index}", role="assistant")
        for index in range(10_001)
    )
    store.write_messages(
        session_dir,
        (*target_messages, boundary, *newer_messages),
    )

    parsed_message_count = _track_message_parsing(monkeypatch)

    turn = store.get_message_turn(session_dir, "oldest-user")

    assert [message.message_id for message in turn.items] == [
        "oldest-user",
        "oldest-reply",
    ]
    assert parsed_message_count() == len(target_messages) + 1


@pytest.mark.parametrize(
    ("reply_role", "reply_status", "expected_count"),
    [
        (None, None, 1),
        ("assistant", "done", 2),
        ("error", "error", 2),
        ("assistant", "cancelled", 2),
    ],
)
def test_store_preserves_all_supported_turn_outcomes(
    tmp_path,
    reply_role,
    reply_status,
    expected_count,
):
    store = ConversationMessageStore()
    session_dir = tmp_path / f"session-{reply_status or 'missing'}"
    messages = [_message("target-user", role="user")]
    if reply_role is not None and reply_status is not None:
        messages.append(_message("target-reply", role=reply_role, status=reply_status))
    messages.append(_message("next-user", role="user"))
    store.write_messages(session_dir, tuple(messages))

    turn = store.get_message_turn(session_dir, "target-user")

    assert len(turn.items) == expected_count
    if expected_count == 2:
        assert turn.items[-1].status == reply_status


def test_store_distinguishes_missing_id_from_non_user_id(tmp_path):
    store = ConversationMessageStore()
    session_dir = tmp_path / "session"
    store.write_messages(
        session_dir,
        (
            _message("target-user", role="user"),
            _message("target-reply", role="assistant"),
        ),
    )

    with pytest.raises(NotFoundError) as missing_error:
        store.get_message_turn(session_dir, "missing-user")
    assert missing_error.value.details == {"parameter": "user_message_id"}

    with pytest.raises(BadRequestError) as role_error:
        store.get_message_turn(session_dir, "target-reply")
    assert role_error.value.details == {"parameter": "user_message_id"}


def test_message_turn_api_returns_exact_user_identity_and_stable_missing_error(
    monkeypatch,
    tmp_path,
):
    repository = ProjectConversationRepository(FakeProjectRepository(str(tmp_path)))
    session = repository.create_session(
        PROJECT_ID,
        title="Exact turn",
        provider_id="provider-a",
        model_id="model-a",
        reasoning_mode="off",
    )
    repository.append_message(
        PROJECT_ID,
        session.session_id,
        role="user",
        content="question",
        message_id="exact-user",
    )
    repository.append_message(
        PROJECT_ID,
        session.session_id,
        role="assistant",
        content="answer",
        status="done",
        message_id="exact-reply",
    )
    service = ProjectConversationService(repository)
    monkeypatch.setattr(
        conversation_routes,
        "get_project_conversation_service",
        lambda: service,
    )
    application = FastAPI()
    register_exception_handlers(application)
    application.include_router(conversation_routes.router)
    client = TestClient(application)

    response = client.get(
        f"/projects/{PROJECT_ID}/conversations/{session.session_id}"
        "/messages/exact-user/turn"
    )

    assert response.status_code == 200
    assert response.json()["user_message_id"] == "exact-user"
    assert [item["message_id"] for item in response.json()["items"]] == [
        "exact-user",
        "exact-reply",
    ]

    missing_response = client.get(
        f"/projects/{PROJECT_ID}/conversations/{session.session_id}"
        "/messages/missing-user/turn"
    )
    assert missing_response.status_code == 404
    assert missing_response.json()["error"] == {
        "code": "not_found",
        "message": "Conversation user message 'missing-user' was not found.",
        "details": {"parameter": "user_message_id"},
    }


def test_repository_cancels_existing_assistant_message_without_appending_duplicate(
    tmp_path,
):
    repository = ProjectConversationRepository(FakeProjectRepository(str(tmp_path)))
    session = repository.create_session(
        PROJECT_ID,
        title="Cancellation",
        provider_id="provider-a",
        model_id="model-a",
        reasoning_mode="off",
    )
    repository.append_message(
        PROJECT_ID,
        session.session_id,
        role="user",
        content="question",
        message_id="cancel-user",
    )
    repository.append_message(
        PROJECT_ID,
        session.session_id,
        role="assistant",
        content="",
        thinking_content="thinking",
        context_tokens=40,
        status="done",
        message_id="cancel-assistant",
    )

    cancelled = repository.cancel_assistant_message(
        PROJECT_ID,
        session.session_id,
        "cancel-assistant",
        usage={"prompt_tokens": 60, "completion_tokens": 4, "total_tokens": 64},
        context_tokens=60,
    )

    messages = repository.list_messages(PROJECT_ID, session.session_id)
    refreshed_session = repository.get_session(PROJECT_ID, session.session_id)
    assert cancelled.status == "cancelled"
    assert cancelled.thinking_content == "thinking"
    assert cancelled.context_tokens == 60
    assert cancelled.usage == {
        "prompt_tokens": 60,
        "completion_tokens": 4,
        "total_tokens": 64,
    }
    assert len(messages) == 2
    assert messages[-1] == cancelled
    assert refreshed_session is not None
    assert refreshed_session.message_count == 2


def _message(
    message_id: str,
    *,
    role: str,
    status: str = "done",
    content: str = "",
) -> ProjectConversationMessage:
    return ProjectConversationMessage(
        message_id=message_id,
        session_id="session-a",
        role=role,
        content=content,
        thinking_content="",
        usage=None,
        provider_id=None,
        model_id=None,
        status=status,
        created_at=TIMESTAMP,
        updated_at=TIMESTAMP,
    )


def _track_message_parsing(monkeypatch):
    parse_count = 0
    original_parser = conversation_stores._message_from_payload

    def tracking_parser(payload):
        nonlocal parse_count
        parse_count += 1
        return original_parser(payload)

    monkeypatch.setattr(conversation_stores, "_message_from_payload", tracking_parser)
    return lambda: parse_count
