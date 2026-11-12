import asyncio
import base64
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import httpx
import pytest

from tests.test_mobile_access import repository, host
from app.services.mobile import feishu_transport, wechat_media, wechat_transport, navigation, menu_pages
from app.services.mobile.feishu_events import normalize_event
from app.services.mobile.feishu_frames import Frame
from app.services.mobile.wechat_transport import normalize_message, trusted_url
from app.services.mobile.wechat_navigation import WeChatNavigation
from app.services.mobile.wechat_login import WeChatLogin

PEER = 'wechat:bot:user:user'
TARGET = {'project_id': 'p', 'session_id': 's'}


def test_wechat_menu_digits_and_chat_digits_have_different_meanings(host, monkeypatch):
    monkeypatch.setattr(menu_pages, 'session_children', lambda *args: [])
    async def run():
        nav = WeChatNavigation(host)
        host.platform, host.navigation = 'wechat', nav
        await host.put('selection', PEER, TARGET)
        await nav.menus.enter(PEER, 'select', {'target': TARGET})
        assert not await nav.consume(PEER, '2', {})
        assert not await nav.consume(PEER, '000', {})
        assert await nav.message_target(PEER, {}) == TARGET
        nav.action = AsyncMock(wraps=nav.action)
        assert await nav.consume(PEER, '0', {})
        assert (await nav.state(PEER))['mode'] == 'menu'
        nav.action.assert_any_await(PEER, 'back')
        with pytest.raises(Exception, match='进入会话'):
            await nav.message_target(PEER, {})
        button = await nav.button(PEER, '选择', 'select', target=TARGET)
        trail = (await nav.state(PEER))['stack']
        nav.action = AsyncMock()
        await host.put('menus', PEER, {'mode': 'menu', 'scope': ['project'], 'stack': [], 'options': [button['callback_data']]})
        assert await nav.consume(PEER, '1', {})
        assert nav.action.call_args.args == (PEER,)
        assert nav.action.call_args.kwargs == {'action': 'select', 'target': TARGET, '_trail': trail}
        with pytest.raises(Exception, match='失效'):
            await nav.choose('another-user', button['callback_data'])
    asyncio.run(run())


def test_async_reply_cannot_overwrite_numeric_menu(host, monkeypatch):
    async def run():
        nav = WeChatNavigation(host)
        host.navigation = nav
        waiting = asyncio.Event()
        worker = None
        async def action(self, peer, name, **kwargs):
            nonlocal worker
            async def late_reply():
                await waiting.wait()
                await host.reply(peer, 'late result', rows=[[await nav.button(peer, 'old', 'status')]])
            worker = asyncio.create_task(late_reply())
            await host.reply(peer, 'menu', rows=[[await nav.button(peer, 'current', 'status')]])
        monkeypatch.setattr(navigation.MobileNavigation, 'action', action)
        await nav.action(PEER, 'collections')
        before = await nav.state(PEER)
        waiting.set()
        await worker
        assert await nav.state(PEER) == before
        assert len(before['options']) == 1
    asyncio.run(run())


def test_wechat_five_selects_menu_item_and_can_name_a_project(host):
    async def run():
        nav = WeChatNavigation(host)
        nav.action = AsyncMock()
        button = await nav.button(PEER, '第五个会话', 'select', target=TARGET)
        await host.put('menus', PEER, {'mode': 'menu', 'scope': ['project'], 'stack': [],
                                     'options': ['a', 'b', 'c', 'd', button['callback_data']]})
        assert await nav.consume(PEER, '5', {})
        nav.action.assert_awaited_once_with(PEER, action='select', target=TARGET, _trail=[])
        nav.action.reset_mock()
        state = await nav.state(PEER)
        state['pending'] = {'action': 'newproject', 'kind': 'project'}
        await host.put('menus', PEER, state)
        assert await nav.consume(PEER, '5', {})
        nav.action.assert_awaited_once_with(PEER, action='newproject', kind='project', title='5')
    asyncio.run(run())


