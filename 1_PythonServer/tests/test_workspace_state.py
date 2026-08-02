from json import dumps, loads

import pytest

from app.core.errors import BadRequestError, NotFoundError
from app.domain.project import ProjectCategory, ProjectKind
from app.infra.database import ensure_database_schema
from app.infra.projects import ProjectStorage
from app.repositories.project import ProjectRepository
from app.repositories.project.conversation_repository import ProjectConversationRepository
from app.services.project.project_conversations import ProjectConversationService
from app.services.project.projects import ProjectService
from app.services.workspace_state import (
    WORKSPACE_LAST_OPENED_KEY,
    WORKSPACE_LAYOUT_PREFERENCES_KEY,
    WorkspaceStateService,
)


def test_workspace_last_opened_is_empty_by_default(tmp_path):
    _project_service, workspace_service, _repository, _conversation_service = _create_services(tmp_path)

    state = workspace_service.get_last_opened()

    assert state.project_id is None
    assert state.category_id is None
    assert state.session_id is None
    assert state.updated_at is None


def test_workspace_last_opened_persists_project_and_session(tmp_path):
    project_service, workspace_service, repository, conversation_service = _create_services(tmp_path)
    project = project_service.create_project(name="项目 A")
    session = conversation_service.create_session(
        project.project_id,
        title="会话 A",
        provider_id=None,
        model_id=None,
        reasoning_mode=None,
    )

    saved = workspace_service.save_last_opened(
        project_id=project.project_id,
        session_id=session.session_id,
    )
    loaded = workspace_service.get_last_opened()

    assert saved.project_id == project.project_id
    assert saved.category_id == project.category_id
    assert saved.session_id == session.session_id
    assert saved.updated_at is not None
    assert loaded == saved

    raw = repository.get_metadata_value(WORKSPACE_LAST_OPENED_KEY)
    assert raw is not None
    payload = loads(raw)
    assert payload["project_id"] == project.project_id
    assert payload["session_id"] == session.session_id
    assert payload["active_category_id"] == project.category_id
    assert payload["category_selections"][project.category_id]["project_id"] == project.project_id
    assert payload["category_selections"][project.category_id]["session_id"] == session.session_id


def test_workspace_last_opened_keeps_selection_per_category(tmp_path):
    project_service, workspace_service, _repository, conversation_service = _create_services(tmp_path)
    category_a = project_service.create_project_category(name="分类 A")
    category_b = project_service.create_project_category(name="分类 B")
    project_a = project_service.create_project(name="项目 A", category_id=category_a.category_id)
    project_b = project_service.create_project(name="项目 B", category_id=category_b.category_id)
    session_a = conversation_service.create_session(
        project_a.project_id,
        title="会话 A",
        provider_id=None,
        model_id=None,
        reasoning_mode=None,
    )
    session_b = conversation_service.create_session(
        project_b.project_id,
        title="会话 B",
        provider_id=None,
        model_id=None,
        reasoning_mode=None,
    )

    workspace_service.save_last_opened(
        project_id=project_a.project_id,
        session_id=session_a.session_id,
    )
    workspace_service.save_last_opened(
        project_id=project_b.project_id,
        session_id=session_b.session_id,
    )

    active_b = workspace_service.get_last_opened()
    assert active_b.category_id == category_b.category_id
    assert active_b.project_id == project_b.project_id
    assert active_b.session_id == session_b.session_id
    assert {
        selection.category_id: selection.session_id
        for selection in active_b.category_selections
    } == {
        category_a.category_id: session_a.session_id,
        category_b.category_id: session_b.session_id,
    }

    active_a = workspace_service.save_last_opened(
        category_id=category_a.category_id,
        session_id=None,
    )

    assert active_a.category_id == category_a.category_id
    assert active_a.project_id == project_a.project_id
    assert active_a.session_id == session_a.session_id


def test_workspace_last_opened_ignores_stale_session(tmp_path):
    project_service, workspace_service, repository, _conversation_service = _create_services(tmp_path)
    project = project_service.create_project(name="项目 A")
    repository.set_metadata_value(
        key=WORKSPACE_LAST_OPENED_KEY,
        value=dumps({
            "project_id": project.project_id,
            "session_id": "missing-session",
            "updated_at": "2026-06-20T00:00:00+00:00",
        }),
        updated_at="2026-06-20T00:00:00+00:00",
    )

    state = workspace_service.get_last_opened()

    assert state.project_id == project.project_id
    assert state.category_id == project.category_id
    assert state.session_id is None
    assert state.updated_at == "2026-06-20T00:00:00+00:00"


def test_workspace_last_opened_rejects_missing_session_on_save(tmp_path):
    project_service, workspace_service, _repository, _conversation_service = _create_services(tmp_path)
    project = project_service.create_project(name="项目 A")

    with pytest.raises(NotFoundError):
        workspace_service.save_last_opened(
            project_id=project.project_id,
            session_id="missing-session",
        )


