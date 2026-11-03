from __future__ import annotations

import asyncio
import json
import sqlite3
from threading import Event

import pytest

from app.core.errors import BadRequestError
from app.domain.llm.chat import ChatCompletionRequest, ChatMessage, ChatMessageRole
from app.repositories.project.conversation_repository import ProjectConversationRepository
from app.repositories.project.conversation_data_view_repository import ConversationDataViewRepository
from app.services.project.project_conversations import ProjectConversationService
from app.services.project.conversation_audit import ConversationAuditService
from app.services.project.conversation_stream import ProjectConversationStreamService
from tests.test_conversation_database import _Projects
from tests.test_chat_stream_cancellation import _FakeUsageService, _FakeNamingService, _FakeMemoryService


def setup_run(tmp_path, chat=None):
    projects = _Projects(tmp_path)
    repo = ProjectConversationRepository(projects)
    session = repo.create_session('project-1', title='submission', provider_id='deepseek',
                                  model_id='model', reasoning_mode=None)
    service = ProjectConversationStreamService(chat, ProjectConversationService(repo),
        _FakeUsageService(), _FakeNamingService(), _FakeMemoryService())
    service._audit_service = ConversationAuditService(projects)
    request = ChatCompletionRequest(provider_id='deepseek', model_id='model',
        project_id='project-1', session_id=session.session_id,
        messages=(ChatMessage(role=ChatMessageRole.USER, content='submitted input', message_id='client-1'),))
    return projects, repo, service, request


async def collect(service, request):
    events = []
    try:
        async for event in service.stream_payloads(request):
            events.append(event)
    except RuntimeError:
        pass  # Unexpected internal errors are still raised after durable settlement.
    await service._audit_service.close()
    return events


def test_local_preparation_failure_survives_reload_and_retry_is_idempotent(tmp_path, monkeypatch):
    projects, repo, service, request = setup_run(tmp_path)
    calls = []
    async def fail_preparation(value):
        calls.append(value)
        raise RuntimeError('Provider model field is required: displayName')
    monkeypatch.setattr(service, '_prepare_image_references', fail_preparation)
    events = asyncio.run(collect(service, request))
    assert [e['kind'] for e in events] == ['conversation_run_started', 'conversation_run_settled', 'error']
    assert events[-1]['error'] == 'Provider model field is required: displayName'
    reloaded = ProjectConversationRepository(projects)
    page = reloaded.list_messages_page('project-1', request.session_id, limit=20)
    assert [m.content for m in page.items] == ['submitted input']
    assert page.run_outcomes[0].status == 'error'
    assert page.run_outcomes[0].error_message == events[-1]['error']
    assert page.run_outcomes[0].attempt_count == 0
    view = ConversationDataViewRepository(projects).read('project-1',
        name='request_submissions.jsonl', session_id=request.session_id, page=1, page_size=20)
    receipt = json.loads(view.content)
    assert receipt['request']['preview_source'] == 'submitted_request'
    assert receipt['request_snapshot']['messages'][-1]['content'] == 'submitted input'
    assert receipt['outcome']['error_message'] == events[-1]['error']
    with sqlite3.connect(tmp_path / '.Tiance' / 'tiance.db') as db:
        assert db.execute("select count(*) from conversation_session_events where kind='request_submissions'").fetchone()[0] == 1
        assert db.execute('select count(*) from conversation_artifacts').fetchone()[0] == 0
        assert db.execute("select count(*) from conversation_journal where event_type='conversation.run.error'").fetchone()[0] == 1
    retry = asyncio.run(collect(service, request))
    assert retry[-1]['error'] == events[-1]['error']
    assert len(calls) == 1
    assert len(reloaded.list_messages('project-1', request.session_id)) == 1


def test_failed_submission_commit_rolls_back_input_and_run(tmp_path, monkeypatch):
    _, repo, service, request = setup_run(tmp_path)
    def fail(*args, **kwargs):
        raise OSError('submission disk failure')
    monkeypatch.setattr('app.repositories.project.conversation_repository.append_event', fail)
    events = asyncio.run(collect(service, request))
    assert [e['kind'] for e in events] == ['error']
    assert events[0]['error'] == 'submission disk failure'
    assert repo.list_messages('project-1', request.session_id) == ()
    with sqlite3.connect(tmp_path / '.Tiance' / 'tiance.db') as db:
        assert db.execute('select count(*) from conversation_runs').fetchone()[0] == 0


def test_no_response_model_failure_still_has_complete_logical_request(tmp_path):
    class Chat:
        async def stream(self, request):
            raise BadRequestError('model unavailable')
            yield
    projects, repo, service, request = setup_run(tmp_path, Chat())
    events = asyncio.run(collect(service, request))
    assert events[-1]['error'] == 'model unavailable'
    from app.repositories.project.conversation_database import read_events
    path = tmp_path / '.Tiance' / 'conversations' / 'sessions' / request.session_id
    exchanges = read_events(path, 'model_exchanges')
    assert len(exchanges) == 1
    assert exchanges[0]['response'] is None
    assert exchanges[0]['status'] == 'error'
    assert exchanges[0]['error']['message'] == 'model unavailable'
    assert exchanges[0]['request_snapshot']['messages'][-1]['content'].endswith('submitted input')


def test_cancel_during_preparation_settles_accepted_submission(tmp_path, monkeypatch):
    _, repo, service, request = setup_run(tmp_path)
    async def run():
        preparing = asyncio.Event()
        async def wait(value):
            preparing.set()
            await asyncio.Event().wait()
        monkeypatch.setattr(service, '_prepare_image_references', wait)
        events=[]
        async def consume():
            async for event in service.stream_payloads(request): events.append(event)
        task=asyncio.create_task(consume())
        await asyncio.wait_for(preparing.wait(), 3)
        task.cancel()
        with pytest.raises(asyncio.CancelledError): await task
        return events
    events=asyncio.run(run())
    assert events[-1]['status'] == 'cancelled'
    page=repo.list_messages_page('project-1', request.session_id, limit=20)
    assert repo.get_run('project-1', request.session_id, 'run_client-1').status == 'cancelled'
    assert len(page.items) == 1


def test_logical_audit_disk_failure_is_visible_and_retried_on_close(tmp_path):
    projects = _Projects(tmp_path)
    audit = ConversationAuditService(projects)
    calls=[]
    async def execute():
        async def write():
            calls.append(1)
            if len(calls) == 1: raise OSError('audit disk failure')
        task=audit.create_session_task('project-1', 'session-1', write, name='logical-request')
        with pytest.raises(OSError): await task
        assert len(audit._failed_session_writes) == 1
        await audit.close()
        assert not audit._failed_session_writes
    asyncio.run(execute())
    assert len(calls) == 2


def test_cancel_during_receipt_commit_keeps_identifiers_and_settles_run(tmp_path, monkeypatch):
    _, repo, service, request = setup_run(tmp_path)
    accepting, release = Event(), Event()
    original = repo.accept_submission

    def delayed(*args, **kwargs):
        accepting.set()
        assert release.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(repo, 'accept_submission', delayed)

    async def run():
        async def consume():
            async for _ in service.stream_payloads(request):
                pass
        task = asyncio.create_task(consume())
        try:
            assert await asyncio.to_thread(accepting.wait, 3)
            task.cancel()
        finally:
            release.set()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())
    assert repo.get_run('project-1', request.session_id, 'run_client-1').status == 'cancelled'
    assert len(repo.list_messages('project-1', request.session_id)) == 1
