import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest

from tests.test_mobile_access import repository
from app.core.errors import BadRequestError
from app.services.mobile.manager import MobileAccessService
from app.services.mobile.service import WeChatService, MobileService, FeishuService
from app.services.mobile.feishu_events import normalize_event


@pytest.fixture(params=['wechat', 'telegram', 'feishu'])
def platform(request):
    return request.param


async def accounts(repository, monkeypatch, platform):
    for adapter in (WeChatService, MobileService, FeishuService):
        monkeypatch.setattr(adapter, 'make_transport', lambda *_: NS(call=AsyncMock()))
    manager = MobileAccessService(repository)
    peers = []
    for bot in ('old', 'new'):
        key = await manager.save_platform(platform, bot, {
            'enabled': True, 'token': 'encrypted-test', 'bot': {'id': bot, 'first_name': bot},
        })
        peer = f'{key}:{bot}-user:{bot}-user'
        await manager.adapters[key].put('peers', peer, dict(connection_id=key, platform=platform,
            bot_id=bot, user_id=bot+'-user', chat_id=bot+'-user', name=bot, allowed=True, reviewed=True))
        peers.append(peer)
    return manager, peers


def test_all_accounts_visible_and_revocation_stays_on_selected_connection(repository, monkeypatch, platform):
    async def run():
        manager, (old, new) = await accounts(repository, monkeypatch, platform)
        status = await manager.status(platform=platform)
        assert status['connection_id'] == f'{platform}:new'
        assert len(status['peers']) == 1
        assert {p['id'] for p in status['platform_peers']} == {old, new}
        result = await manager.authorize(old, False, selected_connection_id=f'{platform}:new')
        assert result['connection_id'] == f'{platform}:new'
        assert not await manager.is_authorized(old)
        assert await manager.is_authorized(new)
        for peer, bot, expected in ((old, 'old', 0), (new, 'new', 1)):
            adapter = manager.adapters[f'{platform}:{bot}']
            adapter.navigation.consume = AsyncMock(return_value=True)
            await adapter.dispatch('input-'+bot, {'channel': platform+':'+bot, 'event': {
                'id': '1', 'chat_id': bot+'-user', 'user_id': bot+'-user', 'text': '0', 'media': [],
            }})
            assert adapter.navigation.consume.await_count == expected
        # Restarting adapters reads the same persisted denial, not a QR default.
        restarted = MobileAccessService(repository)
        await restarted.status(f'{platform}:old', platform)
        assert not await restarted.is_authorized(old)
    asyncio.run(run())


@pytest.mark.parametrize('payload_owner', [None, 'another-platform:wrong'])
def test_account_management_uses_stored_connection_ownership(repository, monkeypatch, platform, payload_owner):
    async def run():
        manager, (old, new) = await accounts(repository, monkeypatch, platform)
        # Existing Telegram peers have ownership in the database column but
        # no duplicate connection_id/platform inside the JSON payload.
        for peer in (old, new):
            identity = repository.get('peers', peer)
            identity.pop('connection_id')
            identity.pop('platform')
            if payload_owner:
                identity.update(connection_id=payload_owner, platform='wrong')
            identity['allowed'] = peer == old
            repository.put('peers', peer, identity)
        other_platform = 'wechat' if platform != 'wechat' else 'telegram'
        other_key = await manager.save_platform(other_platform, 'other', {
            'enabled': True, 'token': 'test', 'bot': {'id': 'other'},
        })
        await manager.adapters[other_key].put('peers', 'foreign-peer', {
            'connection_id': f'{platform}:old', 'platform': platform,
            'bot_id': 'other', 'user_id': 'other', 'allowed': True,
        })
        before = dict(repository.list('peers'))
        status = await manager.status(platform=platform)
        peers = {p['id']: p for p in status['platform_peers']}
        assert set(peers) == {old, new}
        assert peers[old]['connection_id'] == f'{platform}:old'
        assert peers[new]['connection_id'] == f'{platform}:new'
        assert peers[old]['platform'] == platform
        assert peers[old]['allowed'] and not peers[new]['allowed']
        assert dict(repository.list('peers')) == before
        assert await manager.is_authorized(old)
        assert not await manager.is_authorized(new)
        result = await manager.authorize(old, False, selected_connection_id=f'{platform}:new')
        assert result['connection_id'] == f'{platform}:new'
        assert not any(p['allowed'] for p in result['platform_peers'])
        await manager.remove_peer(old, selected_connection_id=f'{platform}:new')
        assert repository.get('peers', old) is None
        assert repository.get('peers', new) == before[new]
        assert repository.get('peers', 'foreign-peer') == before['foreign-peer']
    asyncio.run(run())


