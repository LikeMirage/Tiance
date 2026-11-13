import asyncio
from copy import deepcopy
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest

from tests.test_mobile_access import host, repository
from tests.test_mobile_session_listing import node
from app.core.errors import BadRequestError
from app.services.mobile import context, menu_pages, catalog_navigation, models
from app.services.mobile.feishu_navigation import FeishuNavigation
from app.services.mobile.telegram_navigation import TelegramNavigation
from app.services.mobile.wechat_navigation import WeChatNavigation

PEER = 'peer'
TARGET = {'project_id': 'p', 'session_id': 's'}


@pytest.fixture(params=['wechat', 'feishu', 'telegram'])
def menus(host, monkeypatch, request):
    host.platform = host.label = request.param
    host.config['allowed_collections'] = ['project', 'tool']
    host.navigation = {'wechat': WeChatNavigation, 'feishu': FeishuNavigation, 'telegram': TelegramNavigation}[request.param](host)
    categories = [NS(category_id='cat', name='Work', category_kind='project'), NS(category_id='tools', name='Tools', category_kind='tool')]
    projects = {key: NS(project_id=key, name=key, project_kind=kind, category_id=category)
                for key, kind, category in [('p', 'project', 'cat'), ('tool', 'tool', 'tools')] +
                [(f'p{i}', 'project', 'cat') for i in range(12)]}
    sessions = {sid: NS(session_id=sid, title=sid, provider_id='provider', model_id='model') for sid in ['s', 'child', 'fork']}
    nodes = [node('s'), node('child', 's', 'child'), node('fork', 's', 'fork')]
    projects_api = NS(get_project=projects.get, list_projects=lambda: list(projects.values()),
                      list_project_categories=lambda: categories,
                      get_project_category=lambda cid: next((c for c in categories if c.category_id == cid), None))
    conversations_api = NS(get_session=lambda pid, sid: sessions.get(sid),
                           get_list_data=lambda *a, **k: (None, list(sessions.values()), nodes, [], {}, None))
    for module in (context, menu_pages, catalog_navigation):
        monkeypatch.setattr(module, 'get_project_service', lambda: projects_api)
    monkeypatch.setattr(context, 'get_project_conversation_service', lambda: conversations_api)
    monkeypatch.setattr(models, 'available_models', lambda: [NS(provider_id='provider', provider_label='Provider', model_id='model', model_label='Model')])
    return host


async def buttons(host):
    if host.platform == 'wechat':
        keys = (await host.navigation.state(PEER))['options']
    else:
        rows = (await host.records('outbox'))[-1][1]['rows']
        keys = [button['callback_data'] for row in rows for button in row]
    return [await host.get('callbacks', key) for key in keys]


async def click(host, callback):
    await host.navigation.action(PEER, **{key: value for key, value in callback.items() if key != 'peer'})


async def back(host):
    if host.platform == 'wechat':
        await host.navigation.consume(PEER, '0', {})
    else:
        choices = await buttons(host)
        parent = (await host.navigation.menus.get(PEER))['stack'][-2]
        await click(host, next(b for b in choices if b['action'] == 'back' or
                              parent['action'] == 'select' and b['action'] == 'select' and b['target'] == parent['target']))


def test_level_specific_actions_and_paged_return(menus):
    async def run():
        nav = menus.navigation
        await nav.action(PEER, 'collections')
        assert [b['action'] for b in await buttons(menus)] == ['categories', 'categories']
        await nav.action(PEER, 'categories', kind='project')
        actions = [b['action'] for b in await buttons(menus)]
        assert 'newcategory' in actions and 'newproject' not in actions and 'status' not in actions
        await nav.action(PEER, 'projects', kind='project', category='cat', page=1)
        actions = await buttons(menus)
        assert 'newcategory' not in [b['action'] for b in actions]
        assert 'map' not in [b['action'] for b in actions]
        assert any(b['action'] == 'newproject' for b in actions)
        chosen = next(b for b in actions if b['action'] == 'project')
        await click(menus, chosen)
        actions = await buttons(menus)
        assert actions[0]['action'] == 'select'
        assert sum(b['action'] == 'new' for b in actions) == 1
        await click(menus, actions[0])
        assert await nav.message_target(PEER, {}) == dict(chosen['target'], session_id='s')
        await back(menus)
        assert (await nav.menus.get(PEER))['stack'][-1]['action'] == 'sessions'
        await back(menus)
        frame = (await nav.menus.get(PEER))['stack'][-1]
        assert frame == {'action': 'projects', 'kind': 'project', 'category': 'cat', 'page': 1}
    asyncio.run(run())


@pytest.mark.parametrize('kind', list(context.COLLECTIONS))
def test_single_collection_root_never_reintroduces_picker(menus, kind):
    async def run():
        menus.config['allowed_collections'] = [kind]
        nav = menus.navigation
        await nav.action(PEER, 'collections')
        state = await nav.menus.get(PEER)
        assert len(state['stack']) == 1 and state['stack'][0]['kind'] == kind
        assert not any(b['action'] in {'collections', 'back', 'status'} for b in await buttons(menus))
        await nav.action(PEER, 'projects', kind=kind)
        await back(menus)
        state = await nav.menus.get(PEER)
        assert len(state['stack']) == 1 and state['stack'][0]['action'] == 'categories'
        if menus.platform == 'wechat':
            await back(menus)
            assert (await nav.menus.get(PEER))['stack'] == state['stack']
    asyncio.run(run())


