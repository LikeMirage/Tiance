import asyncio
from dataclasses import replace
from pathlib import Path
import threading
import importlib.util
import io
import json
from urllib.error import HTTPError
from urllib.parse import urlsplit
from types import SimpleNamespace

import pytest
import tiance_runtime

from app.domain.llm.chat import ChatCompletionRequest, ChatMessage, ChatMessageRole, ChatToolCall
from app.domain.llm.functional_model_defaults import DEFAULT_NAMING_PROMPT
from app.repositories.project.conversation_database import read_document, write_document
from app.services.project.conversation_functional_run import FunctionalConversationScheduler
from app.services.project.conversation_naming import ProjectConversationNamingService
from app.services.project.conversation_run_snapshot import ConversationRunSnapshot
from app.services.project.conversation_request_provenance import tag_conversation_message
from app.services.project.conversation_stream import ProjectConversationStreamService
from tests.test_project_conversation_naming import (
    naming_attempt, _PROJECT_ID, _FakeFunctionalModelSettingsService,
    _FakeTokenEstimationSettingsService, _default_settings,
)
from tests.test_declared_host_capabilities import bridge, issue, headers
from app.domain.tools.host_capabilities import HostCapability


def service_for(fixture):
    _, conversations, naming, *_ = fixture
    return ProjectConversationNamingService(
        conversations, _FakeFunctionalModelSettingsService(_default_settings()),
        naming, _FakeTokenEstimationSettingsService(),
    )


def task_dir(fixture):
    projects, _, _, _, _, created = fixture
    return Path(projects.project.root_path) / '.Tiance/conversations/sessions' / created.session.session_id


def test_pending_naming_runs_without_frontend_or_loading_history(naming_attempt, monkeypatch):
    _, conversations, naming, source, _, created = naming_attempt
    service = service_for(naming_attempt)
    calls = []
    monkeypatch.setattr(conversations, 'list_messages', lambda *a: pytest.fail('Recovery must not scan history'))

    async def run(request):
        calls.append(request)
        assert request.client_capabilities == ()
        child = conversations.get_session(_PROJECT_ID, request.session_id)
        assert child.settings.enabled_tool_names == ('submit_conversation_title',)
        assert not child.settings.memory_compression_enabled
        naming.apply_title(_PROJECT_ID, request.session_id, title='新的会话标题')

    service.set_functional_conversation_runner(run)
    async def scenario():
        await asyncio.gather(*(service.resume_pending_tasks(_PROJECT_ID) for _ in range(12)))
    asyncio.run(scenario())
    assert len(calls) == 1
    assert calls[0].session_id == created.session.session_id
    assert calls[0].usage_feature_key == 'automatic_naming'
    assert conversations.get_session(_PROJECT_ID, source.session_id).title == '新的会话标题'
    assert read_document(task_dir(naming_attempt), 'automatic_naming_task')['status'] == 'completed'


def test_new_threshold_task_is_created_and_run_in_one_backend_flow(naming_attempt):
    _, conversations, naming, _, _, _ = naming_attempt
    source = conversations.create_session(_PROJECT_ID, title='新对话', provider_id='codex', model_id='gpt-5.6-sol', reasoning_mode=None)
    boundary = conversations.append_message(_PROJECT_ID, source.session_id, role='assistant', content='完成订单分析', status='done')
    snapshot = ConversationRunSnapshot(
        model_request=ChatCompletionRequest(provider_id='codex', model_id='gpt-5.6-sol', messages=()),
        assistant_response=tag_conversation_message(ChatMessage(role=ChatMessageRole.ASSISTANT, content='完成订单分析'), boundary.message_id),
        context_tokens=20000,
    )
    service = service_for(naming_attempt)
    calls = []
    async def run(request):
        calls.append(request)
        naming.apply_title(_PROJECT_ID, request.session_id, title='订单分析')
    service.set_functional_conversation_runner(run)
    async def scenario():
        await asyncio.gather(*(service.name_session_if_needed(_PROJECT_ID, source.session_id, run_snapshot=snapshot) for _ in range(5)))
    asyncio.run(scenario())
    assert len(calls) == 1
    assert conversations.get_session(_PROJECT_ID, source.session_id).title == '订单分析'