def test_account_order_survives_each_authorization_change_and_restart(repository, monkeypatch, platform):
    async def run():
        manager, (old, _) = await accounts(repository, monkeypatch, platform)
        adapter = manager.adapters[f'{platform}:old']
        # Include two users on the same bot as well as users of another bot.
        await adapter.put('peers', old + '-second', dict(await adapter.get('peers', old), user_id='second'))
        before = await manager.status(platform=platform)
        order = [peer['id'] for peer in before['platform_peers']]
        local_order = [peer['id'] for peer in (await adapter.status())['peers']]
        for peer in order:
            result = await manager.authorize(peer, False, selected_connection_id=f'{platform}:new')
            assert [item['id'] for item in result['platform_peers']] == order
            assert [item['id'] for item in (await adapter.status())['peers']] == local_order
        refreshed = await manager.status(platform=platform)
        assert not any(peer['allowed'] for peer in refreshed['platform_peers'])
        restarted = MobileAccessService(repository)
        assert [peer['id'] for peer in (await restarted.status(platform=platform))['platform_peers']] == order
    asyncio.run(run())


def test_remove_peer_clears_routing_and_does_not_register_again(repository, monkeypatch, platform):
    async def run():
        manager, (old, new) = await accounts(repository, monkeypatch, platform)
        adapter = manager.adapters[f'{platform}:old']
        for namespace in ('selection', 'navigation', 'menus', 'reply_context'):
            await adapter.put(namespace, old, {'keep': False})
        await adapter.put('staged', old+':p:s', [{'reference': {'id': 'r'}}])
        await adapter.put('messages', old+':10', {'target': {}})
        for namespace in ('callbacks', 'outbox', 'inbox'):
            await adapter.put(namespace, namespace+'-key', {'peer': old})
        # A different user on the same connection and another connection survive.
        await adapter.put('menus', old+'-other', {'keep': True})
        await manager.remove_peer(old, selected_connection_id=f'{platform}:new')
        assert not repository.get('peers', old)
        assert repository.get('peers', new)['allowed']
        assert await adapter.get('menus', old+'-other') == {'keep': True}
        assert not await adapter.get('staged', old+':p:s')
        assert not await adapter.get('callbacks', 'callbacks-key')
        adapter.navigation.consume = AsyncMock(return_value=True)
        await adapter.dispatch('later', {'channel': f'{platform}:old', 'event': {
            'id': '2', 'user_id': 'old-user', 'chat_id': 'old-user', 'text': '1', 'media': [],
        }})
        assert repository.get('peers', old) is None
        assert repository.get('deleted_peers', old) is True
        assert not await adapter.records('outbox')
        adapter.navigation.consume.assert_not_called()
    asyncio.run(run())


def test_delete_connection_stops_receiver_preserves_other_connection_and_dedup(repository, monkeypatch, platform):
    async def run():
        manager, (old, new) = await accounts(repository, monkeypatch, platform)
        adapter = manager.adapters[f'{platform}:new']
        async def wait():
            await asyncio.Event().wait()
        receiver = asyncio.create_task(wait())
        adapter.tasks = [receiver]
        adapter.repository.receive(f'{platform}:new', '1', {'channel': f'{platform}:new'})
        result = await manager.remove_connection(platform, f'{platform}:new')
        assert receiver.cancelled()
        assert f'{platform}:new' not in manager.adapters
        assert result['connection_id'] == f'{platform}:old'
        assert [p['id'] for p in result['platform_peers']] == [old]
        assert not repository.get('peers', new)
        assert not adapter.repository.list('inbox')
        assert not adapter.repository.receive(f'{platform}:new', '1', {})
        await manager.remove_connection(platform, f'{platform}:old')
        result = await manager.status(platform=platform)
        assert result['connection_id'] == ''
        assert result['connections'] == result['platform_peers'] == []
    asyncio.run(run())


def test_remove_does_not_drop_active_job_or_erase_wrong_platform(repository, monkeypatch, platform):
    async def run():
        manager, (old, _) = await accounts(repository, monkeypatch, platform)
        await manager.adapters[f'{platform}:old'].put('jobs', 'job', {'peer': old, 'status': 'running'})
        with pytest.raises(BadRequestError, match='任务'):
            await manager.remove_peer(old)
        with pytest.raises(BadRequestError, match='任务'):
            await manager.remove_connection(platform, f'{platform}:old')
        with pytest.raises(BadRequestError, match='不属于'):
            await manager.remove_connection('telegram' if platform != 'telegram' else 'feishu', f'{platform}:old')
        assert repository.get('jobs', 'job')['status'] == 'running'
        assert await manager.is_authorized(old)
    asyncio.run(run())


