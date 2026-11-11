import asyncio
from unittest.mock import Mock

import pytest

from tests.test_collection_default_roles import services
from app.infra.workspace_catalog_changes import WorkspaceCatalogChanges, workspace_catalog_changes
from app.services.application import conversation_creation
from app.schemas.project.project_conversations import ProjectConversationCreateRequest
from app.services.project.project_conversations import ProjectConversationService


def test_threaded_notifications_coalesce_and_unsubscribe():
    async def run():
        bus = WorkspaceCatalogChanges()
        async with bus.subscribe() as queue:
            await asyncio.to_thread(lambda:[bus.publish('p') for _ in range(50)])
            bus.publish('q'); bus.publish()
            await asyncio.sleep(0)
            event = queue.get_nowait()
            assert queue.empty()
            assert event == {'kind':'changed','catalog':True,'projects':['p','q'],'reset':False}
        bus.publish('closed')
        await asyncio.sleep(0)
        assert queue.empty()
    asyncio.run(run())


def test_large_burst_requests_reconciliation_instead_of_dropping_projects():
    async def run():
        bus = WorkspaceCatalogChanges()
        async with bus.subscribe() as queue:
            for i in range(300):
                bus.publish(str(i))
            await asyncio.sleep(0)
            event = queue.get_nowait()
            assert event['reset'] and event['projects'] == []
    asyncio.run(run())


def test_mobile_create_publishes_committed_session_without_changing_desktop_selection(services):
    projects, conversations, roles, creation = services
    project = creation.create_project(name='通知测试')
    original = conversations.get_state(project.project_id)
    async def run():
        async with workspace_catalog_changes.subscribe() as queue:
            created = await asyncio.to_thread(conversation_creation.create_conversation, project.project_id,
                ProjectConversationCreateRequest(title='手机新会话', activate=False, created_by='user'),
                service=conversations, projects=projects, roles=roles)
            await asyncio.sleep(0)
            event = queue.get_nowait()
            assert project.project_id in event['projects']
            assert conversations.get_session(project.project_id, created.session_id).title == '手机新会话'
            assert conversations.get_state(project.project_id)[0] == original[0]
            assert created.role_project_id == roles.get_default_roles()['project']
    asyncio.run(run())


def test_failed_write_does_not_publish(monkeypatch):
    from app.services.project import project_conversations
    publish = Mock()
    monkeypatch.setattr(project_conversations, 'workspace_catalog_changes', type('Bus', (), {'publish':publish})())
    repository = Mock()
    repository.update_session.side_effect = ValueError('disk write failed')
    with pytest.raises(ValueError):
        ProjectConversationService(repository).update_session('p','s',title='new',should_update_title=True)
    publish.assert_not_called()


def test_unchanged_catalog_save_does_not_create_refresh_loop(services):
    projects, _, _, creation = services
    project = creation.create_project(name='相同数据')
    async def run():
        async with workspace_catalog_changes.subscribe() as queue:
            await asyncio.to_thread(projects._repository.save_project, project)
            await asyncio.sleep(0)
            assert queue.empty()
    asyncio.run(run())