@pytest.mark.parametrize('mode', ['menu', 'conversation'])
def test_wechat_bare_menu_returns_to_collections(host, monkeypatch, mode):
    async def run():
        nav = WeChatNavigation(host)
        host.navigation = nav
        host.config['allowed_collections'] = ['project', 'tool']
        await host.put('selection', PEER, TARGET)
        await host.put('menus', PEER, {'mode': mode, 'scope': ['project', 'tool'],
                                     'stack': [{'action': 'sessions', 'target': TARGET}], 'options': []})
        assert await nav.consume(PEER, 'menu', {})
        state = await nav.state(PEER)
        assert state['mode'] == 'menu'
        assert state['stack'] == [{'action': 'collections', 'page': 0}]
        assert state['options']
        assert await host.get('selection', PEER) == TARGET
    asyncio.run(run())


@pytest.mark.parametrize('text,event', [('5个文件', {}), ('menu说明', {}), ('05', {}),
                                      ('000', {}), ('00秒', {}),
                                      ('00', {'media': [{'file_id': 'file'}]}),
                                      ('5', {'media': [{'file_id': 'file'}]}),
                                      ('menu', {'media': [{'file_id': 'file'}]})])
def test_wechat_shortcuts_do_not_consume_normal_text_or_file_captions(host, text, event):
    async def run():
        nav = WeChatNavigation(host)
        await host.put('menus', PEER, {'mode': 'conversation', 'scope': ['project'], 'stack': [], 'options': []})
        nav.action = AsyncMock()
        assert not await nav.consume(PEER, text, event)
        nav.action.assert_not_awaited()
    asyncio.run(run())


@pytest.mark.parametrize('stopped', [True, False])
def test_wechat_double_zero_pauses_selected_conversation_without_leaving_chat(host, stopped):
    async def run():
        nav = WeChatNavigation(host)
        host.navigation = nav
        await host.put('selection', PEER, TARGET)
        state = {'mode': 'conversation', 'scope': ['project'], 'stack': [], 'options': []}
        await host.put('menus', PEER, state)
        host.desktop.stop = AsyncMock(return_value=stopped)
        assert await nav.consume(PEER, '00', {})
        assert await nav.state(PEER) == state
        # A later selection must not redirect the asynchronous stop request.
        await host.put('selection', PEER, dict(TARGET, session_id='other'))
        await asyncio.gather(*host.work)
        host.desktop.stop.assert_awaited_once_with(TARGET, None)
        replies = [item for _, item in await host.records('outbox')]
        assert all(item['target'] == TARGET for item in replies)
        assert any('00 暂停' in item['parts'][0] for item in replies)
        expected = '已暂停。' if stopped else '这次任务已经结束，没有暂停其他任务。'
        assert any(expected in item['parts'][0] for item in replies)
    asyncio.run(run())


def test_wechat_double_zero_in_menu_does_not_pause_and_can_be_a_name(host):
    async def run():
        nav = WeChatNavigation(host)
        host.navigation = nav
        nav.action = AsyncMock()
        state = {'mode': 'menu', 'scope': ['project'], 'stack': [{'action': 'sessions', 'target': TARGET}], 'options': []}
        await host.put('menus', PEER, state)
        assert await nav.consume(PEER, '00', {})
        nav.action.assert_awaited_once_with(PEER, action='sessions', target=TARGET)
        nav.action.reset_mock()
        state['pending'] = {'action': 'newcategory', 'kind': 'project'}
        await host.put('menus', PEER, state)
        assert await nav.consume(PEER, '00', {})
        nav.action.assert_awaited_once_with(PEER, action='newcategory', kind='project', title='00')
    asyncio.run(run())


def test_invalid_selection_does_not_enter_conversation(host, monkeypatch):
    async def fail(*args, **kwargs):
        raise ValueError('target deleted')
    async def run():
        nav = WeChatNavigation(host)
        before = await nav.state(PEER)
        monkeypatch.setattr(navigation.MobileNavigation, 'action', fail)
        with pytest.raises(ValueError):
            await nav.action(PEER, 'select', target=TARGET)
        assert await nav.state(PEER) == before
    asyncio.run(run())


