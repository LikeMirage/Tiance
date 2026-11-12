import asyncio
import json
import sqlite3
from copy import deepcopy
from unittest.mock import AsyncMock, Mock

import pytest

from tests.test_mobile_access import host, repository
from tests.test_mobile_menu_hierarchy import menus, PEER, TARGET, buttons, click
from app.core.errors import BadRequestError
from app.infra.database.schema import ensure_database_schema, SCHEMA_VERSION
from app.services.mobile import catalog, context, models, relationship_diagram


def test_browsing_messages_cannot_be_quoted_as_a_conversation(menus):
    async def run():
        nav = menus.navigation
        await nav.action(PEER, 'select', target=TARGET)
        await nav.action(PEER, 'sessions', target={'project_id': 'p'})
        key, item = (await menus.records('outbox'))[-1]
        menus.repository.delivery_progress(key, item, 'menu-message')
        assert await menus.get('messages', PEER + ':menu-message') == {'target': None}
        if menus.platform != 'wechat':
            with pytest.raises(BadRequestError, match='对应关系'):
                await nav.message_target(PEER, {'reply_to_message': {'message_id': 'menu-message'}})
        await menus.reply(PEER, 'answer', TARGET)
        key, item = (await menus.records('outbox'))[-1]
        menus.repository.delivery_progress(key, item, 'answer-message')
        assert (await menus.get('messages', PEER + ':answer-message'))['target'] == TARGET
        if menus.platform != 'wechat':
            assert await nav.message_target(PEER, {'reply_to_message': {'message_id': 'answer-message'}}) == TARGET
        else:
            with pytest.raises(BadRequestError, match='未发送'):
                await nav.message_target(PEER, {'reply_to_message': {'message_id': 'answer-message'}})
    asyncio.run(run())


def test_child_list_cannot_create_main_via_command(menus, monkeypatch):
    create = Mock()
    monkeypatch.setattr(context, 'create_conversation', create)
    async def run():
        nav = menus.navigation
        await nav.action(PEER, 'sessions', target=TARGET, parent='s', group='child')
        with pytest.raises(BadRequestError, match='主会话列表'):
            await nav.action(PEER, 'new')
        create.assert_not_called()
    asyncio.run(run())


def test_scope_change_requires_reopening_before_implicit_creation(menus, monkeypatch):
    create = Mock()
    monkeypatch.setattr(catalog, 'create_category', create)
    async def run():
        nav = menus.navigation
        await nav.action(PEER, 'categories', kind='project')
        menus.config['allowed_collections'] = ['tool']
        with pytest.raises(BadRequestError, match='访问范围'):
            await nav.action(PEER, 'newcategory', title='must not create in tool')
        create.assert_not_called()
    asyncio.run(run())


def test_old_model_button_keeps_its_target_without_reentering_chat(menus, monkeypatch):
    change = Mock(return_value=type('Model', (), {'provider_label': 'Provider', 'model_label': 'Model'})())
    monkeypatch.setattr(models, 'select_model', change)
    async def run():
        nav = menus.navigation
        await nav.action(PEER, 'select', target=TARGET)
        await nav.action(PEER, 'models', target=TARGET, provider='provider')
        choose = next(b for b in await buttons(menus) if b['action'] == 'setmodel')
        other = dict(TARGET, project_id='tool')
        await nav.action(PEER, 'select', target=other)
        await nav.action(PEER, 'categories', kind='tool')
        before = deepcopy(await nav.menus.get(PEER))
        await click(menus, choose)
        change.assert_called_once_with(TARGET, 'provider', 'model')
        assert await menus.get('selection', PEER) == other
        assert await nav.menus.get(PEER) == before
    asyncio.run(run())


@pytest.mark.parametrize('menus', ['wechat'], indirect=True)
def test_wechat_menu_prompts_do_not_inherit_previous_conversation(menus):
    async def run():
        nav = menus.navigation
        await nav.action(PEER, 'select', target=TARGET)
        await nav.action(PEER, 'categories', kind='tool')
        before = len(await menus.records('outbox'))
        await nav.consume(PEER, '999', {})
        replies = (await menus.records('outbox'))[before:]
        assert replies and all(item['target'] is None and item['header'] == '工具集' and item['menu']
                               for _, item in replies)
        await nav.action(PEER, 'newcategory', kind='tool')
        prompt = (await menus.records('outbox'))[-1][1]
        assert prompt['target'] is None and prompt['header'] == '工具集' and prompt['menu']
        assert (await nav.state(PEER))['pending']['kind'] == 'tool'
        await nav.consume(PEER, '0', {})
        assert 'pending' not in await nav.state(PEER)
        assert (await nav.state(PEER))['stack'][-1]['kind'] == 'tool'
    asyncio.run(run())


def test_late_diagram_keeps_newer_wechat_numbers(menus, monkeypatch, tmp_path):
    if menus.platform != 'wechat':
        return
    async def run():
        nav = menus.navigation
        path = tmp_path / 'diagram.png'
        path.write_bytes(b'png')
        monkeypatch.setattr(catalog, 'collection_outline', lambda kind: {})
        monkeypatch.setattr(relationship_diagram, 'diagram_directory', lambda: tmp_path)
        monkeypatch.setattr(nav.catalog, 'diagram', AsyncMock())
        await nav.action(PEER, 'categories', kind='tool')
        await nav.action(PEER, 'map', kind='tool')
        assert any(b['action'] == 'map' and b['kind'] == 'tool' for b in await buttons(menus))
        await nav.action(PEER, 'categories', kind='project')
        before = deepcopy(await nav.menus.get(PEER))
        await menus.reply_diagram(PEER, path, 'Tools', [])
        assert await nav.menus.get(PEER) == before
        await asyncio.gather(*menus.work)
    asyncio.run(run())


def test_upgrade_resets_only_menu_state_preserving_live_work(tmp_path):
    path = tmp_path / 'old.db'
    ensure_database_schema(path)
    payloads = {'menus': {'mode': 'conversation', 'stack': [{'action': 'sessions'}], 'options': ['old']},
                'navigation': {'kind': 'tool'}, 'selection': TARGET,
                'callbacks': {'action': 'permission', 'request_id': 'approve'},
                'jobs': {'status': 'running'}, 'staged': [{'reference': {'id': 'file'}}],
                'peers': {'allowed': True}, 'messages': {'target': TARGET}, 'offsets': 12}
    with sqlite3.connect(path) as db:
        db.execute('DELETE FROM schema_migrations')
        db.execute("INSERT INTO schema_migrations VALUES (55,'previous','time')")
        for connection in ('wechat:a', 'telegram:b', 'feishu:c'):
            for namespace, value in payloads.items():
                db.execute('INSERT INTO mobile_records VALUES (?,?,?,?,?)',
                           (namespace, connection + ':peer', json.dumps(value), 123, connection))
    ensure_database_schema(path)
    ensure_database_schema(path)
    with sqlite3.connect(path) as db:
        records = db.execute('SELECT namespace,payload,updated_at FROM mobile_records').fetchall()
        assert len(records) == 3 * (len(payloads) - 2)
        for namespace, payload, stamp in records:
            assert json.loads(payload) == payloads[namespace] and stamp == 123
        assert db.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0] == SCHEMA_VERSION