def test_authorization_waits_for_accepted_menu_action_and_blocks_next(repository, monkeypatch, platform):
    async def run():
        manager, (old, _) = await accounts(repository, monkeypatch, platform)
        adapter = manager.adapters[f'{platform}:old']
        started, finish = asyncio.Event(), asyncio.Event()
        async def menu(*_):
            started.set()
            await finish.wait()
            return True
        adapter.navigation.consume = AsyncMock(side_effect=menu)
        record = {'channel': f'{platform}:old', 'event': {'id': '1', 'user_id': 'old-user', 'chat_id': 'old-user', 'text': '1'}}
        task = asyncio.create_task(adapter.dispatch('message', record))
        await started.wait()
        revoked = asyncio.create_task(manager.authorize(old, False))
        await asyncio.sleep(.01)
        assert not revoked.done()
        finish.set()
        await task
        await revoked
        await adapter.dispatch('message2', record)
        assert adapter.navigation.consume.await_count == 1
    asyncio.run(run())


def native_record(platform, connection, event_id, callback=None, text='/start'):
    """Exercise platform message/card decoding as well as the shared dispatcher."""
    if platform == 'telegram':
        user = {'id': 123, 'first_name': 'Test user'}
        message = {'message_id': event_id, 'chat': {'id': 123, 'type': 'private'},
                   'from': user, 'text': text}
        update = {'update_id': event_id, 'message': message}
        if callback:
            update = {'update_id': event_id, 'callback_query': {
                'id': str(event_id), 'from': user, 'message': message, 'data': callback}}
        return {'channel': connection, 'update': update}, f'{connection}:123:123'
    event = {'sender': {'sender_type': 'user', 'sender_id': {'open_id': 'ou_user'}},
             'message': {'chat_type': 'p2p', 'chat_id': 'oc_chat', 'message_id': str(event_id),
                         'message_type': 'text', 'content': {'text': text}}}
    kind = 'im.message.receive_v1'
    if callback:
        kind = 'card.action.trigger'
        event = {'operator': {'open_id': 'ou_user'}, 'context': {'open_chat_id': 'oc_chat'},
                 'action': {'value': {'tiance': callback}}}
    decoded = normalize_event({'header': {'event_type': kind, 'event_id': str(event_id)}, 'event': event})
    return {'channel': connection, 'event': decoded}, f'{connection}:oc_chat:ou_user'


@pytest.mark.parametrize('platform', ['telegram', 'feishu'])
def test_native_commands_and_old_buttons_obey_revocation_and_deletion(repository, monkeypatch, platform):
    async def run():
        manager, _ = await accounts(repository, monkeypatch, platform)
        connection = f'{platform}:old'
        adapter = manager.adapters[connection]
        adapter.navigation.action = AsyncMock()
        adapter.submit = AsyncMock()

        async def send(event_id, callback=None, text='/start'):
            record, peer = native_record(platform, connection, event_id, callback, text)
            await adapter.dispatch(str(event_id), record)
            if adapter.work:
                await asyncio.gather(*list(adapter.work))
            return peer

        peer = await send(1)
        assert not await manager.is_authorized(peer)
        adapter.navigation.action.assert_not_awaited()
        await manager.authorize(peer, True, selected_connection_id=f'{platform}:new')
        button = await adapter.navigation.button(peer, '当前会话', 'status')
        callback = button['callback_data']
        await send(2)
        await send(3, callback)
        assert adapter.navigation.action.await_count == 2

        enabled_config = dict(adapter.config)
        await manager.save_platform(platform, 'old', dict(enabled_config, enabled=False))
        await send(31)
        await send(32, callback)
        assert adapter.navigation.action.await_count == 2
        assert not await manager.is_authorized(peer)
        status = await manager.status(f'{platform}:new', platform)
        account = next(item for item in status['platform_peers'] if item['id'] == peer)
        assert account['allowed'] and not account['connection_enabled']
        await manager.save_platform(platform, 'old', enabled_config)

        await manager.authorize(peer, False, selected_connection_id=f'{platform}:new')
        await send(4)
        await send(5, callback)
        await send(6, text='ordinary message after revocation')
        assert adapter.navigation.action.await_count == 2
        adapter.submit.assert_not_awaited()

        await manager.remove_peer(peer, selected_connection_id=f'{platform}:new')
        assert not await adapter.get('callbacks', callback)
        await send(7, callback)
        await send(8)
        assert not await manager.is_authorized(peer)
        assert adapter.navigation.action.await_count == 2
        assert await adapter.get('peers', peer) is None
        assert not await adapter.records('outbox')
        with pytest.raises(BadRequestError, match='不存在'):
            await manager.authorize(peer, True)
        # Re-adding the bot connection is an explicit new setup. A new message
        # may register a pending user, but cannot recover authorization/buttons.
        await manager.remove_connection(platform, connection)
        await manager.save_platform(platform, 'old', enabled_config)
        adapter = manager.adapters[connection]
        adapter.navigation.action = AsyncMock()
        await send(9)
        assert not await manager.is_authorized(peer)
        await manager.authorize(peer, True)
        await send(10, callback)
        adapter.navigation.action.assert_not_awaited()
        await send(11)
        assert adapter.navigation.action.await_count == 1
    asyncio.run(run())