def test_workspace_layout_preferences_persist_project_overview_mode_per_category(tmp_path):
    project_service, workspace_service, repository, _conversation_service = _create_services(
        tmp_path,
    )
    category_a = project_service.create_project_category(name="分类 A")
    category_b = project_service.create_project_category(name="分类 B")

    workspace_service.save_layout_preferences(
        project_overview_category_id=category_a.category_id,
        project_overview_layout_mode="stack",
    )
    saved = workspace_service.save_layout_preferences(
        project_overview_category_id=category_b.category_id,
        project_overview_layout_mode="roller",
    )
    loaded = workspace_service.get_layout_preferences()

    expected = {
        category_a.category_id: "stack",
        category_b.category_id: "roller",
    }
    assert {
        item.category_id: item.layout_mode
        for item in saved.project_overview_layouts
    } == expected
    assert loaded == saved

    raw = repository.get_metadata_value(WORKSPACE_LAYOUT_PREFERENCES_KEY)
    assert raw is not None
    assert loads(raw)["project_overview_layout_modes"] == expected


def test_workspace_layout_size_update_keeps_project_overview_modes(tmp_path):
    project_service, workspace_service, _repository, _conversation_service = _create_services(
        tmp_path,
    )
    category = project_service.create_project_category(name="分类 A")
    workspace_service.save_layout_preferences(
        project_overview_category_id=category.category_id,
        project_overview_layout_mode="wide",
    )

    saved = workspace_service.save_layout_preferences(side_panel_width=320)

    assert saved.side_panel_width == 320
    assert {
        item.category_id: item.layout_mode
        for item in saved.project_overview_layouts
    } == {category.category_id: "wide"}


def test_workspace_layout_preferences_do_not_persist_project_branch_view(tmp_path):
    project_service, workspace_service, repository, _conversation_service = _create_services(
        tmp_path,
    )
    category_a = project_service.create_project_category(name="分类 A")
    category_b = project_service.create_project_category(name="分类 B")

    workspace_service.save_layout_preferences(
        project_overview_view_category_id=category_a.category_id,
        project_overview_view="conversation",
    )
    saved = workspace_service.save_layout_preferences(
        project_overview_view_category_id=category_b.category_id,
        project_overview_view="branches",
    )

    expected = {
        category_a.category_id: "conversation",
        category_b.category_id: "projects",
    }
    assert {
        item.category_id: item.view
        for item in saved.project_overview_views
    } == expected
    assert workspace_service.get_layout_preferences() == saved

    raw = repository.get_metadata_value(WORKSPACE_LAYOUT_PREFERENCES_KEY)
    assert raw is not None
    assert loads(raw)["project_overview_views"] == expected


def test_workspace_layout_preferences_do_not_persist_tool_branch_view(tmp_path):
    _project_service, workspace_service, repository, _conversation_service = _create_services(
        tmp_path,
    )
    category = repository.save_project_category(
        ProjectCategory(
            category_id="toolset-test",
            name="测试工具集",
            category_kind=ProjectKind.TOOL,
            is_default=False,
            sort_order=0,
            created_at="2026-07-31T00:00:00Z",
            updated_at="2026-07-31T00:00:00Z",
        ),
    )

    saved = workspace_service.save_layout_preferences(
        tool_overview_view_category_id=category.category_id,
        tool_overview_view="branches",
    )

    assert {
        item.category_id: item.view
        for item in saved.tool_overview_views
    } == {category.category_id: "tools"}
    assert workspace_service.get_layout_preferences() == saved

    raw = repository.get_metadata_value(WORKSPACE_LAYOUT_PREFERENCES_KEY)
    assert raw is not None
    assert loads(raw)["tool_overview_views"] == {
        category.category_id: "tools",
    }


def test_workspace_layout_preferences_reset_legacy_branch_views_on_load(tmp_path):
    _project_service, workspace_service, repository, _conversation_service = _create_services(
        tmp_path,
    )
    repository.set_metadata_value(
        key=WORKSPACE_LAYOUT_PREFERENCES_KEY,
        value=dumps({
            "version": 6,
            "project_overview_views": {"project-category": "branches"},
            "tool_overview_views": {"tool-category": "branches"},
        }),
        updated_at="2026-08-01T00:00:00Z",
    )

    loaded = workspace_service.get_layout_preferences()

    assert {
        item.category_id: item.view
        for item in loaded.project_overview_views
    } == {"project-category": "projects"}
    assert {
        item.category_id: item.view
        for item in loaded.tool_overview_views
    } == {"tool-category": "tools"}


