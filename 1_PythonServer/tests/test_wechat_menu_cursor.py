from app.services.mobile import menu_pages
import asyncio
import json
import sqlite3
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

from tests.test_mobile_access import host, repository
from app.infra.database.schema import ensure_database_schema, SCHEMA_VERSION
from app.services.mobile import navigation
from app.services.mobile.wechat_navigation import WeChatNavigation
from app.services.mobile.wechat_transport import WeChatTransport


def test_wechat_connections_advance_independent_cursors_and_resume(repository):
    async def run():
        for connection_id in ['wechat:first', 'wechat:rescanned']:
            scoped = repository.scoped(connection_id)
            transport = WeChatTransport('test-token')
            transport.call = AsyncMock(return_value={'msgs': [
                {'message_type': 1, 'message_id': 'same-id', 'from_user_id': 'user', 'item_list': []}],
                'get_updates_buf': connection_id + ':next'})
            events = transport.events(scoped)
            event = await anext(events)
            assert scoped.receive(connection_id, event['id'], {'event': event})
            assert await anext(events) is None  # Persist cursor after receipt.
            await events.aclose()
            assert scoped.get('offsets', connection_id) == connection_id + ':next'
            resumed = transport.events(scoped)
            await anext(resumed)
            assert transport.call.call_args.args[1]['get_updates_buf'] == connection_id + ':next'
            assert not scoped.receive(connection_id, event['id'], {'event': event})
            await resumed.aclose()
        assert len(repository.list('inbox')) == 2
    asyncio.run(run())


def test_wechat_content_precedes_operations_without_count_heading(host, monkeypatch):
    host.platform = 'wechat'
    host.navigation = WeChatNavigation(host)
    monkeypatch.setattr(menu_pages, 'session_children', lambda *args: [
        (NS(session_id='a', title='讨论方案'), None), (NS(session_id='b', title='实现功能'), None)])
    async def run():
        await host.navigation.action('peer', 'sessions', target={'project_id': 'p'})
        item = (await host.records('outbox'))[0][1]
        text = item['parts'][0]
        assert item['header'] == '项目集：Project A\n会话：未选择'
        assert text.startswith('1. 讨论方案\n2. 实现功能\n3. 【操作】新建主会话')
        assert '主会话（' not in text and '（2）' not in text
        state = await host.navigation.state('peer')
        callbacks = [await host.get('callbacks', key) for key in state['options']]
        assert [item['action'] for item in callbacks[:3]] == ['select', 'select', 'new']
        assert callbacks[0]['target'] == {'project_id': 'p', 'session_id': 'a'}
    asyncio.run(run())


def test_wechat_empty_and_paginated_menus_keep_controls_without_totals(host):
    host.platform = 'wechat'
    host.navigation = WeChatNavigation(host)
    assert host.navigation.page_text('主会话', 0, 0, 1, 'sessions') == '暂无内容。'
    assert host.navigation.page_text('项目集', 2, 0, 1, 'categories') == '项目集'
    assert host.navigation.page_text('选择项目', 12, 1, 2, 'projects') == '选择项目'


def test_upgrade_54_moves_only_owned_wechat_cursor(tmp_path):
    path = tmp_path / 'old.db'
    ensure_database_schema(path)
    with sqlite3.connect(path) as db:
        db.execute('DELETE FROM schema_migrations')
        db.execute("INSERT INTO schema_migrations VALUES (54,'previous','time')")
        db.execute('INSERT INTO mobile_records VALUES (?,?,?,?,?)',
            ('offsets', 'wechat', json.dumps('original-cursor'), 123, 'wechat:first'))
        db.execute('INSERT INTO mobile_records VALUES (?,?,?,?,?)',
            ('offsets', 'telegram:bot', '12', 456, 'telegram:bot'))
    ensure_database_schema(path)
    ensure_database_schema(path)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT record_key,payload,updated_at,connection_id FROM mobile_records ORDER BY record_key').fetchall() == [
            ('telegram:bot', '12', 456, 'telegram:bot'),
            ('wechat:first', json.dumps('original-cursor'), 123, 'wechat:first')]
        assert db.execute('SELECT max(version) FROM schema_migrations').fetchone()[0] == SCHEMA_VERSION