@pytest.mark.parametrize('page,action', [('categories', 'newcategory'), ('projects', 'newproject')])
def test_new_in_chat_is_rejected_and_project_or_category_prompts_for_name(host, page, action):
    async def run():
        nav = WeChatNavigation(host)
        await host.put('menus', PEER, {'mode': 'conversation', 'scope': ['project'], 'stack': [{'action': 'sessions', 'target': TARGET}], 'options': []})
        await nav.consume(PEER, '/new', {})
        assert not (await nav.state(PEER)).get('pending')
        await host.put('menus', PEER, {'mode': 'menu', 'scope': ['project'], 'stack': [{'action': page, 'kind': 'project'}], 'options': []})
        await nav.consume(PEER, '/new', {})
        assert (await nav.state(PEER))['pending']['action'] == action
    asyncio.run(run())


def test_feishu_private_text_media_and_card_normalization():
    event = {'header': {'event_type': 'im.message.receive_v1', 'event_id': 'e'}, 'event': {
        'sender': {'sender_type': 'user', 'sender_id': {'open_id': 'u'}},
        'message': {'chat_type': 'p2p', 'chat_id': 'c', 'message_id': 'm', 'message_type': 'audio', 'content': '{"file_key":"f"}'}}}
    normalized = normalize_event(event)
    assert normalized['media'][0] == {'file_key': 'f', 'message_id': 'm', 'type': 'file', 'file_name': 'm.opus'}
    event['event']['message']['chat_type'] = 'group'
    assert normalize_event(event) is None
    card = {'header': {'event_type': 'card.action.trigger', 'event_id': 'c'}, 'event': {
        'operator': {'open_id': 'u'}, 'context': {'open_chat_id': 'c'}, 'action': {'value': {'tiance': 'owned-token'}}}}
    assert normalize_event(card)['callback'] == 'owned-token'


def test_wechat_media_and_unknown_events_are_explicit():
    event = normalize_message({'message_type': 1, 'message_id': 1, 'from_user_id': 'u', 'context_token': 'reply',
        'item_list': [{'type': 3, 'voice_item': {'encode_type': 6, 'media': {'aes_key': 'x'}}},
                      {'type': 5, 'video_item': {'media': {'aes_key': 'y'}}}]})
    assert event['media'][0]['file_name'].endswith('.silk')
    assert event['media'][1]['file_name'].endswith('.mp4')
    assert event['context']['context_token'] == 'reply'
    with pytest.raises(Exception, match='唯一标识'):
        normalize_message({'message_type': 1, 'from_user_id': 'u'})
    for bad in ['https://weixin.qq.com.attacker.org/file', 'http://ilinkai.weixin.qq.com', 'https://a:b@ilinkai.weixin.qq.com']:
        with pytest.raises(Exception): trusted_url(bad)


@pytest.mark.parametrize('read_timeout', [5, 60])
@pytest.mark.parametrize('method,get', [('get_qrcode_status', True), ('getupdates', False)])
def test_wechat_long_poll_reaches_http_with_preserved_timeouts(monkeypatch, read_timeout, method, get):
    configured = httpx.Timeout(connect=7, read=read_timeout, write=11, pool=13)
    monkeypatch.setattr(wechat_transport, 'get_http_timeout', lambda: configured)
    requests = []
    body = {'status': 'wait'} if get else {'msgs': []}

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json=body)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond), trust_env=False) as client:
            monkeypatch.setattr(wechat_transport, 'get_shared_http_client', lambda: client)
            transport = wechat_transport.WeChatTransport(token='test-token')
            result = await transport.call(method, auth=not get, get=get, poll=True,
                                          params={'qrcode': 'test-code'} if get else None)
            assert result == body

    asyncio.run(run())
    assert len(requests) == 1
    assert requests[0].method == ('GET' if get else 'POST')
    assert requests[0].extensions['timeout'] == {
        'connect': 7, 'read': max(read_timeout, 40), 'write': 11, 'pool': 13,
    }
    assert configured.read == read_timeout