def test_cancelled_creation_does_not_become_recoverable_pending_work(naming_attempt, monkeypatch):
    _, conversations, naming, _, _, _ = naming_attempt
    source = conversations.create_session(_PROJECT_ID, title='新对话', provider_id='codex', model_id='gpt-5.6-sol', reasoning_mode=None)
    boundary = conversations.append_message(_PROJECT_ID, source.session_id, role='assistant', content='分析完成', status='done')
    snapshot = ConversationRunSnapshot(
        model_request=ChatCompletionRequest(provider_id='codex', model_id='gpt-5.6-sol', messages=()),
        assistant_response=tag_conversation_message(ChatMessage(role=ChatMessageRole.ASSISTANT, content='分析完成'), boundary.message_id),
        context_tokens=20000,
    )
    service = service_for(naming_attempt)
    entered, release = threading.Event(), threading.Event()
    original = naming.create_task
    created = []
    def delayed_create(*args, **kwargs):
        result = original(*args, **kwargs)
        created.append(result)
        entered.set()
        assert release.wait(5)
        return result
    monkeypatch.setattr(naming, 'create_task', delayed_create)
    async def run(_):
        pytest.fail('Cancelled creation must not start a model request')
    service.set_functional_conversation_runner(run)
    async def scenario():
        task = asyncio.create_task(service.name_session_if_needed(_PROJECT_ID, source.session_id, run_snapshot=snapshot))
        assert await asyncio.to_thread(entered.wait, 5)
        task.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(scenario())
    directory = naming._session_store.session_dir(_PROJECT_ID, created[0].session.session_id)
    assert read_document(directory, 'automatic_naming_task')['status'] == 'failed'
    assert all(task['source_session_id'] != source.session_id for task in naming.list_pending_tasks(_PROJECT_ID))


@pytest.mark.parametrize('failure', ['no_submission', 'exception', 'cancelled', 'submitted_then_cancelled'])
def test_naming_settlement_does_not_leave_pending_or_repeat(naming_attempt, failure):
    _, _, naming, _, _, created = naming_attempt
    service = service_for(naming_attempt)
    calls = []
    async def run(request):
        calls.append(request)
        if failure == 'exception':
            raise RuntimeError('upstream failed')
        if failure == 'submitted_then_cancelled':
            naming.apply_title(_PROJECT_ID, request.session_id, title='已成功提交')
        if 'cancelled' in failure:
            raise asyncio.CancelledError
    service.set_functional_conversation_runner(run)
    async def scenario():
        if 'cancelled' in failure:
            with pytest.raises(asyncio.CancelledError):
                await service.resume_pending_tasks(_PROJECT_ID)
        else:
            await service.resume_pending_tasks(_PROJECT_ID)
        await service.resume_pending_tasks(_PROJECT_ID)
    asyncio.run(scenario())
    task = read_document(task_dir(naming_attempt), 'automatic_naming_task')
    assert task['status'] == ('completed' if failure == 'submitted_then_cancelled' else 'failed')
    assert len(calls) == 1


def test_cancellation_during_database_claim_waits_and_settles(naming_attempt, monkeypatch):
    _, _, naming, _, _, _ = naming_attempt
    service = service_for(naming_attempt)
    entered, release = threading.Event(), threading.Event()
    original = naming.claim_task
    def delayed_claim(*args):
        claimed = original(*args)
        entered.set()
        assert release.wait(5)
        return claimed
    monkeypatch.setattr(naming, 'claim_task', delayed_claim)
    async def run(_):
        pytest.fail('Cancelled claim must not start the model')
    service.set_functional_conversation_runner(run)
    async def scenario():
        task = asyncio.create_task(service.resume_pending_tasks(_PROJECT_ID))
        assert await asyncio.to_thread(entered.wait, 5)
        task.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(scenario())
    assert read_document(task_dir(naming_attempt), 'automatic_naming_task')['status'] == 'failed'


def test_legacy_pending_prompt_and_tool_scope_upgraded_only_on_claim(naming_attempt):
    _, conversations, naming, _, _, created = naming_attempt
    directory = naming._session_store.conversations_dir(_PROJECT_ID)
    old = DEFAULT_NAMING_PROMPT.replace('submit_conversation_title', 'manage_ai_conversations')
    old += '\n额外要求：保留用户自定义命名规则。'
    naming._session_store.write_session_draft(directory, created.session.session_id, old, 'now')
    claimed = naming.claim_task(_PROJECT_ID, created.session.session_id)
    assert 'submit_conversation_title' in claimed.prompt
    assert 'manage_ai_conversations' not in claimed.prompt
    assert '额外要求：保留用户自定义命名规则。' in claimed.prompt
    assert naming._session_store.read_session_state(directory, created.session.session_id).draft == ''
    assert naming.claim_task(_PROJECT_ID, created.session.session_id) is None


