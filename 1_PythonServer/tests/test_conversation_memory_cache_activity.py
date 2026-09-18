from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.domain.llm.chat import ChatCompletionRequest, ChatMessage, ChatMessageRole, ChatToolCall
from app.domain.project.project_conversation import ProjectConversationMessage
from app.repositories.project.conversation_branch_copy import copy_message_prefix
from app.services.project.conversation_memory_delivery import ProjectConversationMemoryDeliveryService


def _message(at, *, role="assistant", status="done", tool_calls=(), **changes):
    return ProjectConversationMessage(
        message_id=f"{role}-{at}", session_id="source", role=role,
        content="message", thinking_content="", usage=None,
        provider_id="provider", model_id="model", status=status,
        created_at=at, updated_at=at, tool_calls=tool_calls,
        **changes,
    )


def _event(memory_id, content, operation="add"):
    return {
        "memory_id": memory_id if operation == "add" else None,
        "target_memory_id": memory_id if operation != "add" else None,
        "operation": operation, "content": content, "keywords": [],
        "reason": "confirmed change", "created_at": "2026-09-17T09:01:00Z",
    }


@pytest.fixture
def delivery(monkeypatch):
    data = SimpleNamespace(
        state=None, messages=(), now="2026-09-17T08:57:08Z", retention=300,
        global_events=[_event("gm", "global before")],
        project_events=[_event("pm", "project before")],
    )
    session = SimpleNamespace(
        session_id="source",
        settings=SimpleNamespace(global_memory_enabled=True, project_memory_enabled=True),
    )

    def update(_project_id, _session_id, transform):
        data.state = transform(deepcopy(data.state))
        return deepcopy(data.state)

    service = ProjectConversationMemoryDeliveryService(
        SimpleNamespace(
            get_session=lambda *_: session,
            list_messages=lambda *_: data.messages,
        ),
        SimpleNamespace(
            update_session_memory_delivery_state=update,
            read_session_memory_delivery_state=lambda *_: deepcopy(data.state),
            list_global_memory_events=lambda: deepcopy(data.global_events),
            list_project_memory_events=lambda *_: deepcopy(data.project_events),
        ),
        SimpleNamespace(resolve_prompt_cache_retention_seconds=lambda **_: data.retention),
    )
    monkeypatch.setattr(
        "app.services.project.conversation_memory_delivery._utc_now", lambda: data.now,
    )
    service.prepare("project", "source", "first-user", provider_id="provider", model_id="model")
    return service, data


@pytest.mark.parametrize("tool_reply", [False, True])
def test_recent_model_response_keeps_prefix_after_old_user_turn(delivery, tool_reply):
    service, data = delivery
    original_baseline = deepcopy(data.state["baseline"])
    # Reproduce the observed 08:57 user / 09:01 model / 09:02 memory task gap.
    data.state["cache_context"]["last_request_at"] = data.now
    calls = (ChatToolCall(call_id="call", name="test_tool", arguments="{}"),) if tool_reply else ()
    data.messages = (
        _message(data.now, role="user"),
        _message("2026-09-17T09:01:12Z", tool_calls=calls),
        _message("2026-09-17T09:01:13Z", role="tool"),
    )
    data.project_events.append(_event("pm", "project after", "update"))
    data.now = "2026-09-17T09:02:15Z"

    service.prepare("project", "source", "memory-task", provider_id="provider", model_id="model")

    assert data.state["baseline"] == original_baseline
    assert data.state["deliveries"][-1]["project_memory"][0]["after"]["content"] == "project after"
    assert "last_request_at" not in data.state["cache_context"]


@pytest.mark.parametrize("role,status", [
    ("user", "done"), ("tool", "done"), ("assistant", "cancelled"),
    ("assistant", "error"), ("error", "error"),
])
def test_non_model_activity_and_message_edits_do_not_extend_retention(delivery, role, status):
    service, data = delivery
    data.messages = (
        replace(_message("2026-09-17T08:57:30Z"), updated_at="2026-09-17T09:02:50Z"),
        _message("2026-09-17T09:02:55Z", role=role, status=status),
    )
    # Even a recent legacy counter must not override the actual reply time.
    data.state["cache_context"]["last_request_at"] = "2026-09-17T09:02:59Z"
    data.project_events.append(_event("pm", "project after", "update"))
    data.now = "2026-09-17T09:03:00Z"

    service.prepare("project", "source", "next-user", provider_id="provider", model_id="model")

    assert data.state["baseline"]["project_memory"]["items"][0]["content"] == "project after"
    assert len(data.state["deliveries"][-1]["project_memory"]) == 1


