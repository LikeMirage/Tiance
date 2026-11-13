import pytest

from app.core.errors import ConflictError, NotFoundError
from tests.test_project_conversation_branching import PROJECT_ID, _repository, _create_session, _append


def test_ai_clone_running_session_copies_stable_prefix_without_activating(tmp_path):
    repo = _repository(tmp_path)
    source = _create_session(repo)
    _append(repo, source.session_id, "user", "first")
    _append(repo, source.session_id, "assistant", "finished answer")
    last = _append(repo, source.session_id, "user", "current request")
    _append(repo, source.session_id, "assistant", "partial tool call")
    repo.save_state(PROJECT_ID, active_session_id=None, should_update_active_session=False, session_drafts={}, session_references={}, session_runtime_statuses={source.session_id: "running"})
    active_before, _ = repo.get_state(PROJECT_ID)
    result = repo.fork_session(PROJECT_ID, source.session_id, source_message_id=None,
        draft=None, references=None, created_by="ai",
        configuration={"provider_id": "other", "model_id": "plain", "reasoning_mode": None,
                       "settings": {"system_prompt": "child instructions"}})
    copied = repo.list_messages(PROJECT_ID, result.session.session_id)
    assert [m.content for m in copied] == ["first", "finished answer"]
    assert result.state.draft == last.content
    assert result.branch.relation_kind == "child"
    assert result.branch.history_mode == "fork"
    assert result.branch.created_by == "ai"
    assert result.branch.parent_session_id == source.session_id
    assert result.session.model_id == "plain" and result.session.reasoning_mode is None
    assert result.session.settings.system_prompt == "child instructions"
    active_after, states = repo.get_state(PROJECT_ID)
    assert active_after == active_before
    assert states[source.session_id].runtime_status == "running"
    assert states[result.session.session_id].runtime_status == "idle"
    assert repo.get_session(PROJECT_ID, source.session_id).settings.system_prompt == "stable system prompt"
    assert len(repo.list_messages(PROJECT_ID, source.session_id)) == 4
    _append(repo, source.session_id, "assistant", "source continues")
    assert len(repo.list_messages(PROJECT_ID, result.session.session_id)) == 2


def test_human_branch_keeps_existing_running_guard_and_ai_invalid_boundary_has_no_child(tmp_path, monkeypatch):
    from app.infra.conversation_runtime import ConversationRuntimeRegistry
    from app.repositories.project import conversation_branch_repository
    runtime = ConversationRuntimeRegistry()
    monkeypatch.setattr(conversation_branch_repository, "conversation_runtime", runtime)
    repo = _repository(tmp_path)
    source = _create_session(repo)
    user = _append(repo, source.session_id, "user", "question")
    assistant = _append(repo, source.session_id, "assistant", "reply")
    runtime.start(PROJECT_ID, source.session_id, "active-run")
    repo.save_state(PROJECT_ID, active_session_id=None, should_update_active_session=False, session_drafts={}, session_references={}, session_runtime_statuses={source.session_id: "running"})
    with pytest.raises(ConflictError):
        repo.fork_session(PROJECT_ID, source.session_id, source_message_id=user.message_id, draft="edit", references=[])
    for boundary, error in [(assistant.message_id, ConflictError), ("missing", NotFoundError)]:
        with pytest.raises(error):
            repo.fork_session(PROJECT_ID, source.session_id, source_message_id=boundary,
                draft=None, references=None, created_by="ai")
    assert len(repo.list_sessions(PROJECT_ID)) == 1


def test_ai_explicit_earlier_boundary_and_nested_child_use_same_copy_pipeline(tmp_path):
    repo = _repository(tmp_path)
    source = _create_session(repo)
    user = _append(repo, source.session_id, "user", "old question")
    _append(repo, source.session_id, "assistant", "old answer")
    _append(repo, source.session_id, "user", "new question")
    child = repo.fork_session(PROJECT_ID, source.session_id, source_message_id=user.message_id,
        draft=None, references=None, created_by="ai")
    assert child.state.draft == "old question"
    assert not repo.list_messages(PROJECT_ID, child.session.session_id)
    _append(repo, child.session.session_id, "user", "child question")
    nested = repo.fork_session(PROJECT_ID, child.session.session_id, source_message_id=None,
        draft=None, references=None, created_by="ai")
    assert nested.branch.parent_session_id == child.session.session_id
    assert nested.branch.relation_kind == "child"
