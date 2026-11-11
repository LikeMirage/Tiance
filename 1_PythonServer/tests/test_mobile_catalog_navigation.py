import asyncio
from types import SimpleNamespace as NS
from unittest.mock import Mock, AsyncMock

import pytest
from PIL import Image

from tests.test_mobile_access import host, repository
from tests.test_collection_default_roles import services
from app.domain.project import ProjectKind
from app.services.mobile import catalog, models, context, navigation, catalog_navigation as menus
from app.services.mobile import relationship_diagram as diagram
from app.core.errors import BadRequestError


def test_model_picker_uses_existing_enabled_chat_catalog(monkeypatch):
    query = Mock(return_value=())
    monkeypatch.setattr(models, 'get_llm_model_catalog_service', lambda: NS(list_models=query))
    assert models.available_models() == ()
    query.assert_called_once_with(enabled_only=True, kind='chat')


def test_model_selection_keeps_prompt_permissions_reasoning_and_draft(services, monkeypatch):
    projects, conversations, roles, creation = services
    project = creation.create_project(name='手机切模型')
    session = conversations.list_sessions(project.project_id)[0]
    session = conversations.update_session(project.project_id, session.session_id,
        reasoning_mode='high', should_update_reasoning=True,
        settings={'system_prompt': 'keep', 'tools_enabled': False}, should_update_settings=True)
    monkeypatch.setattr(context, 'get_project_service', lambda: projects)
    monkeypatch.setattr(context, 'get_project_conversation_service', lambda: conversations)
    monkeypatch.setattr(models, 'get_project_conversation_service', lambda: conversations)
    candidate = NS(provider_id='p2', model_id='m2')
    monkeypatch.setattr(models, 'available_models', lambda: [candidate])
    conversations.save_state(project.project_id, session_drafts={session.session_id: '未发送的草稿'},
                             session_references={session.session_id: []}, active_session_id=None,
                             should_update_active_session=False, session_runtime_statuses={})
    before = conversations.get_state(project.project_id)
    models.select_model({'project_id': project.project_id, 'session_id': session.session_id}, 'p2', 'm2')
    saved = conversations.get_session(project.project_id, session.session_id)
    assert (saved.provider_id, saved.model_id) == ('p2', 'm2')
    assert saved.settings == session.settings
    assert saved.reasoning_mode == 'high' and saved.title == session.title
    after = conversations.get_state(project.project_id)
    assert after[0] == before[0]
    assert after[1][session.session_id].draft == '未发送的草稿'
    assert after[1][session.session_id].references == before[1][session.session_id].references
    with pytest.raises(BadRequestError, match='已移除'):
        models.select_model({'project_id': project.project_id, 'session_id': session.session_id}, 'gone', 'm2')
    assert conversations.get_session(project.project_id, session.session_id) == saved


def test_old_model_buttons_keep_their_explicit_session(host, monkeypatch):
    async def run():
        peer = 'telegram:12:7:7'
        target = {'project_id': 'p', 'session_id': 'a'}
        candidate = NS(provider_id='provider', provider_label='供应商', model_id='model', model_label='模型')
        monkeypatch.setattr(models, 'available_models', lambda: [candidate])
        change = Mock(return_value=candidate)
        monkeypatch.setattr(models, 'select_model', change)
        await host.navigation.action(peer, 'model', target=target)
        callback = next(item for _, item in await host.records('callbacks') if item['action'] == 'models')
        await host.put('selection', peer, dict(target, session_id='b'))
        await host.navigation.action(peer, **{k:v for k,v in callback.items() if k != 'peer'})
        callback = next(item for _, item in await host.records('callbacks') if item['action'] == 'setmodel')
        await host.navigation.action(peer, **{k:v for k,v in callback.items() if k != 'peer'})
        assert change.call_args.args == (target, 'provider', 'model')
        assert (await host.get('selection', peer))['session_id'] == 'b'
    asyncio.run(run())


@pytest.mark.parametrize('kind', [k for k in ProjectKind if k != ProjectKind.PROVIDER])
def test_project_creation_routes_through_application_service(kind, monkeypatch):
    create = Mock(return_value=NS(project_id='new'))
    monkeypatch.setattr(catalog, 'get_project_service', lambda: NS(get_project_category=lambda _:NS(category_kind=kind)))
    monkeypatch.setattr(catalog, 'get_project_creation_application_service', lambda:NS(create_project=create))
    assert catalog.create_project(kind.value, 'cat', 'new').project_id == 'new'
    create.assert_called_once_with(name='new', category_id='cat', project_kind=kind)


def test_provider_creation_uses_provider_service_and_initial_role(monkeypatch):
    from app.services.llm.provider import catalog_mutation, workspace_registry
    create = Mock(return_value=NS(provider_id='provider'))
    initial = Mock()
    monkeypatch.setattr(catalog_mutation, 'get_provider_catalog_mutation_service', lambda:NS(create_provider=create))
    monkeypatch.setattr(catalog, 'get_project_creation_application_service', lambda:NS(ensure_initial_conversation=initial))
    monkeypatch.setattr(catalog, 'get_project_service', lambda:NS(
        get_project_category=lambda _:NS(category_kind=ProjectKind.PROVIDER),
        get_project=lambda pid:NS(project_id=pid)))
    result = catalog.create_project('provider', 'cat', '供应商')
    assert result.project_id == workspace_registry.provider_project_id('provider')
    assert create.call_args.kwargs['category_id'] == 'cat'
    initial.assert_called_once_with(result.project_id)


