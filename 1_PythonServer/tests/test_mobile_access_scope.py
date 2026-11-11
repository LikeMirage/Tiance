import asyncio
import json
import sqlite3
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock

import pytest
from pydantic import ValidationError

from tests.test_mobile_access import host, repository
from app.api.routes.mobile import AccessScopeSettings
from app.core.errors import BadRequestError
from app.infra.database.schema import ensure_database_schema, SCHEMA_VERSION
from app.services.mobile import context, navigation, catalog
from app.services.mobile.access_scope import reply_collections, validate_collections
from app.services.mobile.manager import MobileAccessService

PEER = 'telegram:12:7:7'
TARGET = {'project_id': 'p', 'session_id': 'a'}


@pytest.mark.parametrize('kind', list(context.COLLECTIONS))
def test_every_single_collection_skips_picker_equally(host, monkeypatch, kind):
    async def run():
        host.config['allowed_collections'] = [kind]
        host.reply = AsyncMock()
        monkeypatch.setattr(navigation, 'get_project_service', lambda: NS(list_project_categories=lambda: []))
        await host.navigation.action(PEER, 'collections')
        assert host.reply.call_args.args[1].startswith(context.COLLECTIONS[kind])
        callbacks = [data for _, data in await host.records('callbacks')]
        assert not any(data['action'] == 'categories' for data in callbacks)
        assert next(data for data in callbacks if data['action'] == 'projects')['kind'] == kind
    asyncio.run(run())


def test_multiple_collections_show_only_enabled_entries_and_zero_is_explicit(host):
    async def run():
        host.reply = AsyncMock()
        host.config['allowed_collections'] = ['tool', 'theme']
        await host.navigation.action(PEER, 'collections')
        assert host.reply.call_args.args[1] == '选择集（2）'
        listed = [data['kind'] for _, data in await host.records('callbacks') if data['action'] == 'categories']
        assert listed == ['tool', 'theme']
        before = await host.records('callbacks')
        host.config['allowed_collections'] = []
        await host.navigation.action(PEER, 'collections')
        assert '尚未开放任何集' in host.reply.call_args.args[1]
        assert host.reply.call_args.kwargs['rows'] == []
        assert await host.records('callbacks') == before
    asyncio.run(run())


@pytest.mark.parametrize('action', ['project', 'sessions', 'groups', 'select', 'new', 'stop',
                                    'permission', 'files', 'clear', 'history', 'model', 'models', 'setmodel'])
def test_old_target_buttons_cannot_bypass_closed_collection(host, action):
    async def run():
        host.config['allowed_collections'] = ['tool']  # Fixture target is a project.
        with pytest.raises(BadRequestError, match='访问范围'):
            await host.navigation.action(PEER, action, target=TARGET)
        assert not await host.records('selection')
        assert not await host.records('outbox')
    asyncio.run(run())


@pytest.mark.parametrize('action', ['categories', 'projects', 'newcategory', 'newproject', 'map'])
def test_old_collection_buttons_are_rejected(host, action):
    async def run():
        with pytest.raises(BadRequestError, match='访问范围'):
            await host.navigation.action(PEER, action, kind='tool', category='tool-category')
    asyncio.run(run())


def test_closed_browsing_location_never_silently_creates_in_another_collection(host, monkeypatch):
    create = Mock()
    monkeypatch.setattr(catalog, 'create_category', create)
    async def run():
        await host.put('navigation', PEER, {'kind': 'tool', 'category': 'tools'})
        with pytest.raises(BadRequestError, match='访问范围'):
            await host.navigation.action(PEER, 'newcategory', title='name')
        create.assert_not_called()
        assert await host.get('navigation', PEER) == {'kind': 'tool', 'category': 'tools'}
    asyncio.run(run())


def test_replying_to_old_message_cannot_change_selection_to_closed_target(host):
    async def run():
        host.config['allowed_collections'] = []
        await host.put('messages', PEER + ':old', {'target': TARGET})
        with pytest.raises(BadRequestError, match='访问范围'):
            await host.navigation.message_target(PEER, {'reply_to_message': {'message_id': 'old'}})
        assert await host.get('selection', PEER) is None
    asyncio.run(run())