def test_encrypted_media_roundtrip_and_corruption_does_not_save(tmp_path, monkeypatch):
    monkeypatch.setattr(wechat_media, 'get_http_timeout', lambda: httpx.Timeout(5))
    source, encrypted, destination = (tmp_path / n for n in ['input', 'encrypted', 'output'])
    source.write_bytes(bytes(range(256)) * 2033 + b'tail')
    key = bytes(range(16))
    size, _ = wechat_media.encrypt_file(source, encrypted, key)
    assert size == source.stat().st_size
    encrypted_bytes = encrypted.read_bytes()
    @asynccontextmanager
    async def lease(_):
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=encrypted_bytes))) as client:
            yield client
    monkeypatch.setattr(wechat_media, 'get_shared_http_client', lambda: None)
    monkeypatch.setattr(wechat_media, 'lease_http_client', lease)
    media = {'media': {'aes_key': base64.b64encode(key.hex().encode()).decode(), 'encrypt_query_param': 'param'}}
    asyncio.run(wechat_media.download_file(media, destination))
    assert destination.read_bytes() == source.read_bytes()
    encrypted_bytes = encrypted_bytes[:-1]
    destination.unlink()
    with pytest.raises(ValueError): asyncio.run(wechat_media.download_file(media, destination))
    assert not destination.exists() and not destination.with_suffix('.part').exists()


def test_qr_confirmed_is_not_visible_until_saved(monkeypatch):
    async def run():
        saving, release = asyncio.Event(), asyncio.Event()
        async def save(*args):
            saving.set()
            await release.wait()
            return 'wechat:bot'
        manager = NS(lock=asyncio.Lock(), save_platform=save, adapters={'wechat:bot': NS(confirm_peer=AsyncMock())})
        login = WeChatLogin(manager)
        import time
        login.state = {'id': 'id', 'status': 'wait', 'expires_at': time.time()+30}
        from app.services.mobile import wechat_login
        monkeypatch.setattr(wechat_login, 'encrypt_secret', lambda x: 'encrypted')
        transport = NS(base='https://ilinkai.weixin.qq.com', call=AsyncMock(return_value={
            'status': 'confirmed', 'bot_token': 'never-return', 'ilink_bot_id': 'bot', 'ilink_user_id': 'owner'}))
        task = asyncio.create_task(login.poll(transport, 'code'))
        await saving.wait()
        assert login.status('id')['status'] == 'saving'
        release.set()
        await task
        assert login.status('id')['connection_id'] == 'wechat:bot'
        assert login.status('id')['status'] == 'confirmed'
        assert 'never-return' not in json.dumps(login.status('id'))
        manager.adapters['wechat:bot'].confirm_peer.assert_awaited_once()
    asyncio.run(run())


def test_feishu_fragment_ack_waits_for_persist(monkeypatch):
    monkeypatch.setattr(feishu_transport, 'get_http_timeout', lambda: httpx.Timeout(5))
    monkeypatch.setattr(feishu_transport, 'get_network_proxy_url', lambda: None)
    import websockets
    async def run():
        payload = json.dumps({'header': {'event_type': 'card.action.trigger', 'event_id': 'id'}, 'event': {
            'operator': {'open_id': 'u'}, 'context': {'open_chat_id': 'c'}, 'action': {'value': {'tiance': 'a'}}}}).encode()
        frames = []
        for n, part in enumerate([payload[:50], payload[50:]]):
            frame = Frame(SeqID=2, LogID=1, service=3, method=1, payload=part)
            for key, value in {'type': 'event', 'sum': '2', 'seq': str(n), 'message_id': 'mid'}.items():
                frame.headers.add(key=key, value=value)
            frames.append(frame.SerializeToString())
        socket = NS(send=AsyncMock(), recv=AsyncMock(side_effect=frames + [RuntimeError('done')]))
        @asynccontextmanager
        async def connect(*args, **kwargs): yield socket
        monkeypatch.setattr(websockets, 'connect', connect)
        transport = feishu_transport.FeishuTransport('app', 'secret')
        transport.request = AsyncMock(return_value={'data': {'URL': 'wss://msg.feishu.cn?service_id=3'}})
        iterator = transport.events(None)
        assert await anext(iterator) is None
        event = await anext(iterator)
        assert event['id'] == 'id'
        assert not any(Frame.FromString(c.args[0]).payload == b'{"code":200}' for c in socket.send.call_args_list)
        with pytest.raises(RuntimeError, match='done'): await anext(iterator)
        assert any(Frame.FromString(c.args[0]).payload == b'{"code":200}' for c in socket.send.call_args_list)
    asyncio.run(run())
