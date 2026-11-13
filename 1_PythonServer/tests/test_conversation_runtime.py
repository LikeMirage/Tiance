import asyncio
from dataclasses import replace
from pathlib import Path

import pytest

from app.domain.project.project_conversation import ProjectConversationSessionState
from app.infra.conversation_runtime import ConversationRuntimeRegistry
from app.services.project.conversation_run_manager import ConversationRunManager
from tests.test_conversation_run_manager import _request


def _state(status="running"):
    return ProjectConversationSessionState(
        session_id="session-1", runtime_status=status, draft="draft", references=[],
        updated_at="2000-01-01T00:00:00Z", runtime_updated_at="2000-01-01T00:00:00Z",
    )


def test_old_persisted_timestamp_cannot_expire_a_live_task_or_resurrect_a_dead_task():
    registry = ConversationRuntimeRegistry()
    state = _state()
    registry.start("project-1", state.session_id, "run-1")
    for stored in (state, replace(state, runtime_status="idle"), replace(state, runtime_status="error")):
        assert registry.project_states("project-1", {state.session_id: stored})[state.session_id].runtime_status == "running"
    registry.update("project-1", state.session_id, "run-1", outcome="idle")
    assert registry.project_states("project-1", {state.session_id: state})[state.session_id].runtime_status == "idle"
    error = replace(state, runtime_status="error")
    assert registry.project_states("project-1", {state.session_id: error})[state.session_id].runtime_status == "error"
    assert state.runtime_status == "running"  # Read projection does not write history.


def test_late_completion_from_previous_run_cannot_clear_new_run():
    registry = ConversationRuntimeRegistry()
    registry.start("p", "s", "old")
    registry.start("p", "s", "new")
    registry.update("p", "s", "old", outcome="error")
    assert registry.is_running("p", "s")
    registry.update("p", "s", "new", outcome="idle")
    assert not registry.is_running("p", "s")


def test_stop_stays_busy_during_persistence_and_silent_wait_is_running():
    async def scenario():
        registry = ConversationRuntimeRegistry()
        manager = ConversationRunManager(runtime_registry=registry)
        started, saving, saved = asyncio.Event(), asyncio.Event(), asyncio.Event()

        class Stream:
            async def stream_payloads(self, request, **kwargs):
                started.set()
                yield {"kind": "tool_result", "content": "tool finished"}
                try:
                    await asyncio.Event().wait()  # Upstream has not returned anything.
                except asyncio.CancelledError:
                    saving.set()
                    await saved.wait()
                    yield {"kind": "conversation_run_settled", "status": "cancelled"}
                    raise

        await manager.start(_request(), Stream())
        await started.wait()
        assert (await manager.get_run_status("project-1", "session-1"))["running"]
        assert registry.project_states("project-1", {"session-1": _state()})["session-1"].runtime_status == "running"
        stop = asyncio.create_task(manager.stop("project-1", "session-1"))
        await asyncio.wait_for(saving.wait(), 1)
        status = await manager.get_run_status("project-1", "session-1")
        assert status["running"] and status["stopping"]
        assert registry.is_running("project-1", "session-1")
        assert not stop.done()
        saved.set()
        assert await asyncio.wait_for(stop, 1)
        assert not registry.is_running("project-1", "session-1")
        assert not (await manager.get_run_status("project-1", "session-1"))["running"]

    asyncio.run(scenario())


def test_output_feed_coalesces_real_output_and_reconnect_is_only_a_snapshot():
    async def scenario():
        registry = ConversationRuntimeRegistry()
        events = registry.events()
        assert await anext(events) == {"kind": "snapshot", "runs": []}
        registry.start("p", "s", "run")
        for _ in range(200):
            registry.update("p", "s", "run", output=True)
        batch = await asyncio.wait_for(anext(events), 1)
        assert len(batch["runs"]) == 1 and batch["runs"][0]["output_seq"] == 200
        reconnect = registry.events()
        snapshot = await anext(reconnect)
        assert snapshot["kind"] == "snapshot" and snapshot["runs"] == batch["runs"]
        registry.update("p", "s", "run", outcome="error")
        terminal = await asyncio.wait_for(anext(events), 1)
        assert terminal["runs"][0]["phase"] == "error"
        await reconnect.aclose()
        await events.aclose()
        assert not registry._subscribers

    asyncio.run(scenario())


@pytest.mark.parametrize("outcome", ["completed", "cancelled", "error"])
def test_manager_only_animates_model_output_and_stays_running_through_retries(outcome):
    async def scenario():
        registry = ConversationRuntimeRegistry()
        manager = ConversationRunManager(runtime_registry=registry)
        events = registry.events()
        await anext(events)
        waiting, allow_output, output_done, allow_finish = (
            asyncio.Event() for _ in range(4)
        )

        class Stream:
            async def stream_payloads(self, request, **kwargs):
                for item in (
                    {"kind": "tool_result", "content": "finished"},
                    {"kind": "error", "error": "upstream failed"},
                    {"kind": "retry_reset"},
                    {"kind": "delta", "content": ""},
                    {"kind": "tool_call_delta", "tool_call": None},
                ):
                    yield item
                waiting.set()
                await allow_output.wait()
                yield {"kind": "thinking_delta", "content": "thinking"}
                yield {"kind": "delta", "content": "reply"}
                yield {"kind": "tool_call_delta", "tool_call": {"id": "tool-1"}}
                output_done.set()
                await allow_finish.wait()
                yield {"kind": "conversation_run_settled", "status": outcome}

        await manager.start(_request(), Stream())
        await asyncio.wait_for(waiting.wait(), 1)
        fact = (await asyncio.wait_for(anext(events), 1))["runs"][0]
        assert fact["phase"] == "running" and fact["output_seq"] == 0
        allow_output.set()
        await asyncio.wait_for(output_done.wait(), 1)
        fact = (await asyncio.wait_for(anext(events), 1))["runs"][0]
        assert fact["phase"] == "running" and fact["output_seq"] == 3
        allow_finish.set()
        fact = (await asyncio.wait_for(anext(events), 1))["runs"][0]
        assert fact["phase"] == ("error" if outcome == "error" else "idle")
        assert not (await manager.get_run_status("project-1", "session-1"))["running"]
        await events.aclose()
        await manager.close()

    asyncio.run(scenario())


def test_assistant_append_does_not_end_running_tool_loop(tmp_path):
    from tests.test_project_conversation_branching import PROJECT_ID, _repository, _create_session, _append
    repo = _repository(tmp_path)
    session = _create_session(repo)
    repo.save_session_runtime_status(PROJECT_ID, session.session_id, "running")
    _append(repo, session.session_id, "assistant", "Now invoking a tool")
    _, states = repo.get_state(PROJECT_ID)
    assert states[session.session_id].runtime_status == "running"


def test_old_compaction_still_executing_is_not_recovered_as_orphan(monkeypatch):
    from app.repositories.project import conversation_compaction_repository as module
    registry = ConversationRuntimeRegistry()
    registry.start("project", "child", "run")
    monkeypatch.setattr(module, "conversation_runtime", registry)
    monkeypatch.setattr(module, "active_compression_records", lambda _: [{
        "compression_id": "record", "function_session_id": "child", "created_at": "2000-01-01T00:00:00Z",
    }])
    monkeypatch.setattr(module, "update_compression_record", lambda *args: (_ for _ in ()).throw(AssertionError("must not expire a live task")))
    assert module._recover_stale_tasks(Path("source"), conversations_dir=Path("conversations"),
        project_id="project", now="2026-11-13T00:00:00Z")