def test_closed_targets_do_not_upload_submit_or_leak_in_reply(host):
    async def run():
        host.config['allowed_collections'] = []
        await host.put('peers', PEER, {'allowed': True})
        transport = NS(download=AsyncMock())
        host.desktop.submit = AsyncMock()
        assert not await host.download(PEER, TARGET, {'file_id': 'id'}, transport)
        await host.submit(PEER, TARGET, 'hi', [])
        await host.reply(PEER, 'private contents', TARGET)
        transport.download.assert_not_awaited()
        host.desktop.submit.assert_not_awaited()
        for _, item in await host.records('outbox'):
            assert item['target'] is None
            assert 'Project A' not in item['header']
            assert 'private contents' not in ''.join(item['parts'])
    asyncio.run(run())


def test_pending_request_is_rechecked_before_desktop_starts(host):
    async def run():
        await host.put('peers', PEER, {'allowed': True, 'bot_id': 12})
        host.desktop.owner = 'ui'
        host.desktop.on_result = AsyncMock()
        await host.put('jobs', 'job', dict(TARGET, peer=PEER, status='preparing', user_message_id='u'))
        host.config['allowed_collections'] = []
        await host.desktop.prepare('ui', 'job', None, None)
        host.desktop.on_result.assert_awaited_once()
        assert host.desktop.on_result.call_args.args[1] == 'error'
        assert await host.get('jobs', 'job') is None
    asyncio.run(run())


def test_scope_change_filters_queued_menu_and_old_queued_buttons(host, monkeypatch):
    async def run():
        host.config['allowed_collections'] = ['project', 'tool']
        await host.navigation.action(PEER, 'collections')
        menu = (await host.records('outbox'))[0][1]
        assert await host.access_scope.allows_delivery(menu)
        host.config['allowed_collections'] = ['project']
        assert not await host.access_scope.allows_delivery(menu)
        legacy = dict(menu)
        legacy.pop('access_collections')
        assert not await host.access_scope.allows_delivery(legacy)
        assert await host.access_scope.allows_delivery(dict(target=TARGET, rows=[]))
    asyncio.run(run())


def test_queued_diagram_retains_scope_when_its_buttons_are_gone(host):
    async def run():
        host.config['allowed_collections'] = ['tool']
        marker = reply_collections.set(('tool',))
        try:
            await host.reply_diagram(PEER, 'diagram.png', '工具集', [])
        finally:
            reply_collections.reset(marker)
        item = (await host.records('outbox'))[0][1]
        assert await host.access_scope.allows_delivery(item)
        host.config['allowed_collections'] = ['project']
        assert not await host.access_scope.allows_delivery(item)
    asyncio.run(run())


def test_scope_is_durable_per_connection_and_configuration_does_not_copy_another_bots_scope(repository, monkeypatch):
    async def run():
        for key, scope in [('12', ['tool']), ('34', ['theme'])]:
            repository.save_connection(f'telegram:{key}', 'telegram', key,
                {'enabled': False, 'token': 'encrypted', 'bot': {'id': int(key)}, 'allowed_collections': scope}, select=key == '12')
        manager = MobileAccessService(repository)
        status = await manager.configure_scope('telegram', 'telegram:12', ['role'])
        assert status['allowed_collections'] == ['role']
        assert (await MobileAccessService(repository).status('telegram:12'))['allowed_collections'] == ['role']
        assert (await manager.status('telegram:34'))['allowed_collections'] == ['theme']
        assert repository.connections('telegram')[0]['config']['token'] == 'encrypted'
        assert (await manager.status('telegram:12'))['enabled'] is False
        # Reconnecting another known bot uses its own scope, not the selected bot's.
        monkeypatch.setattr('app.services.mobile.manager.validate_configuration', AsyncMock(return_value={
            'enabled': False, 'bot': {'id': 34}, 'allowed_collections': ['role']}))
        assert (await manager.configure(token='new', enabled=False, api_base='https://api.telegram.org'))['allowed_collections'] == ['theme']
        monkeypatch.setattr('app.services.mobile.manager.validate_configuration', AsyncMock(return_value={
            'enabled': False, 'bot': {'id': 56}, 'allowed_collections': ['role']}))
        assert (await manager.configure(token='new', enabled=False, api_base='https://api.telegram.org'))['allowed_collections'] == ['project']
        for key in ['telegram:unknown', 'feishu:app']:
            with pytest.raises(BadRequestError):
                await manager.configure_scope('telegram', key, ['project'])
    asyncio.run(run())


