from copy import deepcopy
from json import dumps, loads
from types import SimpleNamespace
import sqlite3

import pytest

from app.domain.llm.chat import ChatCompletionRequest, ChatMessage, ChatMessageRole
from app.domain.project.project_conversation import ProjectConversationMessage
from app.repositories.project.conversation_branch_copy import write_inherited_memory_delivery_state
from app.repositories.project.conversation_database import read_document, write_document, write_session
from app.repositories.project.conversation_memory_repository import ProjectConversationMemoryRepository
from app.services.project.conversation_memory_delivery import ProjectConversationMemoryDeliveryService
from app.services.project.conversation_memory_delivery_context import inject_memory_delivery_context
from app.services.project.conversation_memory_delivery_schema import normalize_memory_delivery_state
from app.services.project.conversation_memory_delivery_state import (
    apply_memory_changes, fold_missing_leading_memory_deliveries, prepare_memory_delivery_state,
)
from app.services.project.conversation_request_provenance import tag_conversation_message

GLOBAL = "global_memory"
PROJECT = "project_memory"
SCOPES = (GLOBAL, PROJECT)
RESPONSE = ProjectConversationMessage(
    message_id="reply", session_id="source", role="assistant", content="reply",
    thinking_content="", usage=None, provider_id="test", model_id="test", status="done",
    created_at="2026-11-06T00:00:30Z", updated_at="2026-11-06T00:00:30Z",
)


def event(memory_id, content, operation="add"):
    return {
        "operation": operation,
        "memory_id": memory_id if operation == "add" else None,
        "target_memory_id": memory_id if operation != "add" else None,
        "content": content, "keywords": [], "reason": "recorded fact",
        "created_at": "2026-11-06T00:00:00Z",
    }


def advance(state, events, message="next", *, scope=GLOBAL, expired=False, enabled=True):
    return prepare_memory_delivery_state(
        state, user_message_id=message, created_at="2026-11-06T00:01:00Z",
        last_model_response=None if expired else RESPONSE,
        global_events=events if scope == GLOBAL else [],
        project_events=events if scope == PROJECT else [],
        global_enabled=enabled if scope == GLOBAL else True,
        project_enabled=enabled if scope == PROJECT else True,
        cache_provider_id="test", cache_model_id="test",
    )


def effective(state, scope=GLOBAL):
    items = state["baseline"][scope]["items"]
    for delivery in state["deliveries"]:
        items = apply_memory_changes(items, delivery[scope])
    return {item["id"]: item["content"] for item in items}


def injected(state, *, enabled=True):
    ids = ["first", "old-update", "changed", "next", "last"]
    request = ChatCompletionRequest(
        provider_id="test", model_id="test",
        messages=tuple(tag_conversation_message(
            ChatMessage(role=ChatMessageRole.USER, content=message_id), message_id,
        ) for message_id in ids),
    )
    return inject_memory_delivery_context(
        request, state, global_enabled=enabled, project_enabled=enabled,
    )


def legacy(state):
    state = deepcopy(state)
    state["schema_version"] = 2
    state.pop("sources", None)
    for baseline in state["baseline"].values():
        baseline.pop("source", None)
    for delivery in state["deliveries"]:
        delivery.pop("sources_after", None)
    return state


