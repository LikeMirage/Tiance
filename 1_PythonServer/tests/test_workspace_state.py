from json import dumps, loads

import pytest

from app.core.errors import BadRequestError, NotFoundError
from app.domain.project import ProjectCategory, ProjectKind
from app.infra.database import ensure_database_schema
from app.infra.projects import ProjectStorage
from app.repositories.project import ProjectRepository
from app.repositories.project.conversation_repository import ProjectConversationRepository
from app.schemas.workspace import WorkspaceLayoutPreferencesResponse
from app.services.project.project_conversations import ProjectConversationService
from app.services.project.projects import ProjectService
from app.services.workspace_state import (
    WORKSPACE_LAST_OPENED_KEY,
    WORKSPACE_LAYOUT_PREFERENCES_KEY,
    WorkspaceStateService,
)


def test_workspace_last_opened_is_empty_by_default(tmp_path):
    _, service, _, _ = _create_services(tmp_path)
    state = service.get_last_opened()
    assert state.project_id is None
    assert state.category_id is None
    assert state.updated_at is None
    assert not hasattr(state, "session_id")


def test_workspace_last_opened_persists_only_project_selection(tmp_path):
    from app.schemas.workspace import WorkspaceLastOpenedResponse

    projects, service, repository, conversations = _create_services(tmp_path)
    project = projects.create_project(name="项目 A")
    session = conversations.create_session(project.project_id, title="会话 A",
        provider_id=None, model_id=None, reasoning_mode=None)
    saved = service.save_last_opened(project_id=project.project_id)
    assert saved.project_id == project.project_id
    assert saved.category_id == project.category_id
    assert saved.updated_at is not None
    assert service.get_last_opened() == saved
    payload = loads(repository.get_metadata_value(WORKSPACE_LAST_OPENED_KEY))
    assert payload["project_id"] == project.project_id
    assert payload["active_category_id"] == project.category_id
    assert payload["category_selections"][project.category_id]["project_id"] == project.project_id
    assert "session_id" not in dumps(payload)
    assert "session_id" not in WorkspaceLastOpenedResponse.from_domain(saved).model_dump_json()
    # Opening another project never changes this project's own session selection.
    other = projects.create_project(name="项目 B")
    service.save_last_opened(project_id=other.project_id)
    assert conversations.get_state(project.project_id)[0] == session.session_id


def test_workspace_last_opened_keeps_selection_per_category(tmp_path):
    projects, service, _, _ = _create_services(tmp_path)
    a = projects.create_project_category(name="分类 A")
    b = projects.create_project_category(name="分类 B")
    pa = projects.create_project(name="项目 A", category_id=a.category_id)
    pb = projects.create_project(name="项目 B", category_id=b.category_id)
    service.save_last_opened(project_id=pa.project_id)
    service.save_last_opened(project_id=pb.project_id)
    active = service.get_last_opened()
    assert active.project_id == pb.project_id
    assert {item.category_id: item.project_id for item in active.category_selections} == {
        a.category_id: pa.project_id, b.category_id: pb.project_id,
    }
    assert service.save_last_opened(category_id=a.category_id).project_id == pa.project_id


def test_workspace_last_opened_ignores_old_global_session_hint(tmp_path):
    projects, service, repository, _ = _create_services(tmp_path)
    project = projects.create_project(name="项目 A")
    repository.set_metadata_value(key=WORKSPACE_LAST_OPENED_KEY, value=dumps({
        "active_category_id": project.category_id, "session_id": "stale",
        "category_selections": {project.category_id: {
            "project_id": project.project_id, "session_id": "missing-session",
            "updated_at": "2026-06-20T00:00:00+00:00",
        }},
    }), updated_at="old")
    state = service.get_last_opened()
    assert state.project_id == project.project_id
    assert state.updated_at == "2026-06-20T00:00:00+00:00"
    assert not hasattr(state, "session_id")
    service.save_last_opened(project_id=project.project_id)
    assert "session_id" not in repository.get_metadata_value(WORKSPACE_LAST_OPENED_KEY)