def test_failed_scope_save_keeps_active_config(repository, monkeypatch):
    async def run():
        repository.save_connection('telegram:12', 'telegram', '12', {'enabled': False, 'bot': {'id': 12}, 'allowed_collections': ['project']}, select=True)
        manager = MobileAccessService(repository)
        await manager.status()
        monkeypatch.setattr(repository, 'save_connection', Mock(side_effect=RuntimeError('disk error')))
        with pytest.raises(RuntimeError, match='disk error'):
            await manager.configure_scope('telegram', 'telegram:12', ['tool'])
        assert manager.adapters['telegram:12'].config['allowed_collections'] == ['project']
        assert repository.connections()[0]['config']['allowed_collections'] == ['project']
    asyncio.run(run())


def test_scope_save_waits_for_accepted_navigation_and_blocks_later_actions(repository, monkeypatch):
    async def run():
        repository.save_connection('telegram:12', 'telegram', '12',
            {'enabled': False, 'bot': {'id': 12}, 'allowed_collections': ['project']}, select=True)
        manager = MobileAccessService(repository)
        await manager.status()
        adapter = manager.adapters['telegram:12']
        entered, finish = asyncio.Event(), asyncio.Event()
        order = []

        async def accepted_action(*args, **kwargs):
            entered.set()
            await finish.wait()
            order.append('action finished')

        monkeypatch.setattr(navigation.MobileNavigation, 'action', accepted_action)
        action = asyncio.create_task(adapter.navigation.action(PEER, 'categories', kind='project'))
        await asyncio.wait_for(entered.wait(), 1)

        async def close_scope():
            await manager.configure_scope('telegram', 'telegram:12', [])
            order.append('scope saved')

        save = asyncio.create_task(close_scope())
        try:
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(asyncio.shield(save), .05)
        finally:
            finish.set()
            await asyncio.gather(action, save)
        assert order == ['action finished', 'scope saved']
        with pytest.raises(BadRequestError, match='访问范围'):
            await adapter.navigation.action(PEER, 'categories', kind='project')
    asyncio.run(run())


def test_scope_schema_rejects_unknowns_and_duplicates():
    with pytest.raises(ValidationError):
        AccessScopeSettings(connection_id='telegram:12', allowed_collections=['unknown'])
    for value in [['project', 'project'], ['unknown'], None]:
        with pytest.raises(BadRequestError):
            validate_collections(value)
    assert validate_collections([]) == []


def test_upgrade_52_preserves_connections_and_only_defaults_telegram(tmp_path):
    path = tmp_path / 'scope.db'
    ensure_database_schema(path)
    with sqlite3.connect(path) as db:
        db.execute('DELETE FROM schema_migrations')
        db.execute("INSERT INTO schema_migrations VALUES (52,'previous','time')")
        for key, platform, config in [('telegram:1','telegram',{'token':'private','enabled':True}),
                                      ('telegram:2','telegram',{'allowed_collections':[]}),
                                      ('feishu:3','feishu',{'token':'unchanged'})]:
            db.execute('INSERT INTO mobile_connections VALUES (?,?,?,?,?)', (key, platform, key.split(':')[1], json.dumps(config), 123))
    ensure_database_schema(path)
    ensure_database_schema(path)
    with sqlite3.connect(path) as db:
        records = {key: json.loads(raw) for key, raw in db.execute('SELECT connection_id,payload FROM mobile_connections')}
        assert records['telegram:1'] == {'token':'private','enabled':True,'allowed_collections':['project']}
        assert records['telegram:2']['allowed_collections'] == []
        assert records['feishu:3'] == {'token':'unchanged','allowed_collections':['project']}
        assert db.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0] == SCHEMA_VERSION
