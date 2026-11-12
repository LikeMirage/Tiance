import asyncio
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from tests.test_external_messaging import repo
from app.api.routes.tools import host_capabilities as api
from app.api.routes.tools.host_capabilities import ExternalMessagingRequest
from app.core.errors import BadRequestError
from app.domain.tools.host_capabilities import HostCapability
from app.services.mobile import messaging, service
from app.services.mobile.telegram_transport import TelegramSendError
from app.services.tools.host_capability_access import HostCapabilityAccessService


@pytest.fixture(params=['telegram', 'feishu', 'wechat'])
def platform(request):
    return request.param


def setup_sender(repo, monkeypatch, platform, send):
    key = f'{platform}:test-bot'
    repo.save_connection(key, platform, 'test-bot', {
        'enabled': True, 'token': 'secret', 'api_base': 'https://api.telegram.org',
        'bot': {'id': 'test-bot'},
    })
    transport = NS(send_once=send, send=send, send_items=send, send_file=send)
    monkeypatch.setattr(messaging, 'TelegramTransport', lambda *_: transport)
    monkeypatch.setattr(messaging, 'decrypt_secret', lambda _: 'secret')
    for cls in (service.FeishuService, service.WeChatService):
        monkeypatch.setattr(cls, 'make_transport', lambda *_: transport)
    scoped = repo.scoped(key)
    if platform == 'wechat':
        scoped.put('peers', 'recipient', {'chat_id': 'target'})
        scoped.put('reply_context', 'recipient', {'context_token': 'reply-token'})
    return key


def request(platform, key, text):
    return ExternalMessagingRequest(action='send_text', platform=platform,
                                    connection_id=key, chat_id='target', text=text)


