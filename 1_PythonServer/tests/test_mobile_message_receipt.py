from app.services.mobile import menu_pages
import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest

from tests.test_mobile_access import host, repository
from tests.test_mobile_account_management import accounts
from app.core.errors import BadRequestError
from app.services.mobile.manager import MobileAccessService, INBOUND_ADAPTERS
from app.services.mobile import manager as manager_module, navigation
from app.services.mobile.wechat_navigation import WeChatNavigation

TARGET = {'project_id': 'p', 'session_id': 's'}


@pytest.mark.parametrize('platform', ['wechat', 'feishu', 'telegram'])
def test_receipt_setting_is_persistent_per_connection_without_restarting(repository, monkeypatch, platform):
    async def run():
        manager, _ = await accounts(repository, monkeypatch, platform)
        key, other = f'{platform}:old', f'{platform}:new'
        adapter = manager.adapters[key]
        transport = adapter.transport
        adapter.apply_config = AsyncMock(wraps=adapter.apply_config)
        assert (await manager.status(key, platform))['message_receipt_enabled'] is True
        before = next(r['config'] for r in repository.connections(platform) if r['connection_id'] == key)
        result = await manager.configure_message_receipt(platform, key, False)
        assert result['message_receipt_enabled'] is False
        after = next(r['config'] for r in repository.connections(platform) if r['connection_id'] == key)
        assert after == dict(before, message_receipt_enabled=False)
        adapter.apply_config.assert_not_awaited()
        assert adapter.transport is transport
        assert (await manager.status(other, platform))['message_receipt_enabled'] is True

        # QR login / credential resave must not reset the local preference.
        await manager.save_platform(platform, 'old', before)
        assert (await manager.status(key, platform))['message_receipt_enabled'] is False
        if platform == 'telegram':
            validator = AsyncMock(return_value=dict(before))
            monkeypatch.setattr(manager_module, 'validate_configuration', validator)
            assert not (await manager.configure(token='', enabled=True, api_base='https://api.telegram.org',
                                                connection_id=key))['message_receipt_enabled']
            # Connecting a different bot must use its own preference.
            validator.return_value = dict(before, bot={'id': 'new'})
            assert (await manager.configure(token='other', enabled=True, api_base='https://api.telegram.org',
                                            connection_id=key))['message_receipt_enabled'] is True
        restarted = MobileAccessService(repository)
        assert not (await restarted.status(key, platform))['message_receipt_enabled']
        assert (await restarted.configure_message_receipt(platform, key, True))['message_receipt_enabled'] is True
        wrong = 'wechat' if platform != 'wechat' else 'telegram'
        with pytest.raises(BadRequestError):
            await restarted.configure_message_receipt(wrong, key, False)
        assert (await restarted.status(key, platform))['message_receipt_enabled'] is True
    asyncio.run(run())


@pytest.mark.parametrize('platform', ['wechat', 'feishu', 'telegram'])
@pytest.mark.parametrize('enabled', [None, True, False])
def test_receipt_only_controls_submit_ack_not_results(host, platform, enabled):
    async def run():
        adapter = INBOUND_ADAPTERS[platform](host.repository)
        adapter.config = dict(host.config)
        if enabled is not None:
            adapter.config['message_receipt_enabled'] = enabled
        peer = f'{platform}:12:user:user'
        await adapter.put('peers', peer, {'allowed': True, 'user_id': 'user', 'chat_id': 'user', 'bot_id': 12})
        adapter.desktop.submit = AsyncMock(return_value='job')
        await adapter.submit(peer, TARGET, '处理要求', [])
        adapter.desktop.submit.assert_awaited_once()
        outbox = [record for _, record in await adapter.records('outbox')]
        assert len(outbox) == (0 if enabled is False else 1)
        if outbox:
            assert '已接收，正在提交到会话。' in ''.join(outbox[0]['parts'])
        for status, text in [('completed', '任务已完成'), ('error', '请求失败'), ('cancelled', '已暂停')]:
            await adapter.result(dict(TARGET, peer=peer, user_message_id=status, status='running'), status, text)
            assert any(text in ''.join(record['parts']) for _, record in await adapter.records('outbox'))
        adapter.desktop.submit.side_effect = BadRequestError('目标会话正在运行')
        await adapter.submit(peer, TARGET, '另一条要求', [])
        assert any('目标会话正在运行' in ''.join(record['parts']) for _, record in await adapter.records('outbox'))
    asyncio.run(run())


def test_missing_wechat_menu_refreshes_without_interpreting_old_number(host, monkeypatch):
    host.platform, host.label = 'wechat', '微信'
    host.navigation = WeChatNavigation(host)
    peer = 'wechat:12:user:user'
    monkeypatch.setattr(menu_pages, 'get_project_service', lambda: NS(
        list_project_categories=lambda: [NS(name='日常项目', category_id='daily-project', category_kind='project')],
        list_projects=lambda: [],
        get_project_category=lambda _: NS(name='日常项目', category_kind='project'),
    ))

    async def run():
        assert await host.navigation.consume(peer, '2', {})
        state = await host.navigation.state(peer)
        assert state['stack'][-1]['action'] == 'categories'
        replies = '\n'.join(''.join(o['parts']) for _, o in await host.records('outbox'))
        assert '原菜单尚未建立或已失效' in replies and '2. 日常项目' in replies
        assert (await host.get('navigation', peer))['category'] is None
        # Loading a new navigation object simulates reopening persisted menus.
        host.navigation = WeChatNavigation(host)
        assert await host.navigation.consume(peer, '2', {})
        assert (await host.get('navigation', peer))['category'] == 'daily-project'
        await host.put('menus', peer, {'mode': 'conversation', 'stack': [], 'scope': ['project'], 'options': []})
        assert await host.navigation.consume(peer, '2', {}) is False
    asyncio.run(run())