def test_scheduler_serializes_same_scope_but_not_other_functions():
    async def scenario():
        scheduler = FunctionalConversationScheduler()
        entered, release = asyncio.Event(), asyncio.Event()
        order = []
        async def first():
            async with scheduler.serialize('p', 's', 'naming'):
                order.append('first'); entered.set(); await release.wait()
        async def second():
            async with scheduler.serialize('p', 's', 'naming'):
                order.append('second')
        first_task = asyncio.create_task(first())
        await entered.wait()
        second_task = asyncio.create_task(second())
        async with scheduler.serialize('p', 's', 'memory'):
            order.append('memory')
        assert order == ['first', 'memory']
        release.set(); await asyncio.gather(first_task, second_task)
        assert order == ['first', 'memory', 'second']
        assert not scheduler._locks
    asyncio.run(scenario())


def test_cancelling_function_owner_stops_child_run():
    class Manager:
        stopped = False
        async def start(self, request, service):
            return object()
        async def stream(self, subscription):
            yield {'kind': 'noop'}
            raise asyncio.CancelledError
        async def stop(self, project, session):
            assert (project, session) == ('p', 's')
            self.stopped = True
    service = object.__new__(ProjectConversationStreamService)
    service._run_manager = Manager()
    async def scenario():
        with pytest.raises(asyncio.CancelledError):
            await service._run_functional_conversation(ChatCompletionRequest(project_id='p', session_id='s', provider_id='provider', model_id='model', messages=()))
    asyncio.run(scenario())
    assert service._run_manager.stopped


def test_title_tool_uses_sdk_gateway_and_bound_naming_session(naming_attempt, bridge, monkeypatch):
    from app.services.project import conversation_naming
    _, conversations, naming, source, _, created = naming_attempt
    service = service_for(naming_attempt)
    monkeypatch.setattr(conversation_naming, 'get_project_conversation_naming_service', lambda: service)
    grant = issue(bridge.access, tool_name='renamed_submission_tool', project_id=_PROJECT_ID,
                  session_id=created.session.session_id, capabilities=(HostCapability.CONVERSATION_NAMING,))
    monkeypatch.setenv('TIANCE_API_BASE_URL', 'http://testserver/api')
    monkeypatch.setenv('TIANCE_HOST_CAPABILITY_TOKEN', grant.token)
    def urlopen(request, timeout):
        response = bridge.client.request(request.method, urlsplit(request.full_url).path,
            headers=dict(request.header_items()), content=request.data)
        if response.is_error:
            raise HTTPError(request.full_url, response.status_code, 'error', {}, io.BytesIO(response.content))
        return io.BytesIO(response.content)
    monkeypatch.setattr(tiance_runtime, 'urlopen', urlopen)
    root = Path(__file__).resolve().parents[2] / 'Data/tools/ffcfb307-05b2-5b3d-86fb-deb99b786462'
    spec = importlib.util.spec_from_file_location('title_submission_test', root / 'program/main.py')
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    naming.claim_task(_PROJECT_ID, created.session.session_id)
    from tests.test_tool_execution import _FakeRegistry
    from app.services.tools.tool_execution import ToolExecutionService, ToolExecutionContext
    tokens = []
    def command_runner(command, input_text, cwd, env, timeout_seconds):
        tokens.append(env['TIANCE_HOST_CAPABILITY_TOKEN'])
        monkeypatch.setenv('TIANCE_HOST_CAPABILITY_TOKEN', tokens[-1])
        output = io.StringIO()
        exit_code = tiance_runtime.run_tool(tool.run, input_stream=io.StringIO(input_text), output_stream=output, exit_process=False)
        return SimpleNamespace(returncode=exit_code, stdout=output.getvalue(), stderr='')
    executor = ToolExecutionService(_FakeRegistry(root), command_runner=command_runner, host_capability_access=bridge.access)
    result = executor.execute(ChatToolCall(call_id='submit-title', name='submit_conversation_title', arguments='{"title":"会议纪要整理"}'),
        context=ToolExecutionContext(project_id=_PROJECT_ID, session_id=created.session.session_id,
                                     enabled_tool_names=('submit_conversation_title',)))
    assert result.ok, result.error
    assert json.loads(result.content)['applied'] is True
    assert bridge.access.authorize(tokens[0], HostCapability.CONVERSATION_NAMING) is None
    assert conversations.get_session(_PROJECT_ID, source.session_id).title == '会议纪要整理'
    path = '/api/tools/capabilities/conversation-naming'
    assert bridge.client.post(path, json={'title': '伪造', 'session_id': source.session_id}, headers=headers(grant)).status_code == 422
    wrong_grant = issue(bridge.access)
    assert bridge.client.post(path, json={'title': '越权'}, headers=headers(wrong_grant)).status_code == 401
    ordinary_grant = issue(bridge.access, project_id=_PROJECT_ID, session_id=source.session_id,
                           capabilities=(HostCapability.CONVERSATION_NAMING,))
    assert bridge.client.post(path, json={'title': '普通会话不能自动命名'}, headers=headers(ordinary_grant)).status_code == 409
    bridge.access.revoke(grant.token)
    assert bridge.client.post(path, json={'title': '过期'}, headers=headers(grant)).status_code == 401


