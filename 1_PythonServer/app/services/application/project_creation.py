from functools import lru_cache
from json import dumps
from pathlib import Path
from shutil import copytree

from app.domain.project import Project, ProjectKind
from app.domain.project.project_conversation import ProjectConversationSession
from app.services.application.role_configuration import (
    RoleConfigurationApplicationService,
)
from app.services.llm.functional_model_settings import (
    LlmFunctionalModelSettingsService,
    get_llm_functional_model_settings_service,
)
from app.services.project.project_conversations import (
    ProjectConversationService,
    get_project_conversation_service,
)
from app.services.project.project_files import (
    ProjectFileService,
    get_project_file_service,
)
from app.services.project.projects import (
    ProjectService,
    get_project_service,
)
from app.services.themes import get_active_theme_id, get_theme
from app.services.themes.theme_catalog import (
    THEME_MANIFEST_FILE,
    ThemeCatalogError,
    load_theme_package,
)
from app.schemas.themes import theme_package_from_definition


class ProjectCreationApplicationService:
    def __init__(
        self,
        project_service: ProjectService,
        conversation_service: ProjectConversationService,
        project_file_service: ProjectFileService,
        functional_model_settings_service: LlmFunctionalModelSettingsService,
    ) -> None:
        self._project_service = project_service
        self._conversation_service = conversation_service
        self._role_configuration_service = RoleConfigurationApplicationService(
            project_service,
            conversation_service,
            project_file_service,
            functional_model_settings_service,
        )

    def create_project(
        self,
        *,
        name: str | None,
        root_path: str | None = None,
        category_id: str | None = None,
        project_kind: ProjectKind = ProjectKind.PROJECT,
    ) -> Project:
        if project_kind is ProjectKind.ROLE:
            self._role_configuration_service.ensure_default_role()
        project = self._project_service.create_project(
            name=name,
            root_path=root_path,
            category_id=category_id,
            project_kind=project_kind,
        )
        try:
            if project_kind is ProjectKind.THEME:
                self._initialize_theme_project(project)
            if project_kind is ProjectKind.ROLE:
                self._role_configuration_service.initialize_role_project(project.project_id)
            else:
                self.ensure_initial_conversation(project.project_id)
        except Exception:
            self._project_service.delete_project(project.project_id)
            raise
        return project

    def create_role_project(
        self,
        *,
        name: str | None,
        category_id: str | None = None,
    ) -> Project:
        return self.create_project(
            name=name,
            category_id=category_id,
            project_kind=ProjectKind.ROLE,
        )

    def ensure_initial_conversation(
        self,
        project_id: str,
    ) -> ProjectConversationSession | None:
        if self._conversation_service.list_sessions(project_id):
            return None

        seed = self._role_configuration_service.build_new_session_seed()
        session = self._conversation_service.create_session(
            project_id,
            provider_id=seed.provider_id,
            model_id=seed.model_id,
            reasoning_mode=seed.reasoning_mode,
            manual_title=False,
            settings=seed.settings,
            role_project_id=seed.role_project_id,
        )
        return session

    def _initialize_theme_project(self, project: Project) -> None:
        active_theme = get_theme(get_active_theme_id())
        source_root = self._find_theme_root(active_theme.id)
        target_root = Path(project.root_path)
        if source_root is not None:
            source_assets = source_root / "assets"
            if source_assets.is_dir():
                copytree(source_assets, target_root / "assets", dirs_exist_ok=True)
        theme = active_theme.model_copy(
            update={"id": project.project_id, "name": project.name},
        )
        payload = theme_package_from_definition(
            theme,
            registration_name=project.name,
        ).model_dump(mode="json", by_alias=True)
        (target_root / THEME_MANIFEST_FILE).write_text(
            dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def _find_theme_root(self, theme_id: str) -> Path | None:
        for project in self._project_service.list_projects():
            if project.project_kind is not ProjectKind.THEME:
                continue
            root = Path(project.root_path)
            try:
                if load_theme_package(root).id == theme_id:
                    return root
            except ThemeCatalogError:
                continue
        return None


@lru_cache
def get_project_creation_application_service() -> ProjectCreationApplicationService:
    return ProjectCreationApplicationService(
        get_project_service(),
        get_project_conversation_service(),
        get_project_file_service(),
        get_llm_functional_model_settings_service(),
    )