def test_child_and_model_pages_return_to_their_bound_session(menus):
    async def run():
        nav = menus.navigation
        await nav.action(PEER, 'select', target=TARGET)
        await nav.action(PEER, 'groups')
        actions = await buttons(menus)
        assert {b['group'] for b in actions if b['action'] == 'sessions'} == {'child', 'fork'}
        await click(menus, next(b for b in actions if b.get('group') == 'child'))
        assert not any(b['action'] == 'new' for b in await buttons(menus))
        await click(menus, next(b for b in await buttons(menus) if b.get('target', {}).get('session_id') == 'child'))
        await back(menus)
        assert (await nav.menus.get(PEER))['stack'][-1]['group'] == 'child'
        await back(menus)
        assert (await nav.menus.get(PEER))['stack'][-1]['action'] == 'groups'
        await back(menus)
        assert await nav.message_target(PEER, {}) == TARGET
        await nav.action(PEER, 'model')
        await click(menus, next(b for b in await buttons(menus) if b['action'] == 'models'))
        await back(menus)
        assert (await nav.menus.get(PEER))['stack'][-1]['action'] == 'model'
        await back(menus)
        assert await nav.message_target(PEER, {}) == TARGET
    asyncio.run(run())


def test_browsing_blocks_send_and_late_results_keep_active_menu(menus):
    async def run():
        nav = menus.navigation
        await nav.action(PEER, 'select', target=TARGET)
        await nav.action(PEER, 'categories', kind='tool')
        page = (await menus.records('outbox'))[-1][1]
        assert page['target'] is None and page['header'] == '工具集'
        with pytest.raises(BadRequestError, match='未发送'):
            await nav.message_target(PEER, {})
        before = deepcopy(await nav.menus.get(PEER))
        await menus.reply(PEER, 'late answer for p', TARGET)
        assert await nav.menus.get(PEER) == before
        # These are the menu's controls, not the late result's controls.
        resume = next(v for _, v in await menus.records('callbacks')
                      if v.get('action') == 'select' and v.get('target') == TARGET and v.get('_trail'))
        await click(menus, resume)
        assert await nav.message_target(PEER, {}) == TARGET
        await nav.action(PEER, 'categories', kind='tool')
        menus.config['allowed_collections'] = ['tool']
        with pytest.raises(BadRequestError, match='访问范围'):
            await click(menus, resume)
    asyncio.run(run())


def test_bad_target_restores_navigation_and_does_not_select(menus):
    async def run():
        nav = menus.navigation
        await nav.action(PEER, 'projects', kind='project', category='cat', page=1)
        before = deepcopy(await nav.menus.get(PEER))
        with pytest.raises(BadRequestError):
            await nav.action(PEER, 'select', target={'project_id': 'gone', 'session_id': 's'})
        assert await nav.menus.get(PEER) == before
        assert await menus.get('selection', PEER) is None
    asyncio.run(run())


def test_explicit_resume_remains_available_across_menus_and_restart(menus):
    async def run():
        nav = menus.navigation
        await nav.action(PEER, 'select', target=TARGET)
        original_path = deepcopy((await nav.menus.get(PEER))['stack'])
        staged = [{'reference': {'id': 'file', 'fileName': 'recording.m4a'}}]
        await menus.put('staged', menus.staging_key(PEER, TARGET), staged)
        locations = [('collections', {}), ('categories', {'kind': 'tool'}),
                     ('projects', {'kind': 'tool', 'category': 'tools'}),
                     ('project', {'target': {'project_id': 'tool'}}),
                     ('actions', {'target': TARGET}), ('model', {'target': TARGET})]
        for action, args in locations:
            await nav.action(PEER, action, **args)
            assert await menus.get('selection', PEER) == TARGET
            page = (await menus.records('outbox'))[-1][1]
            if menus.platform == 'wechat':
                assert '【操作】返回之前会话' in ''.join(page['parts'])
                options = (await nav.menus.get(PEER))['options']
                callbacks = [await menus.get('callbacks', key) for key in options]
                index = next(i for i, item in enumerate(callbacks, 1)
                             if item['action'] == 'select' and item['target'] == TARGET)
                resume = str(index)
            else:
                entries = [button for row in page['rows'] for button in row]
                entry = next(button for button in entries if button['text'] == '返回之前会话')
                resume = await menus.get('callbacks', entry['callback_data'])
            with pytest.raises(BadRequestError, match='未发送'):
                await nav.message_target(PEER, {})
            # A new navigation instance reads the saved menu and last selection.
            menus.navigation = nav = type(nav)(menus)
            if menus.platform == 'wechat':
                assert await nav.consume(PEER, resume, {})
                assert not await nav.consume(PEER, '2', {})
            else:
                await click(menus, resume)
            assert await nav.message_target(PEER, {}) == TARGET
            assert (await nav.menus.get(PEER))['stack'] == original_path
            assert await menus.get('staged', menus.staging_key(PEER, TARGET)) == staged
        # A deliberately chosen new conversation becomes the remembered one.
        replacement = dict(TARGET, session_id='child')
        await nav.action(PEER, 'select', target=replacement)
        await nav.action(PEER, 'collections')
        choices = [b for b in await buttons(menus) if b['action'] == 'select']
        assert len(choices) == 1 and choices[0]['target'] == replacement
        # A second sender has no access to the first sender's return entry.
        await nav.action('another-peer', 'collections')
        assert not any(b['action'] == 'select' for _, b in await menus.records('callbacks')
                       if b.get('peer') == 'another-peer')
    asyncio.run(run())


def test_deleted_remembered_conversation_is_not_offered(menus):
    async def run():
        await menus.put('selection', PEER, dict(TARGET, session_id='deleted'))
        await menus.navigation.action(PEER, 'collections')
        assert not any(b['action'] == 'select' for b in await buttons(menus))
    asyncio.run(run())