@pytest.mark.parametrize("scope", SCOPES)
@pytest.mark.parametrize("new_count", [0, 1, 2, 4])
@pytest.mark.parametrize("old_format", [False, True])
def test_shorter_equal_and_longer_replacements_preserve_old_history(scope, new_count, old_format):
    old_events = [event("old", "before"), event("old", "after", "update")]
    state = advance(None, old_events[:1], "first", scope=scope)
    state = advance(state, old_events, "old-update", scope=scope)
    if old_format:
        state = legacy(state)
    original = deepcopy(state)
    old_request = injected(state)
    new_events = [event(f"new-{i}", f"new content {i}") for i in range(new_count)]

    continued = advance(state, new_events, "changed", scope=scope)

    assert state == original  # previews must never mutate the saved input
    assert effective(continued, scope) == {"old": "after", **{
        f"new-{i}": f"new content {i}" for i in range(new_count)
    }}
    assert continued["deliveries"][0][scope] == state["deliveries"][0][scope]
    assert continued["baseline"][scope]["items"] == state["baseline"][scope]["items"]
    assert not any(change["operation"] == "delete" for change in continued["deliveries"][-1][scope])
    old_index = next(i for i, msg in enumerate(old_request.messages) if "old-update" in msg.content)
    assert injected(continued).messages[old_index].content == old_request.messages[old_index].content

    # Persist/reload; subsequent requests must not repeat the reconnect notices.
    reloaded = loads(dumps(continued))
    again = advance(reloaded, new_events, "next", scope=scope)
    assert again["deliveries"] == continued["deliveries"]
    assert again["cursors"] == continued["cursors"]
    normalize_memory_delivery_state(again)


def test_same_length_same_final_snapshot_but_rewritten_prefix_is_detected():
    events = [event("old", "one"), event("old", "two", "update")]
    state = advance(None, events, "first")
    replacement = [event("old", "different origin"), events[1]]
    continued = advance(state, replacement)
    assert effective(continued) == {"old": "two"}
    assert continued["deliveries"] == []
    assert continued["cursors"][GLOBAL] > state["cursors"][GLOBAL]
    assert continued["sources"][GLOBAL] != state["sources"][GLOBAL]


def test_original_log_can_return_without_replaying_its_old_intermediate_changes():
    events = [event("old", "one"), event("old", "two", "update")]
    state = advance(None, events[:1], "first")
    state = advance(state, events, "old-update")
    missing = advance(state, [], "changed")
    restored = advance(missing, events, "next")
    assert restored["deliveries"] == state["deliveries"]
    updated = advance(restored, [*events, event("old", "three", "update")], "last")
    assert updated["deliveries"][-1][GLOBAL][0]["after"]["content"] == "three"
    assert len(updated["deliveries"]) == len(state["deliveries"]) + 1


def test_same_source_preserves_intermediate_changes_and_explicit_deletions():
    events = [event("old", "one")]
    state = advance(None, events, "first")
    events += [event("old", "two", "update"), event("old", "one", "update"), event("old", "", "delete")]
    continued = advance(state, events)
    assert [c["operation"] for c in continued["deliveries"][-1][GLOBAL]] == ["update", "update", "delete"]
    assert effective(continued) == {}


def test_replacement_honors_explicit_deletion_without_deleting_merely_absent_items():
    state = advance(None, [event("removed", "remove me"), event("absent", "keep me")], "first")
    replacement = [event("removed", "remove me"), event("removed", "", "delete")]
    continued = advance(state, replacement)
    assert effective(continued) == {"absent": "keep me"}
    assert [(c["operation"], c["memory_id"]) for c in continued["deliveries"][-1][GLOBAL]] == [("delete", "removed")]


def test_replacement_reports_changed_existing_fact_as_update_and_keeps_old_notice():
    state = advance(None, [event("old", "one")], "first")
    state = advance(state, [event("old", "one"), event("old", "two", "update")], "old-update")
    replacement = advance(state, [event("old", "three")], "changed")
    change = replacement["deliveries"][-1][GLOBAL][0]
    assert (change["operation"], change["before"]["content"], change["after"]["content"]) == ("update", "two", "three")
    assert replacement["deliveries"][0] == state["deliveries"][0]


def test_original_stream_same_value_update_still_keeps_its_recorded_reason():
    events = [event("old", "one")]
    state = advance(None, events, "first")
    update = event("old", "one", "update")
    update["reason"] = "user reconfirmed the existing fact"
    state = advance(state, [*events, update])
    assert state["deliveries"][-1][GLOBAL][0]["reason"] == update["reason"]


