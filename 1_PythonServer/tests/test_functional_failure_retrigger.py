import asyncio
from dataclasses import replace

import pytest

from tests import test_project_conversation_memory as compression
from tests import test_project_conversation_long_term_memory as memories


def with_run(snapshot, run_id):
    return replace(snapshot, model_request=replace(snapshot.model_request, run_id=run_id))


def test_failed_compression_does_not_repeat_within_run_but_new_run_and_manual_request_can_retry(tmp_path):
    conversation, session, repository, service = compression._create_services(tmp_path, settings={"memory_raw_context_token_reserve": 0})
    for n in (1, 2):
        compression._append_turn(conversation, session.session_id, n)
    calls = []
    async def fail(request):
        calls.append(request)
        raise RuntimeError('attachment unavailable')
    service.set_functional_conversation_runner(fail)
    async def check(run_id):
        await service.compact_context_if_enabled(compression.PROJECT_ID, session.session_id,
            run_snapshot=with_run(compression._snapshot_for_latest_assistant(conversation, session.session_id), run_id))
    async def scenario():
        await check('parent-1')
        # A changed assistant/tool boundary is still part of the same user run.
        conversation.append_message(compression.PROJECT_ID, session.session_id, role='assistant', content='new boundary')
        await asyncio.gather(check('parent-1'), check('parent-1'))
        assert len(calls) == 1
        await check('parent-2')
        assert len(calls) == 2
        result = service.handle_compaction_tool_call(compression.PROJECT_ID, session.session_id, {})
        assert result['action'] == 'scheduled'
        await check('parent-2')
        assert len(calls) == 3
    asyncio.run(scenario())
    assert all(record['status'] == 'failed' for record in repository.list_compressions(compression.PROJECT_ID, session.session_id))
    assert conversation.get_session(compression.PROJECT_ID, session.session_id).settings.memory_compression_enabled


@pytest.mark.parametrize('blocking', [False, True])
def test_memory_scopes_fail_independently_and_new_run_retries(tmp_path, blocking):
    conversation, session, project_repo, global_repo, service = memories._create_services(tmp_path,
        settings_overrides={'blockingEnabled': blocking}, global_settings_overrides={'triggerTokenThreshold': 1})
    memories._append_turn(conversation, session.session_id, 1)
    calls = []
    async def fail(request):
        calls.append(request)
        raise RuntimeError('attachment unavailable')
    service.set_functional_conversation_runner(fail)
    async def check(run_id):
        await service.manage_context_if_enabled(memories.PROJECT_ID, session.session_id, blocking=blocking,
            run_snapshot=with_run(memories._snapshot(conversation, session.session_id), run_id))
    async def scenario():
        await check('parent-1')
        assert len(calls) == 2
        conversation.append_message(memories.PROJECT_ID, session.session_id, role='assistant', content='another boundary')
        await asyncio.gather(check('parent-1'), check('parent-1'))
        assert len(calls) == 2
        await check('parent-2')
        assert len(calls) == 4
    asyncio.run(scenario())
    assert {r.usage_feature_key for r in calls} == {'project_memory_management', 'global_memory_management'}
    assert project_repo.read_state(memories.PROJECT_ID, session.session_id) is None
    assert global_repo.read_state(memories.PROJECT_ID, session.session_id) is None


def test_successful_memory_task_does_not_limit_later_threshold_in_same_run(tmp_path):
    conversation, session, _, _, service = memories._create_services(tmp_path)
    memories._append_turn(conversation, session.session_id, 1)
    calls = []
    service.set_functional_conversation_runner(memories._successful_runner(conversation, calls))
    async def check():
        await service.manage_context_if_enabled(memories.PROJECT_ID, session.session_id,
            run_snapshot=with_run(memories._snapshot(conversation, session.session_id), 'same-parent-run'))
    async def scenario():
        await check()
        conversation.append_message(memories.PROJECT_ID, session.session_id, role='assistant', content='new work ' * 80)
        await check()
    asyncio.run(scenario())
    assert len(calls) == 2