def test_text_is_complete_explicit_and_one_way(repo, monkeypatch, platform):
    async def run():
        send = AsyncMock(side_effect=lambda *a, **kw: {'message_id': send.await_count})
        key = setup_sender(repo, monkeypatch, platform, send)
        monkeypatch.setattr(messaging, 'target_header', lambda _: '项目 A / 会话 B')
        monkeypatch.setattr(Path, 'is_file', lambda *_: pytest.fail('text must not access a file'))
        # Existing routing, a pending input and output must not be consumed or changed.
        scoped = repo.scoped(key)
        for namespace in ('selection', 'navigation', 'inbox', 'outbox', 'jobs', 'messages'):
            scoped.put(namespace, 'keep', {'content': 'unchanged'})
        text = '  已完成一半。\n<不是 HTML> **普通文字** 😀' * 300
        result = await messaging.execute(repo, request(platform, key, text), NS(project_id='p', session_id='s'))
        assert result['ok'] and result['status'] == 'sent'
        assert send.await_count > 1
        parts = []
        for call in send.await_args_list:
            args = call.args
            if platform == 'telegram':
                assert args[0] == 'sendMessage'
                assert args[1]['chat_id'] == 'target' and 'parse_mode' not in args[1]
                parts.append(args[1]['text'])
            elif platform == 'feishu':
                assert args[:2] == ('target', 'text')
                parts.append(args[2]['text'])
            else:
                assert args[0] == 'target' and args[3] == {'context_token': 'reply-token'}
                parts.append(args[1][0]['text_item']['text'])
        assert ''.join(parts) == '项目 A / 会话 B\n\n' + text
        assert all(len(p.encode('utf-16-le')) // 2 <= 3500 for p in parts)
        assert result['sent_characters'] == result['total_characters'] == len(''.join(parts))
        assert len(result['message_ids']) == send.await_count
        for namespace in ('selection', 'navigation', 'inbox', 'outbox', 'jobs', 'messages'):
            assert scoped.list(namespace) == [('keep', {'content': 'unchanged'})]
    asyncio.run(run())


@pytest.mark.parametrize('confirmed', [False, True])
def test_failed_text_reports_confirmed_parts_without_retry(repo, monkeypatch, platform, confirmed):
    async def run():
        failure = (TelegramSendError('timeout', status='unknown') if platform == 'telegram'
                   else httpx.ReadTimeout('private-token-in-url'))
        send = AsyncMock(side_effect=([{'message_id': 'first'}] if confirmed else []) + [failure])
        key = setup_sender(repo, monkeypatch, platform, send)
        result = await messaging.execute(repo, request(platform, key, '字' * 9000), NS(project_id=None))
        assert result['status'] == ('partial' if confirmed else 'unknown')
        assert not result['ok'] and result['failed_part_status'] == 'unknown'
        assert result['message_ids'] == (['first'] if confirmed else [])
        assert result['sent_characters'] == (3500 if confirmed else 0)
        assert result['total_characters'] == 9000
        assert send.await_count == (2 if confirmed else 1)
        assert 'private-token' not in json.dumps(result)
    asyncio.run(run())


def test_explicit_telegram_rejection_is_not_sent(repo, monkeypatch):
    async def run():
        send = AsyncMock(side_effect=TelegramSendError('rate limited', status='not_sent', retry_after=12))
        key = setup_sender(repo, monkeypatch, 'telegram', send)
        result = await messaging.execute(repo, request('telegram', key, '进度'), NS(project_id=None))
        assert result['status'] == 'not_sent' and result['retry_after_seconds'] == 12
        assert result['message_ids'] == [] and send.await_count == 1
    asyncio.run(run())


def test_text_requires_enabled_connection_and_keeps_platform_isolation(repo, monkeypatch, platform):
    async def run():
        send = AsyncMock()
        key = setup_sender(repo, monkeypatch, platform, send)
        record = repo.connections(platform)[0]
        repo.save_connection(key, platform, 'test-bot', dict(record['config'], enabled=False))
        with pytest.raises(BadRequestError, match='未启用'):
            await messaging.execute(repo, request(platform, key, '进度'), NS(project_id=None))
        other = 'telegram' if platform != 'telegram' else 'wechat'
        with pytest.raises(BadRequestError, match='不存在'):
            await messaging.execute(repo, request(other, key, '进度'), NS(project_id=None))
        send.assert_not_awaited()
    asyncio.run(run())


def test_wechat_text_never_borrows_another_connections_reply_context(repo, monkeypatch):
    async def run():
        send = AsyncMock()
        key = setup_sender(repo, monkeypatch, 'wechat', send)
        repo.scoped(key).delete('reply_context', 'recipient')
        other = repo.scoped('wechat:other')
        other.put('peers', 'other-recipient', {'chat_id': 'target'})
        other.put('reply_context', 'other-recipient', {'context_token': 'other-token'})
        with pytest.raises(BadRequestError, match='回复凭据'):
            await messaging.execute(repo, request('wechat', key, '进度'), NS(project_id=None))
        send.assert_not_awaited()
    asyncio.run(run())


@pytest.mark.parametrize('change', [dict(text=''), dict(text=' \n'), dict(chat_id=''),
                                  dict(connection_id=''), dict(file_path='file'), dict(caption='wrong')])
def test_text_request_rejects_missing_or_ambiguous_input(change):
    body = dict(action='send_text', platform='telegram', connection_id='telegram:1', chat_id='7', text='汇报')
    with pytest.raises(ValidationError):
        ExternalMessagingRequest(**(body | change))


def test_independent_text_tool_needs_no_workspace_or_file(monkeypatch):
    root = Path(__file__).resolve().parents[2] / 'Data/tools/0efca349-3362-5aa1-8f15-203dab248ea2'
    spec = importlib.util.spec_from_file_location('external_text_tool', root / 'program/main.py')
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    calls = []
    monkeypatch.delenv('TIANCE_WORKSPACE_ROOT', raising=False)
    monkeypatch.setattr(tool, 'call_host_capability', lambda *a, **kw: calls.append((a, kw)) or {'ok': True})
    body = dict(action='send_text', platform='telegram', connection_id='telegram:1', chat_id='7', text='  进度\n')
    assert tool.run(body)['ok']
    assert calls[0][0] == ('external_messaging', body)
    assert calls[0][1]['timeout_seconds'] == json.loads((root / '.tool/tool.json').read_text('utf-8'))['runtime']['timeout_seconds']
    with pytest.raises(ValueError, match='text'):
        tool.run(body | {'text': ' '})
    assert len(calls) == 1


def test_text_bridge_requires_declared_capability_for_every_platform(repo, monkeypatch, platform):
    send = AsyncMock(return_value={'message_id': 'accepted'})
    key = setup_sender(repo, monkeypatch, platform, send)
    access = HostCapabilityAccessService()
    monkeypatch.setattr(api, 'get_host_capability_access_service', lambda: access)
    monkeypatch.setattr(service, 'get_mobile_service', lambda: NS(repository=repo))
    app = FastAPI()
    app.include_router(api.router)

    def grant(capability):
        return access.issue_grant(
            tool_name='user-created-messaging-tool', tool_call_id='call',
            provider_id=None, model_id=None, project_id=None, session_id=None,
            lifetime_seconds=60, capabilities=(capability,),
        )

    body = request(platform, key, '任务进度').model_dump(exclude_none=True)
    with TestClient(app) as client:
        url = '/tools/capabilities/external-messaging'
        assert client.post(url, json=body).status_code == 401
        wrong = grant(HostCapability.TOOL_CATALOG)
        assert client.post(url, json=body, headers={'Authorization': 'Bearer ' + wrong.token}).status_code == 401
        send.assert_not_awaited()
        allowed = grant(HostCapability.EXTERNAL_MESSAGING)
        response = client.post(url, json=body, headers={'Authorization': 'Bearer ' + allowed.token})
        assert response.status_code == 200
        assert response.json()['status'] == 'sent'
        assert response.json()['message_ids'] == ['accepted']
        assert 'secret' not in response.text and 'reply-token' not in response.text
        send.assert_awaited_once()