def test_workspace_layout_preferences_persist_collection_overview_views(tmp_path):
    _project_service, workspace_service, repository, _conversation_service = _create_services(
        tmp_path,
    )
    role_category = repository.save_project_category(
        ProjectCategory(
            category_id="role-category-test",
            name="测试角色集",
            category_kind=ProjectKind.ROLE,
            is_default=False,
            sort_order=0,
            created_at="2026-07-31T00:00:00Z",
            updated_at="2026-07-31T00:00:00Z",
        ),
    )
    theme_category = repository.save_project_category(
        ProjectCategory(
            category_id="theme-category-test",
            name="测试主题集",
            category_kind=ProjectKind.THEME,
            is_default=False,
            sort_order=0,
            created_at="2026-07-31T00:00:00Z",
            updated_at="2026-07-31T00:00:00Z",
        ),
    )

    workspace_service.save_layout_preferences(
        collection_overview_view_category_id=role_category.category_id,
        collection_overview_view="conversation",
    )
    saved = workspace_service.save_layout_preferences(
        collection_overview_view_category_id=theme_category.category_id,
        collection_overview_view="online",
    )

    expected = {
        role_category.category_id: "conversation",
        theme_category.category_id: "online",
    }
    assert {
        item.category_id: item.view
        for item in saved.collection_overview_views
    } == expected
    assert workspace_service.get_layout_preferences() == saved

    raw = repository.get_metadata_value(WORKSPACE_LAYOUT_PREFERENCES_KEY)
    assert raw is not None
    assert loads(raw)["collection_overview_views"] == expected


def test_workspace_layout_preferences_migrate_existing_maximized_project_to_conversation_view(
    tmp_path,
):
    project_service, workspace_service, repository, _conversation_service = _create_services(
        tmp_path,
    )
    category = project_service.create_project_category(name="分类 A")
    project = project_service.create_project(name="项目 A", category_id=category.category_id)
    repository.set_metadata_value(
        key=WORKSPACE_LAYOUT_PREFERENCES_KEY,
        value=dumps({
            "version": 3,
            "project_overview_maximized_project_ids": {
                category.category_id: project.project_id,
            },
        }),
        updated_at="2026-07-31T00:00:00Z",
    )

    loaded = workspace_service.get_layout_preferences()

    assert {
        item.category_id: item.view
        for item in loaded.project_overview_views
    } == {category.category_id: "conversation"}


def test_workspace_layout_preferences_persist_maximized_project_per_category(tmp_path):
    project_service, workspace_service, repository, _conversation_service = _create_services(
        tmp_path,
    )
    category_a = project_service.create_project_category(name="分类 A")
    category_b = project_service.create_project_category(name="分类 B")
    project_a = project_service.create_project(name="项目 A", category_id=category_a.category_id)
    project_b = project_service.create_project(name="项目 B", category_id=category_b.category_id)

    workspace_service.save_layout_preferences(
        project_overview_maximized_category_id=category_a.category_id,
        project_overview_maximized_project_id=project_a.project_id,
        update_project_overview_maximized=True,
    )
    saved = workspace_service.save_layout_preferences(
        project_overview_maximized_category_id=category_b.category_id,
        project_overview_maximized_project_id=project_b.project_id,
        update_project_overview_maximized=True,
    )

    assert {
        item.category_id: item.project_id
        for item in saved.project_overview_maximized
    } == {
        category_a.category_id: project_a.project_id,
        category_b.category_id: project_b.project_id,
    }

    cleared = workspace_service.save_layout_preferences(
        project_overview_maximized_category_id=category_a.category_id,
        project_overview_maximized_project_id=None,
        update_project_overview_maximized=True,
    )
    assert {
        item.category_id: item.project_id
        for item in cleared.project_overview_maximized
    } == {category_b.category_id: project_b.project_id}

    raw = repository.get_metadata_value(WORKSPACE_LAYOUT_PREFERENCES_KEY)
    assert raw is not None
    assert loads(raw)["project_overview_maximized_project_ids"] == {
        category_b.category_id: project_b.project_id,
    }


def test_workspace_layout_preferences_reject_maximized_project_from_other_category(
    tmp_path,
):
    project_service, workspace_service, _repository, _conversation_service = _create_services(
        tmp_path,
    )
    category_a = project_service.create_project_category(name="分类 A")
    category_b = project_service.create_project_category(name="分类 B")
    project = project_service.create_project(name="项目 A", category_id=category_a.category_id)

    with pytest.raises(BadRequestError):
        workspace_service.save_layout_preferences(
            project_overview_maximized_category_id=category_b.category_id,
            project_overview_maximized_project_id=project.project_id,
            update_project_overview_maximized=True,
        )


def _create_services(tmp_path):
    database_path = tmp_path / "tiance.db"
    ensure_database_schema(database_path)
    repository = ProjectRepository(database_path)
    project_service = ProjectService(
        repository,
        ProjectStorage(tmp_path / "managed-projects"),
    )
    conversation_service = ProjectConversationService(
        ProjectConversationRepository(repository),
    )
    workspace_service = WorkspaceStateService(repository, conversation_service)
    return project_service, workspace_service, repository, conversation_service
