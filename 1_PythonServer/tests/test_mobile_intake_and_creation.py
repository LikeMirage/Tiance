"""Exercise shared intake and numeric creation, not just standalone transports."""
import asyncio
import base64
from contextlib import asynccontextmanager
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from tests.test_mobile_access import host, repository
from app.services.mobile import context, navigation, wechat_media, feishu_transport
from app.services.mobile.wechat_navigation import WeChatNavigation
from app.services.mobile.wechat_transport import WeChatTransport, normalize_message

TARGET = {'project_id': 'p', 'session_id': 's'}
PEER = 'wechat:12:user:user'


def setup_wechat(host):
    host.platform, host.label = 'wechat', '微信'
    host.navigation = WeChatNavigation(host)


async def drain(host):
    while host.work:
        await asyncio.gather(*list(host.work))


@pytest.mark.parametrize('platform', ['wechat', 'feishu'])
@pytest.mark.parametrize('kind', ['file', 'voice'])
def test_real_transport_saves_into_fresh_intake_directory(host, tmp_path, monkeypatch, platform, kind):
    content = bytes(range(256)) * 1025 + b'original tail'
    filename = '非全专硕课第十周_产业政策的条件性命题.pptx' if kind == 'file' else 'recording.speex'
    host.platform = platform
    host.label = {'wechat': '微信', 'feishu': '飞书'}[platform]
    if platform == 'wechat':
        host.navigation = WeChatNavigation(host)
        source, encrypted = tmp_path / 'source', tmp_path / 'encrypted'
        source.write_bytes(content)
        key = bytes(range(16))
        wechat_media.encrypt_file(source, encrypted, key)
        response_bytes = encrypted.read_bytes()
        item = {'media': {'aes_key': base64.b64encode(key.hex().encode()).decode(),
                          'encrypt_query_param': 'test-resource'}}
        item.update({'file_name': filename} if kind == 'file' else {'encode_type': 4})
        event = normalize_message({'message_type': 1, 'message_id': '7526540469300687112',
                                   'from_user_id': 'user', 'item_list': [
                                       {'type': 4 if kind == 'file' else 3,
                                        'file_item' if kind == 'file' else 'voice_item': item}]})
        media = event['media'][0]
        filename = media['file_name']
        transport, module = WeChatTransport('test-token'), wechat_media
    else:
        response_bytes = content
        media = {'file_key': 'file', 'message_id': 'message', 'type': 'file', 'file_name': filename}
        transport, module = feishu_transport.FeishuTransport('app', 'secret'), feishu_transport
        transport.access_token = AsyncMock(return_value='test-token')

    @asynccontextmanager
    async def lease(_):
        async with httpx.AsyncClient(transport=httpx.MockTransport(
                lambda request: httpx.Response(200, content=response_bytes)), trust_env=False) as client:
            yield client

    monkeypatch.setattr(module, 'get_shared_http_client', lambda: None)
    monkeypatch.setattr(module, 'lease_http_client', lease)
    monkeypatch.setattr(module, 'get_http_timeout', lambda: httpx.Timeout(5))

    async def run():
        assert not (tmp_path / '远程收件').exists()
        for _ in range(2):  # Same filename must not overwrite an earlier upload.
            assert await host.download(PEER, TARGET, media, transport)
        refs = await host.get('staged', host.staging_key(PEER, TARGET))
        assert len(refs) == 2
        paths = [tmp_path / r['reference']['filePath'] for r in refs]
        assert paths[0] != paths[1]
        for path, ref in zip(paths, refs):
            assert path.is_file() and path.read_bytes() == content
            assert path.is_relative_to(tmp_path / '远程收件' / host.label)
            assert ref['reference']['fileName'] == filename
            assert ref['reference']['projectId'] == 'p'
        assert not list((tmp_path / '远程收件').rglob('*.part'))
        assert all('已保存' in ''.join(o['parts']) for _, o in await host.records('outbox'))

    asyncio.run(run())