def test_workspace_last_opened_validates_project_membership(tmp_path):
    projects, service, _, _ = _create_services(tmp_path)
    project = projects.create_project(name="项目 A")
    other = projects.create_project_category(name="其他分类")
    with pytest.raises(NotFoundError):
        service.save_last_opened(project_id="00000000-0000-0000-0000-000000000000")
    with pytest.raises(BadRequestError):
        service.save_last_opened(category_id=other.category_id, project_id=project.project_id)


def test_restore_preferences_never_opens_remembered_project_databases(tmp_path, monkeypatch):
    from app.repositories.project import conversation_database

    projects, service, repository, _ = _create_services(tmp_path)
    first = projects.create_project(name="当前项目")
    category = projects.create_project_category(name="另一个分类")
    other = projects.create_project(name="旧库项目", category_id=category.category_id)
    repository.set_metadata_value(key=WORKSPACE_LAST_OPENED_KEY, value=dumps({
        "active_category_id": first.category_id, "category_selections": {
            first.category_id: {"project_id": first.project_id, "session_id": "remembered"},
            other.category_id: {"project_id": other.project_id, "session_id": "old-session"},
        },
    }), updated_at="now")

    def must_not_read(*args, **kwargs):
        raise AssertionError("Navigation must not read or migrate any project database")

    monkeypatch.setattr(conversation_database, "_open_connection", must_not_read)
    restored = service.get_last_opened()
    assert restored.project_id == first.project_id
    assert {item.project_id for item in restored.category_selections} == {first.project_id, other.project_id}
    assert service.save_last_opened(category_id=other.category_id).project_id == other.project_id
    assert service.save_last_opened(project_id=first.project_id).project_id == first.project_id


@pytest.mark.parametrize("old_mode", ["grid", "wide", "roller", "stack"])
def test_workspace_layout_preferences_drop_old_modes_without_losing_other_settings(tmp_path, old_mode):
    project_service, workspace_service, repository, _conversation_service = _create_services(
        tmp_path,
    )
    project = project_service.create_project(name="项目 A")
    payload = {
        "version": 6,
        "side_panel_width": 310,
        "ai_panel_width": 480,
        "composer_height": 200,
        "project_overview_layout_modes": {project.category_id: old_mode},
        "project_overview_maximized_project_ids": {project.category_id: project.project_id},
        "project_overview_views": {project.category_id: "conversation"},
        "tool_overview_views": {"tools": "online"},
        "collection_overview_views": {"roles": "specialized"},
    }
    repository.set_metadata_value(
        key=WORKSPACE_LAYOUT_PREFERENCES_KEY, value=dumps(payload), updated_at="old",
    )
    loaded = workspace_service.get_layout_preferences()
    expected = {key: value for key, value in payload.items() if key != "project_overview_layout_modes"}
    expected["version"] = 7
    assert WorkspaceLayoutPreferencesResponse.from_domain(loaded).model_dump() == expected
    saved = workspace_service.save_layout_preferences(side_panel_width=320)
    expected["side_panel_width"] = 320
    assert WorkspaceLayoutPreferencesResponse.from_domain(saved).model_dump() == expected
    assert workspace_service.get_layout_preferences() == saved
    assert loads(repository.get_metadata_value(WORKSPACE_LAYOUT_PREFERENCES_KEY)) == expected


def test_workspace_layout_preferences_start_without_layout_mode_settings(tmp_path):
    _project_service, workspace_service, repository, _conversation_service = _create_services(
        tmp_path,
    )
    assert "project_overview_layout_modes" not in WorkspaceLayoutPreferencesResponse.from_domain(
        workspace_service.get_layout_preferences(),
    ).model_dump()
    saved = workspace_service.save_layout_preferences(side_panel_width=320)
    assert saved.side_panel_width == 320
    assert workspace_service.get_layout_preferences() == saved
    assert "project_overview_layout_modes" not in loads(
        repository.get_metadata_value(WORKSPACE_LAYOUT_PREFERENCES_KEY),
    )


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
    workspace_service = WorkspaceStateService(repository)
    return project_service, workspace_service, repository, conversation_service
