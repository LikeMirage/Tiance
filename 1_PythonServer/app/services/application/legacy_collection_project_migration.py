from __future__ import annotations

from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Callable
from uuid import NAMESPACE_URL, uuid5

from app.core.config import get_settings
from app.core.errors import BadRequestError
from app.domain.project import Project, ProjectKind
from app.infra.projects import ProjectStorage, get_project_storage
from app.repositories.project import ProjectRepository, get_project_repository
from app.services.project import ProjectService, get_project_service
from app.services.themes import ThemeCatalogError
from app.services.themes.theme_catalog import load_theme_package


_COLLECTION_MIGRATION_KEY = "collections.native_projects_imported"


class LegacyCollectionProjectMigrationService:
    """Import registered theme packages into the native project catalog once."""

    def __init__(
        self,
        *,
        project_service: ProjectService,
        project_repository: ProjectRepository,
        project_storage: ProjectStorage,
        themes_root: Path,
        conversation_initializer: Callable[[str], object] | None = None,
    ) -> None:
        self._project_service = project_service
        self._project_repository = project_repository
        self._project_storage = project_storage
        self._themes_root = themes_root
        self._conversation_initializer = conversation_initializer

    def migrate_once(self) -> None:
        if self._project_repository.get_metadata_value(_COLLECTION_MIGRATION_KEY) == "1":
            return
        migrated_project_ids = self._import_themes()
        if self._conversation_initializer is not None:
            for project_id in sorted(migrated_project_ids):
                self._conversation_initializer(project_id)
        self._project_repository.set_metadata_value(
            key=_COLLECTION_MIGRATION_KEY,
            value="1",
            updated_at=_utc_now(),
        )

    def _import_themes(self) -> set[str]:
        imported_project_ids: set[str] = set()
        if not self._themes_root.is_dir():
            return imported_project_ids
        for theme_dir in sorted(self._themes_root.iterdir(), key=lambda item: item.name.lower()):
            if not theme_dir.is_dir():
                continue
            try:
                theme = load_theme_package(theme_dir)
                project_id = self._import_theme_project(
                    theme_id=theme.id,
                    name=theme.name,
                    root_path=theme_dir,
                )
                if project_id is not None:
                    imported_project_ids.add(project_id)
            except (ThemeCatalogError, BadRequestError):
                continue
        return imported_project_ids

    def _import_theme_project(
        self,
        *,
        theme_id: str,
        name: str,
        root_path: Path,
    ) -> str | None:
        managed_root = self._project_storage.resolve_managed_project_root(
            str(root_path),
            project_kind=ProjectKind.THEME,
        )
        if self._project_repository.get_project_by_root_path(str(managed_root)) is not None:
            return None
        category = self._project_service.ensure_default_theme_project_category()
        now = _utc_now()
        project_id = str(uuid5(NAMESPACE_URL, f"tiance:theme:{theme_id}"))
        self._project_repository.save_project(
            Project(
                project_id=project_id,
                name=name,
                root_path=str(managed_root),
                category_id=category.category_id,
                project_kind=ProjectKind.THEME,
                is_default=False,
                sort_order=self._project_repository.next_sort_order(),
                created_at=now,
                updated_at=now,
            )
        )
        return project_id


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


@lru_cache
def get_legacy_collection_project_migration_service() -> LegacyCollectionProjectMigrationService:
    from app.services.application.project_creation import (
        get_project_creation_application_service,
    )

    settings = get_settings()
    return LegacyCollectionProjectMigrationService(
        project_service=get_project_service(),
        project_repository=get_project_repository(),
        project_storage=get_project_storage(),
        themes_root=settings.themes_data_path,
        conversation_initializer=(
            get_project_creation_application_service().ensure_initial_conversation
        ),
    )
