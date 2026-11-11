import asyncio
from contextlib import nullcontext
from unittest.mock import patch

import pytest

from app.core.errors import BadRequestError, ConflictError
from app.api.routes.project import conversations as routes
from tests.test_project_conversation_branching import PROJECT_ID, _repository, _create_session, _append


def child(repository, parent, title):
    message = _append(repository, parent.session_id, "user", title)
    _append(repository, parent.session_id, "assistant", "reply")
    return repository.fork_session(PROJECT_ID, parent.session_id,
        source_message_id=message.message_id, draft=title, references=[]).session


def test_batch_deletes_across_roots_and_preserves_unselected_descendants(tmp_path):
    repository = _repository(tmp_path)
    caller = _create_session(repository, "caller")
    root = _create_session(repository, "root")
    other = _create_session(repository, "other")
    middle = child(repository, root, "middle")
    grandchild = child(repository, middle, "grandchild")
    repository.delete_session(PROJECT_ID, None,
        session_ids=(middle.session_id, other.session_id, middle.session_id),
        protected_session_id=caller.session_id)
    assert repository.get_session(PROJECT_ID, middle.session_id) is None
    assert repository.get_session(PROJECT_ID, other.session_id) is None
    assert repository.get_session(PROJECT_ID, grandchild.session_id) is not None
    nodes, _ = repository.list_branch_graph(PROJECT_ID)
    retained = next(node for node in nodes if node.session_id == grandchild.session_id)
    assert retained.parent_session_id == root.session_id
    assert retained.source_message_id is None


def test_invalid_batch_is_rejected_before_any_deletion(tmp_path):
    repository = _repository(tmp_path)
    a = _create_session(repository, "a")
    b = _create_session(repository, "b")
    for selection in [(), (" ",), (a.session_id, "missing")]:
        with pytest.raises(BadRequestError):
            repository.delete_session(PROJECT_ID, None, session_ids=selection)
        assert repository.get_session(PROJECT_ID, a.session_id) is not None
        assert repository.get_session(PROJECT_ID, b.session_id) is not None
    # The pre-existing single-session endpoint still rejects unrelated targets.
    with pytest.raises(BadRequestError, match="下级"):
        repository.delete_session(PROJECT_ID, a.session_id, session_ids=(a.session_id, b.session_id))


def test_caller_and_ancestors_are_protected_even_without_cascading(tmp_path):
    repository = _repository(tmp_path)
    root = _create_session(repository, "root")
    middle = child(repository, root, "middle")
    caller = child(repository, middle, "caller")
    other = _create_session(repository, "other")
    for forbidden in [root, middle, caller]:
        with pytest.raises(ConflictError, match="调用会话"):
            repository.validate_session_deletion(PROJECT_ID, None,
                session_ids=(other.session_id, forbidden.session_id), protected_session_id=caller.session_id)
        with pytest.raises(ConflictError, match="调用会话"):
            repository.delete_session(PROJECT_ID, None,
                session_ids=(other.session_id, forbidden.session_id), protected_session_id=caller.session_id)
        assert repository.get_session(PROJECT_ID, other.session_id) is not None


def test_selection_is_revalidated_at_commit_and_does_not_include_new_children(tmp_path):
    repository = _repository(tmp_path)
    caller = _create_session(repository, "caller")
    a = _create_session(repository, "a")
    b = _create_session(repository, "b")
    selected = repository.validate_session_deletion(PROJECT_ID, None,
        session_ids=(a.session_id, b.session_id), protected_session_id=caller.session_id)
    new_child = child(repository, a, "created after preview")
    repository.delete_session(PROJECT_ID, b.session_id, session_ids=(b.session_id,))
    with pytest.raises(BadRequestError, match="不存在"):
        repository.delete_session(PROJECT_ID, None, session_ids=selected, protected_session_id=caller.session_id)
    assert repository.get_session(PROJECT_ID, a.session_id) is not None
    repository.delete_session(PROJECT_ID, None, session_ids=(a.session_id,), protected_session_id=caller.session_id)
    assert repository.get_session(PROJECT_ID, new_child.session_id) is not None
    nodes, _ = repository.list_branch_graph(PROJECT_ID)
    assert next(node for node in nodes if node.session_id == new_child.session_id).parent_session_id is None