@pytest.mark.parametrize('platform', ['telegram', 'feishu'])
def test_same_sender_on_two_bots_has_separate_authorization(repository, monkeypatch, platform):
    async def run():
        manager, _ = await accounts(repository, monkeypatch, platform)
        peers = []
        for bot in ('old', 'new'):
            connection = f'{platform}:{bot}'
            adapter = manager.adapters[connection]
            adapter.navigation.action = AsyncMock()
            record, peer = native_record(platform, connection, 1)
            await adapter.dispatch(connection + ':input', record)
            await manager.authorize(peer, True)
            peers.append(peer)
        old, new = peers
        await manager.authorize(old, False, selected_connection_id=f'{platform}:new')
        await manager.remove_peer(old, selected_connection_id=f'{platform}:new')
        assert await manager.is_authorized(new)
        for bot, expected in (('old', 0), ('new', 1)):
            record, peer = native_record(platform, f'{platform}:{bot}', 2)
            adapter = manager.adapters[f'{platform}:{bot}']
            await adapter.dispatch(bot + ':again', record)
            assert adapter.navigation.action.await_count == expected
        await manager.remove_connection(platform, f'{platform}:old')
        assert await manager.is_authorized(new)
        restarted = MobileAccessService(repository)
        await restarted.status(platform=platform)
        assert await restarted.is_authorized(new)
        assert not await restarted.is_authorized(old)
    asyncio.run(run())


def test_each_platform_lists_and_deletes_only_its_own_accounts(repository, monkeypatch):
    async def run():
        managers, peers_by_platform = {}, {}
        # All three platforms coexist in one global DB, as in the real app.
        for platform in ('telegram', 'feishu', 'wechat'):
            managers[platform], peers_by_platform[platform] = await accounts(repository, monkeypatch, platform)
        for platform, manager in managers.items():
            status = await manager.status(platform=platform)
            assert {peer['id'] for peer in status['platform_peers']} == set(peers_by_platform[platform])
        await managers['telegram'].remove_connection('telegram', 'telegram:old')
        for platform in ('feishu', 'wechat'):
            status = await managers[platform].status(platform=platform)
            assert {peer['id'] for peer in status['platform_peers']} == set(peers_by_platform[platform])
            for peer in peers_by_platform[platform]:
                assert await managers[platform].is_authorized(peer)
    asyncio.run(run())


def test_deleted_peer_stays_deleted_after_restart_toggle_and_queued_input(repository, monkeypatch, platform):
    async def run():
        manager, (old, _) = await accounts(repository, monkeypatch, platform)
        key = f'{platform}:old'
        adapter = manager.adapters[key]
        # A received event may not yet have been decoded to a peer at deletion.
        record = {'channel': key, 'event': {
            'id': 'queued', 'user_id': 'old-user', 'chat_id': 'old-user',
            'text': '/start', 'media': [{'file_id': 'file'}], 'context': {'token': 'reply-token'},
        }}
        assert adapter.repository.receive(key, 'queued', record)
        await manager.remove_peer(old)
        assert adapter.repository.get('inbox', key + ':queued') is not None
        restarted = MobileAccessService(repository)
        await restarted.status(key, platform)
        adapter = restarted.adapters[key]
        config = dict(adapter.config)
        await restarted.save_platform(platform, 'old', dict(config, enabled=False))
        await restarted.save_platform(platform, 'old', config)
        adapter.reply = AsyncMock()
        adapter.download = AsyncMock()
        adapter.navigation.action = AsyncMock()
        for index in range(3):
            await adapter.dispatch(f'{key}:input-{index}', record)
        assert await adapter.get('peers', old) is None
        assert await adapter.get('reply_context', old) is None
        assert not await adapter.records('staged')
        assert not await adapter.records('outbox')
        adapter.reply.assert_not_awaited()
        adapter.download.assert_not_awaited()
        adapter.navigation.action.assert_not_awaited()
        status = await restarted.status(key, platform)
        assert all(item['id'] != old for item in status['platform_peers'])
        # A genuinely new visitor still appears pending, with no permissions.
        record['event'] = dict(record['event'], user_id='new-visitor', chat_id='new-visitor', media=[])
        await adapter.dispatch(key + ':visitor', record)
        visitor = await adapter.get('peers', key + ':new-visitor:new-visitor')
        assert visitor and not visitor['allowed']
    asyncio.run(run())


