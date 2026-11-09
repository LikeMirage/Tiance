from hashlib import sha256
from json import dumps, loads

from app.infra.database import ensure_database_schema
from app.infra.file_workspace import FileWorkspaceStorage
from app.infra.projects import ProjectStorage
from app.repositories.roles.default_role_repository import DefaultRoleRepository
from app.repositories.project import ProjectRepository
from app.repositories.project.conversation_repository import (
    ProjectConversationRepository,
)
from app.repositories.project.conversation_serialization import (
    _session_from_payload,
    _session_to_payload,
)
from app.schemas.project.project_conversations import (
    ProjectConversationSessionResponse,
)
from app.services.application.role_configuration import (
    DEFAULT_ROLE_NAME,
    RoleConfigurationApplicationService,
)
from app.services.document_conversion import MarkdownDocxService
from app.domain.project import ProjectKind
from app.services.project.project_conversations import ProjectConversationService
from app.services.project.project_files import ProjectFileService
from app.services.project.projects import ProjectService


def _build_services(tmp_path):
    database_path = tmp_path / "tiance.db"
    ensure_database_schema(database_path)
    repository = ProjectRepository(database_path)
    project_service = ProjectService(
        repository,
        ProjectStorage(tmp_path / "projects", tmp_path / "roles"),
    )
    conversation_service = ProjectConversationService(
        ProjectConversationRepository(repository),
    )
    default_roles_repository = DefaultRoleRepository(database_path)
    role_service = RoleConfigurationApplicationService(
        project_service,
        conversation_service,
        ProjectFileService(
            repository,
            FileWorkspaceStorage(),
            MarkdownDocxService(),
        ),
        default_roles_repository,
    )
    return (
        project_service,
        conversation_service,
        role_service,
        default_roles_repository,
    )


def test_default_role_is_created_once(tmp_path):
    project_service, _conversation_service, role_service, default_roles = (
        _build_services(tmp_path)
    )

    first = role_service.ensure_default_role()
    second = role_service.ensure_default_role()

    assert first.project_id == second.project_id
    assert first.name == DEFAULT_ROLE_NAME
    assert [
        project
        for project in project_service.list_projects()
        if project.name == DEFAULT_ROLE_NAME
    ] == [first]
    assert role_service.get_default_roles() == {kind.value: first.project_id for kind in ProjectKind}
    response = loads((tmp_path / "roles" / first.project_id / "response.json").read_text(encoding="utf-8"))
    assert response["output_limit_action"] == "send_message"
    assert response["output_limit_save_partial"] is True
    seed = role_service.build_new_session_seed()
    assert seed.settings["output_limit_action"] == "send_message"
    assert seed.settings["output_limit_save_partial"] is True


def test_existing_role_cannot_restore_removed_cancellation_options(tmp_path):
    _project_service, _conversation_service, role_service, _default_roles = (
        _build_services(tmp_path)
    )
    role = role_service.ensure_default_role()
    response_file = tmp_path / "roles" / role.project_id / "response.json"
    response = loads(response_file.read_text(encoding="utf-8"))
    response.update({
        "return_cancelled_messages": False,
        "return_user_before_cancelled": False,
        "upstream_retry_count": 4,
    })
    response_file.write_text(dumps(response), encoding="utf-8")

    seed = role_service.build_new_session_seed(role.project_id)

    assert "return_cancelled_messages" not in seed.settings
    assert "return_user_before_cancelled" not in seed.settings
    assert seed.settings["upstream_retry_count"] == 4


def test_role_application_ignores_invalid_fields_and_tracks_custom_state(tmp_path):
    project_service, conversation_service, role_service, _default_roles = (
        _build_services(tmp_path)
    )
    role = role_service.ensure_default_role()
    project = project_service.create_project(name="测试项目")
    source = conversation_service.create_session(
        project.project_id,
        provider_id="custom-provider",
        model_id="custom-model",
        reasoning_mode="off",
        settings={
            "temperature": 0.4,
            "top_p": 0.7,
            "system_prompt": "保留内容",
        },
    )
    role_root = tmp_path / "roles" / role.project_id
    (role_root / "generation.json").write_text(
        dumps(
            {
                "temperature": 1.2,
                "top_p": "invalid",
                "max_output_tokens": -1,
            }
        ),
        encoding="utf-8",
    )
    (role_root / "prompt.json").write_text("{broken", encoding="utf-8")
    (role_root / "tools.json").write_text(
        dumps(
            {
                "tools_enabled": True,
                "enabled_tool_names": None,
                "max_tool_calls": 99999,
                "tool_approval_mode": "follow_tool_policy",
            }
        ),
        encoding="utf-8",
    )

    applied = role_service.apply_role(
        project.project_id,
        source.session_id,
        role.project_id,
    )

    assert applied.settings.temperature == 1.2
    assert applied.settings.top_p == 0.7
    assert applied.settings.system_prompt == "保留内容"
    assert applied.settings.tool_approval_mode == "follow_tool_policy"
    assert ProjectConversationSessionResponse.from_domain(applied).role_status == "selected"

    renamed = conversation_service.update_session(
        project.project_id,
        source.session_id,
        title="只修改标题",
        should_update_title=True,
    )
    assert ProjectConversationSessionResponse.from_domain(renamed).role_status == "selected"

    edited = conversation_service.update_session(
        project.project_id,
        source.session_id,
        settings={"temperature": 0.8},
        should_update_settings=True,
    )
    assert ProjectConversationSessionResponse.from_domain(edited).role_status == "custom"

    restored = conversation_service.update_session(
        project.project_id,
        source.session_id,
        settings={"temperature": 1.2},
        should_update_settings=True,
    )
    assert restored.role_configuration_hash is None
    assert ProjectConversationSessionResponse.from_domain(restored).role_status == "custom"

    reapplied = role_service.apply_role(
        project.project_id,
        source.session_id,
        role.project_id,
    )
    assert ProjectConversationSessionResponse.from_domain(reapplied).role_status == "selected"


