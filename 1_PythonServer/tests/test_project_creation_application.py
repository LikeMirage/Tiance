from json import loads
from pathlib import Path

from app.infra.database import ensure_database_schema
from app.infra.file_workspace import FileWorkspaceStorage
from app.infra.projects import ProjectStorage
from app.domain.project import ProjectKind
from app.repositories.llm.functional_model_settings_repository import (
    LlmFunctionalModelSettingsRepository,
)
from app.repositories.project import ProjectRepository
from app.repositories.project.file_project_catalog import FileProjectCatalog
from app.repositories.project.conversation_repository import ProjectConversationRepository
from app.services.application.project_creation import ProjectCreationApplicationService
from app.services.application.role_configuration import (
    RoleConfigurationApplicationService,
)
from app.services.document_conversion import MarkdownDocxService
from app.services.llm.functional_model_settings import LlmFunctionalModelSettingsService
from app.services.project.project_files import ProjectFileService
from app.services.project.project_conversations import ProjectConversationService
from app.services.project.projects import ProjectService


def test_theme_and_tool_creation_use_native_project_workspace(tmp_path):
    database_path = tmp_path / "tiance.db"
    ensure_database_schema(database_path)
    repository = ProjectRepository(
        database_path,
        file_catalogs=(
            FileProjectCatalog(tmp_path / "tools", project_kind=ProjectKind.TOOL),
        ),
    )
    project_service = ProjectService(
        repository,
        ProjectStorage(
            tmp_path / "projects",
            roles_root=tmp_path / "roles",
            themes_root=tmp_path / "themes",
            tools_root=tmp_path / "tools",
        ),
    )
    conversation_service = ProjectConversationService(
        ProjectConversationRepository(repository),
    )
    settings_service = LlmFunctionalModelSettingsService(
        LlmFunctionalModelSettingsRepository(database_path),
    )
    creation_service = ProjectCreationApplicationService(
        project_service,
        conversation_service,
        ProjectFileService(
            repository,
            FileWorkspaceStorage(),
            MarkdownDocxService(),
        ),
        settings_service,
    )

    theme = creation_service.create_project(name=None, project_kind=ProjectKind.THEME)
    tool = creation_service.create_project(name=None, project_kind=ProjectKind.TOOL)

    assert Path(theme.root_path).parent == tmp_path / "themes"
    assert Path(tool.root_path).parent == tmp_path / "tools"
    assert {path.name for path in Path(theme.root_path).iterdir()} == {
        ".Tiance",
        "theme.json",
    }
    theme_manifest = loads((Path(theme.root_path) / "theme.json").read_text(encoding="utf-8"))
    assert theme_manifest["id"] == theme.project_id
    assert theme_manifest["registrationName"] == theme.name
    assert {path.name for path in Path(tool.root_path).iterdir()} == {".Tiance"}
    assert len(conversation_service.list_sessions(theme.project_id)) == 1
    assert len(conversation_service.list_sessions(tool.project_id)) == 1
    assert repository.list_database_projects(project_kind=ProjectKind.TOOL) == ()