def test_wrong_collection_category_is_rejected_before_creating(monkeypatch):
    create = Mock()
    monkeypatch.setattr(catalog, 'get_project_service', lambda:NS(get_project_category=lambda _:NS(category_kind='theme')))
    monkeypatch.setattr(catalog, 'get_project_creation_application_service', create)
    with pytest.raises(BadRequestError):
        catalog.create_project('tool', 'theme-category', 'name')
    create.assert_not_called()
    with pytest.raises(BadRequestError):
        catalog.collection_kind('settings')


def test_creation_uses_browsed_collection_not_old_selected_session(host, monkeypatch):
    async def run():
        host.config['allowed_collections'] = ['project', 'tool']
        peer = 'telegram:12:7:7'; selected = {'project_id':'p', 'session_id':'a'}
        await host.put('selection', peer, selected)
        await host.put('navigation', peer, {'kind':'tool', 'category':'tools'})
        categories = Mock(return_value=NS(category_id='newcat'))
        monkeypatch.setattr(catalog, 'create_category', categories)
        monkeypatch.setattr(navigation, 'get_project_service', lambda:NS(list_projects=lambda:[]))
        await host.navigation.action(peer, 'newcategory', title='办公工具')
        categories.assert_called_once_with('tool', '办公工具')
        assert await host.get('navigation', peer) == {'kind':'tool', 'category':'newcat'}
        assert await host.get('selection', peer) == selected
    asyncio.run(run())


def test_outline_keeps_empty_groups_and_only_root_sessions(monkeypatch):
    root = NS(session_id='main', title='主会话')
    child = NS(session_id='child', title='不应显示')
    nodes = [NS(session_id='main', parent_session_id=None, deleted_at=None, relation_kind='root'),
             NS(session_id='child', parent_session_id='main', deleted_at=None, relation_kind='child')]
    query = Mock(return_value=(None, [root,child], nodes, [], {}, None))
    monkeypatch.setattr(context, 'get_project_conversation_service', lambda:NS(get_list_data=query))
    monkeypatch.setattr(catalog, 'get_project_service', lambda:NS(
        list_project_categories=lambda:[NS(category_id='cat',name='分类',category_kind='tool'),NS(category_id='empty',name='空分类',category_kind='tool')],
        list_projects=lambda:[NS(project_id='p',category_id='cat',name='项目',project_kind='tool'),
                              NS(project_id='excluded',category_id='cat',name='其他集',project_kind='project')]))
    outline = catalog.collection_outline('tool')
    assert outline['categories'][0]['projects'][0]['sessions'] == [{'id':'main','name':'主会话'}]
    assert outline['categories'][1]['projects'] == []
    query.assert_called_once_with('p', summaries_only=True)


def test_diagram_pages_preserve_every_long_label(tmp_path, monkeypatch):
    labels = [f'第{i}个主会话 —— 测试中文长标题可以换行且不被省略' for i in range(50)]
    outline = {'name':'工具集', 'categories':[{'id':'cat','name':'办公', 'projects':[
        {'id':'p','name':'转写工具','sessions':[{'id':str(i),'name':name} for i,name in enumerate(labels)]}]}]}
    written = []
    original = diagram.ImageDraw.ImageDraw.text
    def capture(self, xy, text, *args, **kwargs):
        written.append(text)
        return original(self, xy, text, *args, **kwargs)
    monkeypatch.setattr(diagram.ImageDraw.ImageDraw, 'text', capture)
    files = diagram.render_diagram(outline, tmp_path)
    assert len(files) > 1
    for name in labels:
        assert name in ''.join(written)
    for file in files:
        with Image.open(file) as image:
            assert image.width == 1520 and image.height <= 1800


def test_diagram_delivery_keeps_file_until_confirmed_and_cleans_owned_png(host, tmp_path, monkeypatch):
    async def run():
        peer = 'telegram:12:7:7'
        monkeypatch.setattr(diagram, 'diagram_directory', lambda:tmp_path)
        path = tmp_path/'graph.png'; path.write_bytes(b'png')
        await host.put('peers', peer, {'bot_id':12,'chat_id':7,'user_id':7,'allowed':True})
        await host.reply_diagram(peer, path, '项目集', [])
        assert path.exists()
        host.transport.send_once = AsyncMock(return_value={'message_id':100})
        loop = asyncio.create_task(host.delivery_loop())
        try:
            for _ in range(100):
                await asyncio.sleep(.01)
                if not await host.records('outbox'):
                    break
            assert not await host.records('outbox')
            assert not path.exists()
            assert host.transport.send_once.call_args.args[0] == 'sendDocument'
            assert (await host.get('messages', peer+':100'))['target'] is None
            with pytest.raises(BadRequestError, match='对应关系'):
                await host.navigation.message_target(peer, {'reply_to_message': {'message_id': 100}})
        finally:
            loop.cancel()
            await asyncio.gather(loop, return_exceptions=True)
    asyncio.run(run())


def test_cancel_during_render_joins_worker_and_removes_only_generated_files(host, tmp_path, monkeypatch):
    from threading import Event
    entered, release = Event(), Event()
    path = tmp_path/'diagram.png'
    monkeypatch.setattr(diagram, 'diagram_directory', lambda:tmp_path)
    monkeypatch.setattr(catalog, 'collection_outline', lambda _: {})
    def render(_):
        entered.set()
        assert release.wait(3)
        path.write_bytes(b'image')
        return [path]
    monkeypatch.setattr(menus, 'render_diagram', render)
    async def run():
        key = ('peer','project')
        task = asyncio.create_task(host.navigation.catalog.diagram('peer','project',key))
        assert await asyncio.to_thread(entered.wait, 3)
        task.cancel()
        await asyncio.sleep(0)
        release.set()
        result = await asyncio.gather(task, return_exceptions=True)
        assert isinstance(result[0], asyncio.CancelledError)
        assert not path.exists()
        assert not await host.records('outbox')
    asyncio.run(run())