def test_deletion_and_confirmation_share_dispatch_lock(repository, monkeypatch, platform):
    async def run():
        manager, (old, _) = await accounts(repository, monkeypatch, platform)
        adapter = manager.adapters[f'{platform}:old']
        identity = await adapter.get('peers', old)
        started, finish = asyncio.Event(), asyncio.Event()
        async def menu(*_):
            started.set()
            await finish.wait()
            return True
        adapter.navigation.consume = AsyncMock(side_effect=menu)
        record = {'channel': f'{platform}:old', 'event': {
            'id': '1', 'user_id': 'old-user', 'chat_id': 'old-user', 'text': '1'}}
        task = asyncio.create_task(adapter.dispatch('message', record))
        await started.wait()
        removed = asyncio.create_task(manager.remove_peer(old))
        await asyncio.sleep(.01)
        assert not removed.done()
        finish.set()
        await task
        await removed
        await adapter.dispatch('later', record)
        assert adapter.navigation.consume.await_count == 1
        async with adapter.dispatch_lock:
            confirmed = asyncio.create_task(adapter.confirm_peer(old, identity))
            await asyncio.sleep(.01)
            assert not confirmed.done()
        await confirmed
        assert await manager.is_authorized(old)
        assert await adapter.get('deleted_peers', old) is None
    asyncio.run(run())


def test_wechat_rescan_restores_only_confirmed_owner_without_old_routing(repository, monkeypatch):
    import time
    from app.services.mobile import wechat_login
    async def run():
        manager, (old, new) = await accounts(repository, monkeypatch, 'wechat')
        old_adapter = manager.adapters['wechat:old']
        await old_adapter.put('selection', old, {'project_id': 'p', 'session_id': 's'})
        await old_adapter.put('callbacks', 'old-button', {'peer': old})
        await manager.remove_peer(old)
        await manager.remove_peer(new)
        monkeypatch.setattr(wechat_login, 'encrypt_secret', lambda _: 'encrypted-test')
        login = manager.wechat_login
        login.state = {'id': 'login', 'status': 'wait', 'expires_at': time.time()+30}
        transport = NS(base='https://ilinkai.weixin.qq.com', call=AsyncMock(return_value={
            'status': 'confirmed', 'bot_token': 'token', 'ilink_bot_id': 'old', 'ilink_user_id': 'old-user'}))
        await login.poll(transport, 'qr-code')
        assert login.state['status'] == 'confirmed'
        assert await manager.is_authorized(old)
        assert not await manager.is_authorized(new)
        assert repository.get('deleted_peers', old) is None
        assert repository.get('deleted_peers', new) is True
        assert repository.get('selection', old) is None
        assert repository.get('callbacks', 'old-button') is None
    asyncio.run(run())


def test_failed_deletion_rolls_back_the_marker_and_user_data(repository):
    import sqlite3
    scoped = repository.scoped('wechat:bot')
    peer = 'wechat:bot:owner:owner'
    scoped.put('peers', peer, {'allowed': True})
    scoped.put('selection', peer, {'project_id': 'keep'})
    with sqlite3.connect(repository.path) as db:
        db.execute("CREATE TRIGGER fail_peer_delete BEFORE DELETE ON mobile_records "
                   "WHEN OLD.namespace='peers' BEGIN SELECT RAISE(ABORT, 'test failure'); END")
    with pytest.raises(sqlite3.IntegrityError, match='test failure'):
        scoped.remove_peer(peer)
    assert scoped.get('deleted_peers', peer) is None
    assert scoped.get('peers', peer)['allowed']
    assert scoped.get('selection', peer) == {'project_id': 'keep'}
