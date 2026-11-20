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


def _failed_run(repository, session_id, user, run_id, tmp_path):
    repository.begin_run(
        PROJECT_ID, session_id, run_id=run_id, user_message_id=user.message_id,
        started_at="2026-11-17T07:00:00+00:00",
    )
    for attempt, error in ((1, "Server disconnected without sending a response."), (2, "ReadError")):
        append_journal_event(
            tmp_path / ".Tiance", session_id=session_id, run_id=run_id,
            turn_id=user.message_id, tool_call_id=None, event_type="model.request_attempt.failed",
            occurred_at=f"2026-11-17T07:20:0{attempt}+00:00",
            payload={"attempt_index": attempt, "attempt_count": 2,
                     "error_code": "upstream_connection_error", "error_message": error},
        )
    repository.settle_run(
        PROJECT_ID, session_id, run_id=run_id, status="error",
        error_code="upstream_connection_error", error_message="ReadError", attempt_count=2,
        settled_at="2026-11-17T07:20:03+00:00",
    )


def test_long_turn_tail_api_keeps_failures_when_user_row_is_on_previous_page(monkeypatch, tmp_path):
    repository, session_id = _repository_with_message(tmp_path)
    user = repository.list_messages(PROJECT_ID, session_id)[0]
    for index in range(83):
        repository.append_message(PROJECT_ID, session_id, role="assistant", content=f"step {index}")
    _failed_run(repository, session_id, user, "long-run", tmp_path)
    monkeypatch.setattr(conversation_routes, "get_project_conversation_service",
                        lambda: ProjectConversationService(repository))
    application = FastAPI()
    application.include_router(conversation_routes.router)
    client = TestClient(application)
    url = f"/projects/{PROJECT_ID}/conversations/{session_id}/messages"
    for params in ({"limit": 80}, {"limit": 80, "after_message_id": user.message_id}):
        response = client.get(url, params=params)
        assert response.status_code == 200
        page = response.json()
        assert len(page["items"]) == 80
        assert all(message["role"] != "user" for message in page["items"])
        assert [outcome["run_id"] for outcome in page["run_outcomes"]] == ["long-run"]
        assert [failure["error_message"] for failure in page["run_attempt_failures"]] == [
            "Server disconnected without sending a response.", "ReadError",
        ]
    assert len(repository.list_messages(PROJECT_ID, session_id)) == 84


def test_partial_pages_only_include_their_own_turns_and_share_stable_failure_ids(tmp_path):
    repository, session_id = _repository_with_message(tmp_path)
    first_user = repository.list_messages(PROJECT_ID, session_id)[0]
    for index in range(6):
        repository.append_message(PROJECT_ID, session_id, role="assistant", content=f"first {index}")
    _failed_run(repository, session_id, first_user, "first-run", tmp_path)
    second_user = repository.append_message(PROJECT_ID, session_id, role="user", content="next task")
    for index in range(6):
        repository.append_message(PROJECT_ID, session_id, role="assistant", content=f"second {index}")
    _failed_run(repository, session_id, second_user, "second-run", tmp_path)
    tail = repository.list_messages_page(PROJECT_ID, session_id, limit=3)
    assert [outcome.run_id for outcome in tail.run_outcomes] == ["second-run"]
    older = repository.list_messages_page(PROJECT_ID, session_id, limit=3,
                                         before_message_id=second_user.message_id)
    assert [outcome.run_id for outcome in older.run_outcomes] == ["first-run"]
    crossing = repository.list_messages_page(PROJECT_ID, session_id, limit=8)
    assert {outcome.run_id for outcome in crossing.run_outcomes} == {"first-run", "second-run"}
    assert {failure.event_id for failure in crossing.run_attempt_failures} == {
        failure.event_id for page in (tail, older) for failure in page.run_attempt_failures
    }


def _message_client(monkeypatch, repository):
    monkeypatch.setattr(conversation_routes, "get_project_conversation_service",
                        lambda: ProjectConversationService(repository))
    application = FastAPI()
    register_exception_handlers(application)
    application.include_router(conversation_routes.router)
    return TestClient(application)


def test_turn_page_keeps_long_task_and_failures_together(monkeypatch, tmp_path):
    repository, session_id = _repository_with_message(tmp_path)
    user = repository.list_messages(PROJECT_ID, session_id)[0]
    for index in range(83):
        repository.append_message(PROJECT_ID, session_id,
                                  role="assistant" if index % 2 == 0 else "tool",
                                  content=f"step {index}")
    _failed_run(repository, session_id, user, "long-run", tmp_path)
    client = _message_client(monkeypatch, repository)
    url = f"/projects/{PROJECT_ID}/conversations/{session_id}/messages"

    page = client.get(url, params={"turn_limit": 80}).json()
    assert page["count"] == page["total_count"] == 84
    assert page["items"][0]["message_id"] == user.message_id
    assert not page["has_more"] and page["next_before_message_id"] is None
    assert [outcome["run_id"] for outcome in page["run_outcomes"]] == ["long-run"]
    assert len(page["run_attempt_failures"]) == 2

    # Sync can omit the already cached user row, but not truncate its new steps
    # or lose the errors belonging to that user.
    delta = client.get(url, params={"turn_limit": 1, "after_message_id": user.message_id}).json()
    assert delta["items"] == page["items"][1:]
    assert not delta["has_more"]
    assert delta["run_outcomes"] == page["run_outcomes"]
    assert delta["run_attempt_failures"] == page["run_attempt_failures"]