def test_new_session_seed_uses_configured_default_role(tmp_path):
    project_service, _conversation_service, role_service, default_roles = (
        _build_services(tmp_path)
    )
    default_role = role_service.ensure_default_role()
    selected_role = project_service.create_role_project(
        name="角色创建者",
        category_id=default_role.category_id,
    )
    role_service.initialize_role_project(selected_role.project_id)
    default_roles.save(ProjectKind.PROJECT, selected_role.project_id)

    seed = role_service.build_new_session_seed()

    assert seed.role_project_id == selected_role.project_id


def test_missing_configured_role_falls_back_to_default_role(tmp_path):
    _project_service, _conversation_service, role_service, default_roles = (
        _build_services(tmp_path)
    )
    default_role = role_service.ensure_default_role()
    default_roles.save(ProjectKind.PROJECT, "missing-role")

    seed = role_service.build_new_session_seed()
    resolved = role_service.get_default_roles()

    assert seed.role_project_id == default_role.project_id
    assert resolved["project"] == default_role.project_id
    assert default_roles.get_all()["project"] == "missing-role"


def test_role_catalog_follows_project_drag_order(tmp_path):
    project_service, _conversation_service, role_service, _default_roles = (
        _build_services(tmp_path)
    )
    default_role = role_service.ensure_default_role()
    other_role = project_service.create_role_project(
        name="角色创建者",
        category_id=default_role.category_id,
    )
    role_service.initialize_role_project(other_role.project_id)
    project_service.save_project_order(
        (default_role.project_id, other_role.project_id),
    )

    catalog = role_service.get_catalog()

    assert [item.project.project_id for item in catalog.roles] == [
        default_role.project_id,
        other_role.project_id,
    ]


def test_retry_interval_survives_role_application_save_and_reload(tmp_path):
    projects, conversations, roles, _settings = _build_services(tmp_path)
    role = roles.ensure_default_role()
    response_path = tmp_path / "roles" / role.project_id / "response.json"
    response = loads(response_path.read_text(encoding="utf-8"))
    assert response["upstream_retry_interval_seconds"] == 5
    response["upstream_retry_interval_seconds"] = 17
    response_path.write_text(dumps(response), encoding="utf-8")
    seed = roles.build_new_session_seed(role.project_id)
    assert seed.settings["upstream_retry_interval_seconds"] == 17
    project = projects.create_project(name="重试配置")
    session = conversations.create_session(project.project_id, settings=seed.settings)
    changed = conversations.update_session(
        project.project_id, session.session_id,
        settings={"upstream_retry_interval_seconds": 0}, should_update_settings=True,
    )
    saved_role, _ = roles.save_session_as_role(
        project.project_id, session.session_id, name="立即重试", category_id=role.category_id,
    )
    saved_path = tmp_path / "roles" / saved_role.project_id / "response.json"
    assert loads(saved_path.read_text(encoding="utf-8"))["upstream_retry_interval_seconds"] == 0
    assert ProjectConversationSessionResponse.from_domain(changed).settings.upstream_retry_interval_seconds == 0
    roles.apply_role(project.project_id, session.session_id, role.project_id)
    reloaded = conversations.get_session(project.project_id, session.session_id)
    assert reloaded.settings.upstream_retry_interval_seconds == 17
    # A role created before this field existed has the same displayed/applied default.
    response.pop("upstream_retry_interval_seconds")
    response_path.write_text(dumps(response), encoding="utf-8")
    assert roles.apply_role(project.project_id, session.session_id, role.project_id).settings.upstream_retry_interval_seconds == 5