@pytest.mark.parametrize("expired", [False, True])
def test_source_switch_and_compaction_keep_source_checkpoint_with_folded_snapshot(expired):
    state = advance(None, [event("old", "original")], "first")
    continued = advance(state, [event("new", "new value")], "changed", expired=expired)
    folded = fold_missing_leading_memory_deliveries(
        continued, visible_message_ids={"last"}, updated_at="now",
    )
    assert effective(folded) == {"old": "original", "new": "new value"}
    assert folded["baseline"][GLOBAL]["source"] == continued["sources"][GLOBAL]
    subsequent = advance(folded, [event("new", "new value"), event("new", "updated", "update")], "last")
    assert effective(subsequent) == {"old": "original", "new": "updated"}


def test_disabling_memory_during_missing_source_does_not_erase_history():
    events = [event("old", "original")]
    state = advance(None, events, "first")
    disabled = advance(state, [], "changed", enabled=False)
    assert effective(disabled) == {"old": "original"}
    assert all("original" not in message.content for message in injected(disabled, enabled=False).messages)
    reenabled = advance(disabled, [], "next")
    assert "original" in injected(reenabled).messages[0].content


def test_duplicate_submission_never_adopts_new_source_twice():
    state = advance(None, [event("old", "original")], "first")
    changed = advance(state, [event("new", "new value")], "changed")
    assert advance(changed, [], "changed") == changed


def test_preview_is_repeatable_and_does_not_consume_real_delivery():
    state = advance(None, [event("old", "original")], "first")
    events = [event("new", "new value")]
    preview = advance(state, events, "__draft_user_message__")
    assert advance(state, events, "__draft_user_message__") == preview
    real = advance(state, events, "changed")
    assert real["deliveries"][-1][GLOBAL] == preview["deliveries"][-1][GLOBAL]
    assert real["deliveries"][-1]["user_message_id"] == "changed"


@pytest.mark.parametrize("branch_point", ["first", "changed", "next"])
def test_branch_after_source_change_uses_checkpoint_at_its_own_branch_point(tmp_path, branch_point):
    state = advance(None, [event("old", "original")], "first")
    events = [event("new", "one")]
    state = advance(state, events, "changed")
    events += [event("new", "two", "update")]
    state = advance(state, events, "next")
    conversations = tmp_path / "conversations"
    for session_id in ("source", "child"):
        write_session(conversations, session_id, {})
    source_dir = conversations / "sessions" / "source"
    child_dir = conversations / "sessions" / "child"
    write_document(source_dir, "memory_delivery", state)
    message_ids = ["first", "changed", "next"]
    mapping = {i: f"child-{i}" for i in message_ids[:message_ids.index(branch_point) + 1]}
    write_inherited_memory_delivery_state(source_dir, child_dir, message_id_map=mapping)
    inherited = read_document(child_dir, "memory_delivery")
    continued = advance(inherited, events, "last")
    assert effective(continued) == {"old": "original", "new": "two"}
    if branch_point == "next":
        assert continued["deliveries"] == inherited["deliveries"]
    else:
        assert continued["deliveries"][-1][GLOBAL][-1]["after"]["content"] == "two"
    # The source conversation is untouched by its child's preparation.
    assert read_document(source_dir, "memory_delivery") == state


def test_legacy_same_source_does_not_miss_pending_updates():
    events = [event("old", "original")]
    state = legacy(advance(None, events, "first"))
    continued = advance(state, [*events, event("old", "updated", "update")])
    assert continued["cursors"][GLOBAL] == 2
    assert continued["deliveries"][-1][GLOBAL][0]["before"]["content"] == "original"
    assert effective(continued) == {"old": "updated"}


