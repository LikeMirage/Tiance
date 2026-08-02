from json import dumps

from app.infra.database import ensure_database_schema
from app.infra.file_workspace import FileWorkspaceStorage
from app.infra.projects import ProjectStorage
from app.repositories.llm.functional_model_settings_repository import (
    LlmFunctionalModelSettingsRepository,
)
from app.repositories.project import ProjectRepository
from app.repositories.project.conversation_repository import (
    ProjectConversationRepository,
)
from app.schemas.project.project_conversations import (
    ProjectConversationSessionResponse,
)
from app.services.application.role_configuration import (
    DEFAULT_ROLE_NAME,
    RoleConfigurationApplicationService,
)
from app.services.document_conversion import MarkdownDocxService
from app.services.llm.functional_model_settings import (
    LlmFunctionalModelSettingsService,
)
from app.domain.llm.functional_model_defaults import (
    DEFAULT_CONVERSATION_ROLE_SETTINGS_VERSION,
)
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
    functional_settings_service = LlmFunctionalModelSettingsService(
        LlmFunctionalModelSettingsRepository(database_path),
    )
    role_service = RoleConfigurationApplicationService(
        project_service,
        conversation_service,
        ProjectFileService(
            repository,
            FileWorkspaceStorage(),
            MarkdownDocxService(),
        ),
        functional_settings_service,
    )
    return (
        project_service,
        conversation_service,
        role_service,
        functional_settings_service,
    )


def test_default_role_is_created_once(tmp_path):
    project_service, _conversation_service, role_service, functional_settings = (
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
    default_settings = functional_settings.get_profile_settings("defaultConversation")
    assert default_settings is not None
    assert default_settings.settings == {"roleProjectId": first.project_id}


def test_role_application_ignores_invalid_fields_and_tracks_custom_state(tmp_path):
    project_service, conversation_service, role_service, _functional_settings = (
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

    applied = role_service.apply_role(
        project.project_id,
        source.session_id,
        role.project_id,
    )

    assert applied.settings.temperature == 1.2
    assert applied.settings.top_p == 0.7
    assert applied.settings.system_prompt == "保留内容"
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
    project_service, _conversation_service, role_service, functional_settings = (
        _build_services(tmp_path)
    )
    default_role = role_service.ensure_default_role()
    selected_role = project_service.create_role_project(
        name="角色创建者",
        category_id=default_role.category_id,
    )
    role_service.initialize_role_project(selected_role.project_id)
    functional_settings.save_profile_settings(
        profile_key="defaultConversation",
        settings={"roleProjectId": selected_role.project_id},
        version=DEFAULT_CONVERSATION_ROLE_SETTINGS_VERSION,
    )

    seed = role_service.build_new_session_seed()

    assert seed.role_project_id == selected_role.project_id


def test_missing_configured_role_falls_back_to_default_role(tmp_path):
    _project_service, _conversation_service, role_service, functional_settings = (
        _build_services(tmp_path)
    )
    default_role = role_service.ensure_default_role()
    functional_settings.save_profile_settings(
        profile_key="defaultConversation",
        settings={"roleProjectId": "missing-role"},
        version=DEFAULT_CONVERSATION_ROLE_SETTINGS_VERSION,
    )

    seed = role_service.build_new_session_seed()
    repaired = functional_settings.get_profile_settings("defaultConversation")

    assert seed.role_project_id == default_role.project_id
    assert repaired is not None
    assert repaired.settings == {"roleProjectId": default_role.project_id}


def test_role_catalog_follows_project_drag_order(tmp_path):
    project_service, _conversation_service, role_service, _functional_settings = (
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