@pytest.mark.parametrize("retention,content", [(300, "project after"), (900, "project before")])
def test_provider_retention_applies_to_model_reply_time(delivery, retention, content):
    service, data = delivery
    data.retention = retention
    data.messages = (_message("2026-09-17T08:58:00Z"),)
    data.project_events.append(_event("pm", "project after", "update"))
    data.now = "2026-09-17T09:03:00Z"

    service.prepare("project", "source", "next-user", provider_id="provider", model_id="model")

    assert data.state["baseline"]["project_memory"]["items"][0]["content"] == content


@pytest.mark.parametrize("provider,model", [("other", "model"), ("provider", "other")])
def test_model_switch_invalidates_recent_activity(delivery, provider, model):
    service, data = delivery
    data.messages = (_message("2026-09-17T09:01:59Z"),)
    data.project_events.append(_event("pm", "project after", "update"))
    data.now = "2026-09-17T09:02:00Z"

    service.prepare("project", "source", "next-user", provider_id=provider, model_id=model)

    assert data.state["baseline"]["project_memory"]["items"][0]["content"] == "project after"


def test_no_successful_response_does_not_use_legacy_counter(delivery):
    service, data = delivery
    data.state["cache_context"]["last_request_at"] = "2026-09-17T09:02:59Z"
    data.messages = (_message("2026-09-17T09:02:59Z", role="user"),)
    data.project_events.append(_event("pm", "project after", "update"))
    data.now = "2026-09-17T09:03:00Z"

    service.prepare("project", "source", "next-user", provider_id="provider", model_id="model")

    assert data.state["baseline"]["project_memory"]["items"][0]["content"] == "project after"


@pytest.mark.parametrize("scope", ["global", "project"])
@pytest.mark.parametrize("reply_at,expired", [
    ("2026-09-17T09:01:12Z", False), ("2026-09-17T08:57:00Z", True),
])
def test_function_branch_uses_copied_response_time(delivery, scope, reply_at, expired):
    service, data = delivery
    source_state = deepcopy(data.state)
    source_messages = (
        _message("2026-09-17T08:56:00Z", role="user"),
        _message(reply_at),
    )
    copied, _ = copy_message_prefix(source_messages, target_session_id="function")
    assert copied[-1].created_at == source_messages[-1].created_at
    data.messages = (*copied, _message("2026-09-17T09:02:15Z", role="user"))
    getattr(data, f"{scope}_events").append(_event(f"{scope[0]}m", "after", "update"))
    data.now = "2026-09-17T09:02:15Z"

    service.prepare("project", "function", "function-task", provider_id="provider", model_id="model")

    baseline = data.state["baseline"][f"{scope}_memory"]
    assert baseline["items"][0]["content"] == ("after" if expired else f"{scope} before")
    assert data.state["deliveries"][-1][f"{scope}_memory"][0]["after"]["content"] == "after"
    assert source_state["cursors"][f"{scope}_memory"] == 1


def test_accumulated_global_and_project_changes_are_all_delivered_once(delivery):
    service, data = delivery
    original_baseline = deepcopy(data.state["baseline"])
    for scope in ("global", "project"):
        events = getattr(data, f"{scope}_events")
        for index in range(20):
            events.extend([
                _event(f"{scope[0]}m", f"revision {index}", "update"),
                _event(f"{scope}-{index}", "temporary"),
                _event(f"{scope}-{index}", "", "delete"),
            ])
    data.messages = (_message("2026-09-17T09:19:59Z"),)
    data.now = "2026-09-17T09:20:00Z"
    service.prepare("project", "source", "next-user", provider_id="provider", model_id="model")

    assert data.state["baseline"] == original_baseline
    notification = data.state["deliveries"][-1]
    for scope in ("global_memory", "project_memory"):
        assert [change["operation"] for change in notification[scope]] == ["update", "add", "delete"] * 20
        assert data.state["cursors"][scope] == 61
    assert notification["user_message_id"] == "next-user"
    saved_deliveries = deepcopy(data.state["deliveries"])
    data.messages += (_message("2026-09-17T09:20:30Z"),)
    data.now = "2026-09-17T09:21:00Z"
    service.prepare("project", "source", "third-user", provider_id="provider", model_id="model")
    assert data.state["deliveries"] == saved_deliveries
    assert data.state["baseline"] == original_baseline


def test_pending_preview_uses_same_activity_without_persisting_changes(delivery):
    service, data = delivery
    original_state = deepcopy(data.state)
    data.messages = (_message("2026-09-17T09:01:12Z"),)
    data.project_events.append(_event("pm", "project after", "update"))
    data.now = "2026-09-17T09:02:15Z"
    request = ChatCompletionRequest(
        project_id="project", session_id="source", provider_id="provider", model_id="model",
        messages=(ChatMessage(role=ChatMessageRole.USER, content="draft"),),
    )

    preview = service.inject(request, include_pending_changes=True)

    system_text = "\n".join(message.content for message in preview.messages if message.role == ChatMessageRole.SYSTEM)
    assert "project before" in system_text
    assert "project after" not in system_text
    assert "project after" in preview.messages[-1].content
    assert data.state == original_state