def test_branch_does_not_rewind_a_disabled_scopes_folded_baseline(tmp_path):
    def prepare(state, user, global_events, project_events, enabled=True):
        return prepare_memory_delivery_state(
            state, user_message_id=user, created_at="2026-11-06T00:01:00Z",
            last_model_response=RESPONSE, global_events=global_events,
            project_events=project_events, global_enabled=enabled, project_enabled=True,
        )

    global_events = [event("global", "one")]
    project_events = [event("project", "one")]
    state = prepare(None, "first", global_events, project_events)
    global_events.append(event("global", "two", "update"))
    project_events.append(event("project", "two", "update"))
    state = prepare(state, "changed", global_events, project_events)
    state = prepare(state, "next", [], project_events, enabled=False)
    conversations = tmp_path / "conversations"
    for session_id in ("source", "child"):
        write_session(conversations, session_id, {})
    source_dir = conversations / "sessions" / "source"
    child_dir = conversations / "sessions" / "child"
    write_document(source_dir, "memory_delivery", state)
    write_inherited_memory_delivery_state(
        source_dir, child_dir, message_id_map={"first": "child-first", "changed": "child-changed"},
    )
    inherited = normalize_memory_delivery_state(read_document(child_dir, "memory_delivery"))
    continued = prepare(inherited, "last", global_events, project_events)
    assert effective(continued) == {"global": "two"}
    assert effective(continued, PROJECT) == {"project": "two"}


def test_invalid_checkpoint_remains_an_explicit_error_not_a_missing_source():
    state = advance(None, [], "first")
    state["sources"][GLOBAL]["sha256"] = "corrupt"
    with pytest.raises(ValueError, match="fingerprint"):
        advance(state, [])


def test_copied_database_works_without_original_computers_global_memory(tmp_path):
    old_root, new_root = tmp_path / "old-project", tmp_path / "new-project"
    old_conversations = old_root / ".Tiance" / "conversations"
    new_conversations = new_root / ".Tiance" / "conversations"
    write_session(old_conversations, "source", {})
    events = [event("old", "original")]
    state = advance(None, events, "first")
    events.append(event("old", "updated", "update"))
    state = advance(state, events, "old-update")
    write_document(old_conversations / "sessions" / "source", "memory_delivery", state)
    new_conversations.mkdir(parents=True)
    with sqlite3.connect(old_root / ".Tiance" / "tiance.db") as source:
        with sqlite3.connect(new_root / ".Tiance" / "tiance.db") as target:
            source.backup(target)

    project_repository = SimpleNamespace(get_project=lambda _: SimpleNamespace(root_path=str(new_root)))
    repository = ProjectConversationMemoryRepository(
        project_repository, global_memory_root=tmp_path / "new-runtime-memory",
    )
    session = SimpleNamespace(session_id="source", settings=SimpleNamespace(
        global_memory_enabled=True, project_memory_enabled=True,
    ))
    conversations = SimpleNamespace(
        get_session=lambda *_: session, list_messages=lambda *_: (RESPONSE,),
    )
    service = ProjectConversationMemoryDeliveryService(
        conversations, repository,
        SimpleNamespace(resolve_prompt_cache_retention_seconds=lambda **_: 300),
    )
    service.prepare("project", "source", "next", provider_id="test", model_id="test")
    saved = repository.read_session_memory_delivery_state("project", "source")
    assert effective(saved) == {"old": "updated"}
    assert not (tmp_path / "new-runtime-memory" / "global_memory.jsonl").exists()
    request = ChatCompletionRequest(
        provider_id="test", model_id="test", project_id="project", session_id="source",
        messages=(tag_conversation_message(ChatMessage(role=ChatMessageRole.USER, content="continue"), "next"),),
    )
    result = service.inject(request)
    assert sum(message.content.count("updated") for message in result.messages) == 1
    # Actual unreadable/corrupt source data must remain visible as an error.
    memory_dir = tmp_path / "new-runtime-memory"
    memory_dir.mkdir()
    (memory_dir / "global_memory.jsonl").write_text("invalid JSON\n", encoding="utf-8")
    with pytest.raises(ValueError, match="JSONL"):
        service.prepare("project", "source", "last", provider_id="test", model_id="test")