def test_failed_wechat_download_does_not_block_next_text(host, tmp_path, monkeypatch):
    setup_wechat(host)
    host.transport = WeChatTransport('test-token')
    host.desktop.submit = AsyncMock(return_value='accepted')

    @asynccontextmanager
    async def lease(_):
        async with httpx.AsyncClient(transport=httpx.MockTransport(
                lambda request: httpx.Response(503)), trust_env=False) as client:
            yield client
    monkeypatch.setattr(wechat_media, 'get_shared_http_client', lambda: None)
    monkeypatch.setattr(wechat_media, 'lease_http_client', lease)
    monkeypatch.setattr(wechat_media, 'get_http_timeout', lambda: httpx.Timeout(5))

    async def run():
        await host.put('peers', PEER, {'allowed': True, 'user_id': 'user', 'chat_id': 'user', 'bot_id': 12})
        await host.put('selection', PEER, TARGET)
        await host.put('menus', PEER, {'mode': 'conversation', 'scope': ['project'], 'stack': [], 'options': []})
        event = {'id': 'file', 'user_id': 'user', 'chat_id': 'user', 'text': '', 'media': [{
            'file_name': 'failed.pptx', 'aeskey': bytes(range(16)).hex(),
            'media': {'encrypt_query_param': 'test-resource'}}]}
        await host.dispatch('file', {'channel': host.channel, 'event': event})
        await drain(host)
        assert not await host.get('staged', host.staging_key(PEER, TARGET))
        assert not list((tmp_path / '远程收件').rglob('*.part'))
        assert any('文件接收失败' in ''.join(o['parts']) for _, o in await host.records('outbox'))
        host.desktop.submit.assert_not_awaited()
        await host.dispatch('text', {'channel': host.channel, 'event': dict(event, id='text', media=[], text='你好')})
        await drain(host)
        host.desktop.submit.assert_awaited_once()
        args = host.desktop.submit.call_args.args
        assert args[1] == TARGET and args[2].startswith('你好\n\n') and args[3] == []

    asyncio.run(run())


def test_intake_does_not_recreate_missing_project_or_escape_workspace(host, tmp_path, monkeypatch):
    # A missing project is an error; only the intake subdirectories may be created.
    missing = tmp_path / 'missing-project'
    monkeypatch.setattr(context, 'get_project_service', lambda: NS(get_project=lambda _: NS(root_path=str(missing), project_id='p')))
    with pytest.raises(FileNotFoundError):
        context.incoming_path(TARGET, 'test.txt', '微信')
    assert not missing.exists()
    monkeypatch.setattr(context, 'get_project_service', lambda: NS(get_project=lambda _: NS(root_path=str(tmp_path), project_id='p')))
    outside = tmp_path.parent / (tmp_path.name + '-outside') / 'test.txt'
    with pytest.raises(Exception, match='工作区外'):
        context.incoming_path(TARGET, str(outside), '微信')
    assert not outside.parent.exists()


@pytest.mark.parametrize('command,title', [('7', None), ('/new', None), ('/new 自定义标题', '自定义标题')])
def test_new_conversation_enters_chat_and_next_hello_is_sent(host, monkeypatch, command, title):
    setup_wechat(host)
    new_target = {'project_id': 'p', 'session_id': 'new'}
    created = Mock(return_value=NS(session_id='new'))
    monkeypatch.setattr(context, 'create_conversation', created)
    monkeypatch.setattr(navigation, 'session_children', lambda *args: [
        (NS(session_id=str(i), title=f'会话{i}'), None) for i in range(6)])
    host.desktop.submit = AsyncMock(return_value='accepted')

    async def run():
        await host.put('peers', PEER, {'allowed': True, 'user_id': 'user', 'chat_id': 'user', 'bot_id': 12})
        await host.navigation.action(PEER, 'sessions', target={'project_id': 'p'})
        before = await host.navigation.state(PEER)
        assert (await host.get('callbacks', before['options'][6]))['action'] == 'new'
        assert await host.navigation.consume(PEER, command, {})
        created.assert_called_once()
        project_id, request = created.call_args.args
        assert project_id == 'p' and request.activate is False and request.created_by == 'user'
        assert request.title == title  # Shared creation supplies the default title.
        assert ('title' in request.model_fields_set) == (title is not None)
        state = await host.navigation.state(PEER)
        assert state['mode'] == 'conversation' and 'pending' not in state
        assert await host.get('selection', PEER) == new_target
        assert not any('请发送新名称' in ''.join(o['parts']) for _, o in await host.records('outbox'))
        await host.dispatch('text', {'channel': host.channel, 'event': {
            'id': 'text', 'user_id': 'user', 'chat_id': 'user', 'text': '你好', 'media': []}})
        await drain(host)
        created.assert_called_once()  # Hello is not used to create another session.
        host.desktop.submit.assert_awaited_once()
        args = host.desktop.submit.call_args.args
        assert args[1] == new_target and args[2].startswith('你好\n\n')

    asyncio.run(run())


def test_failed_creation_keeps_menu_and_original_selection(host, monkeypatch):
    setup_wechat(host)
    monkeypatch.setattr(navigation, 'session_children', lambda *args: [])
    monkeypatch.setattr(context, 'create_conversation', Mock(side_effect=ValueError('creation failed')))

    async def run():
        await host.put('selection', PEER, TARGET)
        await host.navigation.action(PEER, 'sessions', target={'project_id': 'p'})
        before = await host.navigation.state(PEER)
        with pytest.raises(ValueError, match='creation failed'):
            await host.navigation.consume(PEER, '/new', {})
        assert await host.navigation.state(PEER) == before
        assert await host.get('selection', PEER) == TARGET

    asyncio.run(run())
