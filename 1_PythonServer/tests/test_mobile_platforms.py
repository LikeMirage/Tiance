import asyncio
import base64
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import httpx
import pytest

from tests.test_mobile_access import repository, host
from app.services.mobile import feishu_transport, wechat_media, navigation
from app.services.mobile.feishu_events import normalize_event
from app.services.mobile.feishu_frames import Frame
from app.services.mobile.wechat_transport import normalize_message, trusted_url
from app.services.mobile.wechat_navigation import WeChatNavigation
from app.services.mobile.wechat_login import WeChatLogin

PEER = 'wechat:bot:user:user'
TARGET = {'project_id': 'p', 'session_id': 's'}


def test_wechat_menu_digits_and_chat_digits_have_different_meanings(host, monkeypatch):
    async def run():
        nav = WeChatNavigation(host)
        await host.put('selection', PEER, TARGET)
        await host.put('menus', PEER, {'mode': 'conversation', 'stack': [{'action': 'sessions', 'target': TARGET}], 'options': []})
        assert not await nav.consume(PEER, '2', {})
        assert not await nav.consume(PEER, '000', {})
        assert await nav.message_target(PEER, {}) == TARGET
        nav.action = AsyncMock()
        assert await nav.consume(PEER, '0', {})
        assert (await nav.state(PEER))['mode'] == 'menu'
        nav.action.assert_awaited_once_with(PEER, action='sessions', target=TARGET, _back=True)
        with pytest.raises(Exception, match='进入会话'):
            await nav.message_target(PEER, {})
        button = await nav.button(PEER, '选择', 'select', target=TARGET)
        await host.put('menus', PEER, {'mode': 'menu', 'stack': [], 'options': [button['callback_data']]})
        assert await nav.consume(PEER, '1', {})
        assert nav.action.call_args.args == (PEER,)
        assert nav.action.call_args.kwargs == {'action': 'select', 'target': TARGET}
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


def test_new_in_chat_is_rejected_and_menu_new_prompts_for_name(host):
    async def run():
        nav = WeChatNavigation(host)
        await host.put('menus', PEER, {'mode': 'conversation', 'stack': [{'action': 'sessions', 'target': TARGET}], 'options': []})
        await nav.consume(PEER, '/new', {})
        assert not (await nav.state(PEER)).get('pending')
        await host.put('menus', PEER, {'mode': 'menu', 'stack': [{'action': 'categories', 'kind': 'project'}], 'options': []})
        await nav.consume(PEER, '/new', {})
        assert (await nav.state(PEER))['pending']['action'] == 'newcategory'
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
        manager = NS(lock=asyncio.Lock(), save_platform=save, adapters={'wechat:bot': NS(put=AsyncMock())})
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
        manager.adapters['wechat:bot'].put.assert_awaited_once()
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