def test_project_creation_creates_initial_conversation_with_default_role(tmp_path):
    database_path = tmp_path / "tiance.db"
    ensure_database_schema(database_path)
    project_repository = ProjectRepository(database_path)
    project_service = ProjectService(
        project_repository,
        ProjectStorage(tmp_path / "managed-projects", tmp_path / "roles"),
    )
    conversation_service = ProjectConversationService(
        ProjectConversationRepository(project_repository),
    )
    settings_service = LlmFunctionalModelSettingsService(
        LlmFunctionalModelSettingsRepository(database_path),
    )
    project_file_service = ProjectFileService(
        project_repository,
        FileWorkspaceStorage(),
        MarkdownDocxService(),
    )
    creation_service = ProjectCreationApplicationService(
        project_service,
        conversation_service,
        project_file_service,
        settings_service,
    )
    role_service = RoleConfigurationApplicationService(
        project_service,
        conversation_service,
        project_file_service,
        settings_service,
    )
    default_role = role_service.ensure_default_role()
    default_role_session = conversation_service.list_sessions(
        default_role.project_id,
    )[0]
    configured_role_session = conversation_service.update_session(
        default_role.project_id,
        default_role_session.session_id,
        provider_id="deepseek",
        should_update_provider=True,
        model_id="deepseek-v4-flash",
        should_update_model=True,
        reasoning_mode="high",
        should_update_reasoning=True,
        settings={
            "max_output_tokens": 45678,
            "temperature": 1.3,
            "top_p": 0.8,
            "streaming_enabled": False,
            "system_prompt": "默认主会话提示词",
        },
        should_update_settings=True,
    )
    role_service.write_role_configuration(
        default_role.project_id,
        configured_role_session,
    )

    project = creation_service.create_project(name="新项目")

    sessions = conversation_service.list_sessions(project.project_id)
    active_session_id, states = conversation_service.get_state(project.project_id)
    assert len(sessions) == 1
    session = sessions[0]
    assert session.provider_id == "deepseek"
    assert session.model_id == "deepseek-v4-flash"
    assert session.reasoning_mode == "high"
    assert session.settings.max_output_tokens == 45678
    assert session.settings.temperature == 1.3
    assert session.settings.top_p == 0.8
    assert session.settings.streaming_enabled is False
    assert session.settings.system_prompt == "默认主会话提示词"
    assert active_session_id == session.session_id
    assert session.session_id in states
    workspace_readme = Path(project.root_path) / ".Tiance" / "README.md"
    assert workspace_readme.is_file()
    assert "tiance.db" in workspace_readme.read_text(encoding="utf-8")
    assert (Path(project.root_path) / ".Tiance" / "tiance.db").is_file()


def test_project_creation_does_not_duplicate_initial_conversation(tmp_path):
    database_path = tmp_path / "tiance.db"
    ensure_database_schema(database_path)
    project_repository = ProjectRepository(database_path)
    project_service = ProjectService(
        project_repository,
        ProjectStorage(tmp_path / "managed-projects", tmp_path / "roles"),
    )
    conversation_service = ProjectConversationService(
        ProjectConversationRepository(project_repository),
    )
    settings_service = LlmFunctionalModelSettingsService(
        LlmFunctionalModelSettingsRepository(database_path),
    )
    project_file_service = ProjectFileService(
        project_repository,
        FileWorkspaceStorage(),
        MarkdownDocxService(),
    )
    creation_service = ProjectCreationApplicationService(
        project_service,
        conversation_service,
        project_file_service,
        settings_service,
    )
    project = project_service.create_project(name="已有会话")
    conversation_service.create_session(
        project.project_id,
        title="手动会话",
        provider_id=None,
        model_id=None,
        reasoning_mode=None,
    )

    creation_service.ensure_initial_conversation(project.project_id)

    assert len(conversation_service.list_sessions(project.project_id)) == 1


def test_role_creation_initializes_editable_configuration_files(tmp_path):
    database_path = tmp_path / "tiance.db"
    roles_root = tmp_path / "roles"
    ensure_database_schema(database_path)
    project_repository = ProjectRepository(database_path)
    project_service = ProjectService(
        project_repository,
        ProjectStorage(tmp_path / "managed-projects", roles_root),
    )
    conversation_service = ProjectConversationService(
        ProjectConversationRepository(project_repository),
    )
    settings_service = LlmFunctionalModelSettingsService(
        LlmFunctionalModelSettingsRepository(database_path),
    )
    project_file_service = ProjectFileService(
        project_repository,
        FileWorkspaceStorage(),
        MarkdownDocxService(),
    )
    creation_service = ProjectCreationApplicationService(
        project_service,
        conversation_service,
        project_file_service,
        settings_service,
    )

    role = creation_service.create_role_project(name="测试角色")
    role_root = Path(role.root_path)

    assert {path.name for path in role_root.glob("*.json")} == {
        "context.json",
        "generation.json",
        "memory.json",
        "model.json",
        "profile.json",
        "prompt.json",
        "response.json",
        "tools.json",
    }
    assert loads((role_root / "profile.json").read_text(encoding="utf-8")) == {
        "description": "",
    }
    assert loads((role_root / "tools.json").read_text(encoding="utf-8")) == {
        "tools_enabled": True,
        "enabled_tool_names": None,
        "max_tool_calls": 99999,
    }