def test_naming_prompt_upgrade_keeps_custom_rules():
    from app.migrations.functional_settings import convert
    prompt = '我自己的标题规则。\n调用 manage_ai_conversations。\naction 必须使用 name_parent_session。\n最多十个字。'
    version, settings = convert('naming', 28, {'prompt': prompt, 'triggerTokenThreshold': 8765})
    assert version == 29
    assert settings['triggerTokenThreshold'] == 8765
    assert settings['prompt'] == '我自己的标题规则。\n调用 submit_conversation_title。\n最多十个字。'


def test_pending_task_respects_manual_title(naming_attempt):
    _, conversations, naming, source, _, created = naming_attempt
    directory = naming._session_store.require_session_dir(_PROJECT_ID, source.session_id, for_write=True)
    naming._session_store.write_session(directory, replace(source, title='用户指定标题', manual_title=True))
    assert naming.claim_task(_PROJECT_ID, created.session.session_id) is None
    assert read_document(task_dir(naming_attempt), 'automatic_naming_task')['status'] == 'superseded'
    assert conversations.get_session(_PROJECT_ID, source.session_id).title == '用户指定标题'


def test_startup_recovers_existing_tasks_without_frontend_or_empty_database_creation(naming_attempt, monkeypatch, tmp_path):
    from app.services.project import conversation_functional_recovery as recovery, conversation_stream
    from app.services.project.conversation_background_tasks import ConversationBackgroundTaskRegistry
    projects, conversations, naming, source, _, created = naming_attempt
    service = service_for(naming_attempt)
    async def run(request):
        naming.apply_title(_PROJECT_ID, request.session_id, title='启动后完成命名')
    service.set_functional_conversation_runner(run)
    empty = tmp_path / 'empty-project'
    empty.mkdir()
    monkeypatch.setattr(conversation_stream, 'get_project_conversation_stream_service', lambda: None)
    monkeypatch.setattr(recovery, 'get_project_repository', lambda: SimpleNamespace(list_projects=lambda: (
        projects.project, SimpleNamespace(project_id='empty', root_path=str(empty)),
    )))
    monkeypatch.setattr(recovery, 'get_project_conversation_naming_service', lambda: service)
    monkeypatch.setattr(recovery, 'get_project_conversation_naming_repository', lambda: naming)
    registry = ConversationBackgroundTaskRegistry()
    monkeypatch.setattr(recovery, 'get_conversation_background_task_registry', lambda: registry)
    async def scenario():
        await recovery.resume_pending_functional_tasks()
        assert set(registry._tasks) == {(_PROJECT_ID, source.session_id)}
        await asyncio.gather(*(task for tasks in registry._tasks.values() for task in tasks))
        await recovery.resume_pending_functional_tasks()
        assert not registry._tasks
    asyncio.run(scenario())
    assert not (empty / '.Tiance').exists()
    assert conversations.get_session(_PROJECT_ID, source.session_id).title == '启动后完成命名'