def test_batch_database_changes_roll_back_together_on_write_failure(tmp_path, monkeypatch):
    repository = _repository(tmp_path)
    caller = _create_session(repository, "caller")
    a = _create_session(repository, "a")
    b = _create_session(repository, "b")
    original = repository._session_store.delete_session_dir
    def fail_second(path, session_id):
        original(path, session_id)
        if session_id == b.session_id:
            raise OSError("injected write failure")
    monkeypatch.setattr(repository._session_store, "delete_session_dir", fail_second)
    with pytest.raises(OSError):
        repository.delete_session(PROJECT_ID, None, session_ids=(a.session_id, b.session_id),
            protected_session_id=caller.session_id)
    assert repository.get_session(PROJECT_ID, a.session_id) is not None
    assert repository.get_session(PROJECT_ID, b.session_id) is not None
    nodes, _ = repository.list_branch_graph(PROJECT_ID)
    assert all(node.deleted_at is None for node in nodes)


def test_batch_route_stops_and_drains_every_selected_run_before_one_commit():
    calls = []
    class Service:
        def validate_session_deletion(self, project_id, anchor, *, session_ids, protected_session_id):
            assert anchor is None
            assert protected_session_id == "caller"
            calls.append("validate")
            return tuple(dict.fromkeys(session_ids))
        def delete_session(self, project_id, anchor, *, session_ids, protected_session_id):
            assert session_ids == ("a", "b")
            assert protected_session_id == "caller"
            calls.append("delete")
    class Runs:
        def prevent_new_runs(self, project_id, session_ids): return nullcontext()
        async def stop(self, project_id, session_id): calls.append("stop:" + session_id)
    class Background:
        async def cancel_session(self, project_id, session_id): calls.append("cancel:" + session_id)
    class Audit:
        async def wait_session(self, project_id, session_id): calls.append("audit:" + session_id)
    with (
        patch.object(routes, "get_project_conversation_service", return_value=Service()),
        patch.object(routes, "get_conversation_run_manager", return_value=Runs()),
        patch.object(routes, "get_conversation_background_task_registry", return_value=Background()),
        patch.object(routes, "get_conversation_audit_service", return_value=Audit()),
    ):
        asyncio.run(routes.delete_project_conversations("project", routes.ProjectConversationDeleteRequest(
            session_ids=["a", "b", "a"], protected_session_id="caller")))
    assert calls == ["validate", "stop:a", "stop:b", "cancel:a", "cancel:b", "audit:a", "audit:b", "delete"]


def test_deletion_reservation_prevents_restart_and_releases_after_failure():
    from dataclasses import replace
    from app.services.project.conversation_run_manager import ConversationRunManager
    from tests.test_conversation_run_manager import _request, _ControlledStreamService
    async def run_test():
        manager = ConversationRunManager()
        await manager.start(_request(), _ControlledStreamService())
        try:
            with manager.prevent_new_runs("project-1", ("session-1",)):
                await manager.stop("project-1", "session-1")
                assert manager.has_project_activity("project-1")
                with pytest.raises(ConflictError, match="正在删除"):
                    await manager.start(_request(), _ControlledStreamService())
                with pytest.raises(ConflictError):
                    with manager.prevent_new_runs("project-1", ("session-1",)):
                        pytest.fail("overlapping deletion must not start")
                # Other sessions remain usable throughout a deletion.
                await manager.start(replace(_request(), session_id="other"), _ControlledStreamService())
                await manager.stop("project-1", "other")
                raise OSError("deletion failed")
        except OSError:
            pass
        assert not manager.has_project_activity("project-1")
        await manager.start(_request(), _ControlledStreamService())
        await manager.close()
    asyncio.run(run_test())
