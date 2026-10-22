from dataclasses import replace
from unittest.mock import Mock

import pytest

from app.core.errors import NotFoundError
from app.domain.llm.chat import ChatCompletionRequest, ChatMessage, ChatMessageRole
from app.repositories.project import conversation_stores
from app.repositories.project.conversation_database import replace_message_payloads
from app.repositories.project.conversation_serialization import _message_to_payload
from app.services.project.conversation_stream_persistence import ConversationStreamPersistence
from app.services.project.project_conversations import ProjectConversationService
from tests.test_project_conversation_branching import PROJECT_ID, _repository, _create_session, _append


def _persistence(service):
    return ConversationStreamPersistence(
        conversation_service=service, usage_service=Mock(), naming_service=Mock(),
        memory_service=Mock(), background_task_registry=Mock(),
    )


def _request(session_id):
    return ChatCompletionRequest(
        provider_id="provider-a", model_id="model-a", project_id=PROJECT_ID,
        session_id=session_id, messages=(ChatMessage(role=ChatMessageRole.USER, content="hello"),),
    )


def test_pending_check_deserializes_only_one_of_10000_messages(tmp_path, monkeypatch):
    repository = _repository(tmp_path)
    session = _create_session(repository)
    base = _append(repository, session.session_id, "user", "hello")
    base = replace(base, target_provider_id="provider-a", target_model_id="model-a")
    session_dir = repository._session_store.require_session_dir(PROJECT_ID, session.session_id)
    replace_message_payloads(session_dir, [
        _message_to_payload(replace(base, message_id=f"m{i}")) for i in range(10000)
    ])
    decode = Mock(wraps=conversation_stores._message_from_payload)
    monkeypatch.setattr(conversation_stores, "_message_from_payload", decode)
    monkeypatch.setattr(conversation_stores, "list_message_payloads", Mock(side_effect=AssertionError("must not load full history")))
    persistence = _persistence(ProjectConversationService(repository))
    request = _request(session.session_id)
    persistence.validate_conversation_target(request)
    assert decode.call_count == 0
    pending = persistence._matching_pending_user_message(request, request.messages[-1])
    assert pending.message_id == "m9999"
    assert decode.call_count == 1


@pytest.mark.parametrize("role", ["user", "assistant", "tool", "error"])
def test_latest_message_keeps_actual_last_role_and_session_boundary(tmp_path, role):
    repository = _repository(tmp_path)
    first = _create_session(repository)
    other = _create_session(repository)
    _append(repository, first.session_id, "user", "earlier")
    last = _append(repository, first.session_id, role, "latest")
    _append(repository, other.session_id, "user", "other session newer")
    service = ProjectConversationService(repository)
    assert service.get_latest_message(PROJECT_ID, first.session_id) == last


def test_empty_session_and_missing_session_remain_distinct(tmp_path):
    repository = _repository(tmp_path)
    session = _create_session(repository)
    service = ProjectConversationService(repository)
    persistence = _persistence(service)
    request = _request(session.session_id)
    assert service.get_latest_message(PROJECT_ID, session.session_id) is None
    persistence.validate_conversation_target(request)
    assert persistence._matching_pending_user_message(request, request.messages[-1]) is None
    with pytest.raises(NotFoundError):
        service.get_latest_message(PROJECT_ID, "missing")
    with pytest.raises(NotFoundError):
        persistence.validate_conversation_target(replace(request, session_id="missing"))


@pytest.mark.parametrize("change", [{"message_id": "other-id"}, {"content": "different"}])
def test_pending_check_still_requires_matching_message(tmp_path, change):
    repository = _repository(tmp_path)
    session = _create_session(repository)
    _append(repository, session.session_id, "user", "hello")
    persistence = _persistence(ProjectConversationService(repository))
    request = _request(session.session_id)
    assert persistence._matching_pending_user_message(request, replace(request.messages[-1], **change)) is None