def test_eighty_user_turns_not_eighty_internal_records(monkeypatch, tmp_path):
    repository, session_id = _repository_with_message(tmp_path)
    for index in range(81):
        if index:
            repository.append_message(PROJECT_ID, session_id, role="user", content=f"task {index}")
        repository.append_message(PROJECT_ID, session_id, role="assistant", content="working")
        repository.append_message(PROJECT_ID, session_id, role="assistant", content="finished")
    messages = repository.list_messages(PROJECT_ID, session_id)
    client = _message_client(monkeypatch, repository)
    url = f"/projects/{PROJECT_ID}/conversations/{session_id}/messages"
    tail = client.get(url, params={"turn_limit": 80}).json()
    assert tail["count"] == 240 and tail["total_count"] == 243
    assert sum(item["role"] == "user" for item in tail["items"]) == 80
    assert tail["has_more"]
    older = client.get(url, params={
        "turn_limit": 80, "before_message_id": tail["next_before_message_id"],
    }).json()
    assert older["count"] == 3 and not older["has_more"]
    assert [item["message_id"] for item in older["items"] + tail["items"]] == [
        item.message_id for item in messages
    ]
    assert older["revision"] == tail["revision"]
    assert older["reset_revision"] == tail["reset_revision"]


@pytest.mark.parametrize("turn_limit", [1, 2, 3])
def test_turn_sync_from_inside_task_has_no_gaps_or_duplicates(tmp_path, turn_limit):
    repository, session_id = _repository_with_message(tmp_path)
    for index in range(4):
        if index:
            repository.append_message(PROJECT_ID, session_id, role="user", content=f"task {index}")
        for step in range(index + 2):
            repository.append_message(PROJECT_ID, session_id, role="assistant", content=f"step {step}")
    messages = repository.list_messages(PROJECT_ID, session_id)
    # Cache stops inside the first task, not at its user or final response.
    collected = list(messages[:2])
    while True:
        delta = repository.list_messages_page(
            PROJECT_ID, session_id, turn_limit=turn_limit,
            after_message_id=collected[-1].message_id,
        )
        assert delta.items
        collected.extend(delta.items)
        assert delta.next_after_message_id == collected[-1].message_id
        if not delta.has_more:
            break
        assert messages[len(collected)].role == "user", "A page cannot end inside a task"
    assert collected == list(messages)
    empty = repository.list_messages_page(
        PROJECT_ID, session_id, turn_limit=turn_limit,
        after_message_id=collected[-1].message_id,
    )
    assert not empty.items and not empty.has_more
    assert empty.next_after_message_id == collected[-1].message_id


def test_turn_pages_preserve_legacy_prefix_and_normalize_inside_cursor(tmp_path):
    from app.repositories.project.conversation_database import replace_message_payloads

    repository, session_id = _repository_with_message(tmp_path)
    session_dir = repository.message_sync_target(PROJECT_ID, session_id)
    replace_message_payloads(session_dir, [
        {"message_id": str(index), "session_id": session_id, "role": role,
         "content": str(index), "status": "done",
         "created_at": "2026-11-17T00:00:00+00:00", "updated_at": "2026-11-17T00:00:00+00:00"}
        for index, role in enumerate(["assistant", "user", "assistant", "user", "assistant"])
    ])
    tail = repository.list_messages_page(PROJECT_ID, session_id, turn_limit=1)
    assert [item.message_id for item in tail.items] == ["3", "4"]
    for cursor in (tail.next_before_message_id, "4"):
        older = repository.list_messages_page(
            PROJECT_ID, session_id, turn_limit=1, before_message_id=cursor,
        )
        assert [item.message_id for item in older.items] == ["0", "1", "2"]
        assert not older.has_more


@pytest.mark.parametrize("params,status", [
    ({"turn_limit": 0}, 422),
    ({"turn_limit": 1, "limit": 1}, 400),
    ({"turn_limit": 1, "before_message_id": "missing"}, 400),
    ({"turn_limit": 1, "after_message_id": "missing"}, 400),
    ({"turn_limit": 1, "before_message_id": "before", "after_message_id": "after"}, 400),
])
def test_turn_page_rejects_invalid_parameters(monkeypatch, tmp_path, params, status):
    repository, session_id = _repository_with_message(tmp_path)
    client = _message_client(monkeypatch, repository)
    response = client.get(f"/projects/{PROJECT_ID}/conversations/{session_id}/messages", params=params)
    assert response.status_code == status
