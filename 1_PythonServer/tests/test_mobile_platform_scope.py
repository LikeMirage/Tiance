import asyncio
import json
import sqlite3
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest

from tests.test_mobile_access import host, repository
from app.core.errors import BadRequestError
from app.services.mobile import context, navigation, history
from app.services.mobile.feishu_navigation import FeishuNavigation
from app.services.mobile.wechat_navigation import WeChatNavigation
from app.services.mobile.manager import MobileAccessService
from app.infra.database.schema import ensure_database_schema

PEER = 'peer'
TARGET = {'project_id': 'p', 'session_id': 's'}


def platform_host(host, platform):
    host.platform = platform
    host.label = platform
    host.navigation = (WeChatNavigation if platform == 'wechat' else FeishuNavigation)(host)
    return host


@pytest.mark.parametrize('platform', ['wechat', 'feishu'])
@pytest.mark.parametrize('kind', list(context.COLLECTIONS))
def test_every_collection_can_be_the_only_entry(host, monkeypatch, platform, kind):
    platform_host(host, platform)
    monkeypatch.setattr(navigation, 'get_project_service', lambda: NS(list_project_categories=lambda: []))
    async def run():
        host.config['allowed_collections'] = [kind]
        await host.navigation.action(PEER, 'collections')
        item = (await host.records('outbox'))[0][1]
        assert item['parts'][0].startswith(context.COLLECTIONS[kind])
        assert item['access_collections'] == [kind]
        if platform == 'wechat':
            state = await host.navigation.state(PEER)
            assert state['stack'] == [{'action': 'categories', 'kind': kind}]
            await host.navigation.consume(PEER, '0', {})
            assert (await host.navigation.state(PEER))['stack'] == state['stack']
        else:
            assert item['rows'][0][0]['presentation']['role'] == 'entry'
    asyncio.run(run())


@pytest.mark.parametrize('platform', ['wechat', 'feishu'])
def test_scope_blocks_old_callbacks_messages_and_queued_results(host, platform):
    platform_host(host, platform)
    async def run():
        host.config['allowed_collections'] = ['project', 'tool']
        await host.navigation.action(PEER, 'collections')
        item = (await host.records('outbox'))[0][1]
        host.config['allowed_collections'] = ['tool']
        assert not await host.access_scope.allows_delivery(item)
        for action, args in [('categories', {'kind': 'project'}), ('new', {'target': TARGET}),
                             ('history', {'target': TARGET}), ('actions', {'target': TARGET})]:
            with pytest.raises(BadRequestError, match='访问范围'):
                await host.navigation.action(PEER, action, **args)
        await host.put('selection', PEER, TARGET)
        if platform == 'wechat':
            await host.put('menus', PEER, {'mode': 'conversation', 'stack': [], 'options': []})
        with pytest.raises(BadRequestError, match='访问范围'):
            await host.navigation.message_target(PEER, {})
        assert not await host.access_scope.allows_delivery({'target': TARGET, 'parts': ['private']})
    asyncio.run(run())


@pytest.mark.parametrize('shortcut', ['5', '/5'])
def test_wechat_operations_are_labeled_and_history_shortcut_preserves_chat(host, monkeypatch, shortcut):
    platform_host(host, 'wechat')
    monkeypatch.setattr(navigation, 'get_project_service', lambda: NS(list_project_categories=lambda: []))
    monkeypatch.setattr(history, 'recent_history_text', lambda target: 'recent five turns')
    async def run():
        await host.navigation.action(PEER, 'collections')
        menu = (await host.records('outbox'))[0][1]['parts'][0]
        assert '1. 全部项目' in menu
        assert '2. 【操作】新建分类' in menu
        assert '【操作】关系图' in menu
        await host.put('peers', PEER, {'allowed': True, 'bot_id': 12})
        await host.navigation.action(PEER, 'select', target=TARGET)
        state = await host.navigation.state(PEER)
        assert state['mode'] == 'conversation'
        assert any('5 查看前5轮对话 · 00 暂停 · 0 返回上一级 · menu 选择集' in item['parts'][0] for _, item in await host.records('outbox'))
        assert all('/5' not in item['parts'][0] and '/menu' not in item['parts'][0] for _, item in await host.records('outbox'))
        assert await host.navigation.consume(PEER, shortcut, {})
        await asyncio.gather(*host.work)
        assert any('recent five turns' in item['parts'][0] for _, item in await host.records('outbox'))
        assert await host.navigation.state(PEER) == state
        assert not await host.navigation.consume(PEER, '05', {})
    asyncio.run(run())


def test_wechat_scope_change_resets_pending_creation_and_numeric_menu(host, monkeypatch):
    platform_host(host, 'wechat')
    monkeypatch.setattr(navigation, 'get_project_service', lambda: NS(list_project_categories=lambda: []))
    async def run():
        await host.navigation.action(PEER, 'collections')
        await host.navigation.action(PEER, 'newcategory', kind='project')
        host.config['allowed_collections'] = ['tool', 'theme']
        assert await host.navigation.consume(PEER, '1', {})
        state = await host.navigation.state(PEER)
        assert 'pending' not in state
        assert state['stack'] == [{'action': 'collections'}]
        assert len(state['options']) == 4  # Two collections plus two controls.
        host.config['allowed_collections'] = []
        await host.navigation.consume(PEER, '1', {})
        assert not (await host.navigation.state(PEER))['options']
    asyncio.run(run())


@pytest.mark.parametrize('platform', ['wechat', 'feishu'])
def test_reconnect_and_new_connections_keep_independent_scopes(repository, monkeypatch, platform):
    async def run():
        manager = MobileAccessService(repository)
        await manager.save_platform(platform, 'a', {'enabled': False, 'bot': {'id': 'a'}})
        await manager.configure_scope(platform, f'{platform}:a', ['theme'])
        await manager.save_platform(platform, 'a', {'enabled': False, 'bot': {'id': 'a'}, 'token': 'encrypted'})
        await manager.save_platform(platform, 'b', {'enabled': False, 'bot': {'id': 'b'}})
        restored = MobileAccessService(repository)
        assert (await restored.status(f'{platform}:a', platform))['allowed_collections'] == ['theme']
        assert (await restored.status(f'{platform}:b', platform))['allowed_collections'] == ['project']
        with pytest.raises(BadRequestError):
            await restored.configure_scope('telegram', f'{platform}:a', [])
    asyncio.run(run())


def test_upgrade_53_preserves_explicit_scopes_and_adds_defaults(tmp_path):
    path = tmp_path / 'old.db'
    ensure_database_schema(path)
    with sqlite3.connect(path) as db:
        db.execute('DELETE FROM schema_migrations')
        db.execute("INSERT INTO schema_migrations VALUES (53,'previous','time')")
        for platform, values in [('wechat', {'token': 'encrypted'}), ('feishu', {'allowed_collections': []}),
                                 ('telegram', {'allowed_collections': ['tool']})]:
            db.execute('INSERT INTO mobile_connections VALUES (?,?,?,?,?)',
                (f'{platform}:a', platform, 'a', json.dumps(values), 123))
    ensure_database_schema(path)
    ensure_database_schema(path)
    with sqlite3.connect(path) as db:
        data = {key: json.loads(raw) for key, raw in db.execute('SELECT platform,payload FROM mobile_connections')}
        assert data == {'wechat': {'token': 'encrypted', 'allowed_collections': ['project']},
                        'feishu': {'allowed_collections': []}, 'telegram': {'allowed_collections': ['tool']}}
