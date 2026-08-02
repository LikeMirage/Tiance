from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
import json
import logging
from pathlib import Path
from threading import RLock
from uuid import NAMESPACE_URL, uuid4, uuid5

from app.core.atomic_replace import atomic_replace_path
from app.core.config import get_settings
from app.domain.project import Project, ProjectCategory, ProjectKind
from app.repositories.project import FileProjectCatalog, get_project_repository
from app.repositories.themes import ThemeSettingsRepository, get_theme_settings_repository
from app.schemas.themes import ThemeDefinition
from app.services.project.projects import (
    DEFAULT_THEME_PROJECT_CATEGORY_ID,
    DEFAULT_THEME_PROJECT_CATEGORY_NAME,
)
from app.services.themes.theme_catalog import (
    DEFAULT_THEME_ID,
    THEME_MANIFEST_FILE,
    ThemeCatalogError,
    load_theme_package,
)

logger = logging.getLogger(__name__)

_RECOVERY_THEME_IDS = (DEFAULT_THEME_ID, "light")


@dataclass(frozen=True, slots=True)
class ThemeWorkspaceSyncResult:
    restored_theme_ids: tuple[str, ...]
    added_project_ids: tuple[str, ...]
    removed_project_ids: tuple[str, ...]
    invalid_directories: tuple[str, ...]
    active_theme_id: str
    recovered_catalog_path: str | None


class ThemeWorkspaceReconciliationService:
    """Keep the theme folders, project catalog, and active selection consistent."""

    def __init__(
        self,
        *,
        themes_root: Path,
        recovery_root: Path,
        catalog: FileProjectCatalog,
        settings_repository: ThemeSettingsRepository,
    ) -> None:
        self._themes_root = themes_root.resolve()
        self._recovery_root = recovery_root.resolve()
        self._catalog = catalog
        self._settings_repository = settings_repository
        self._sync_lock = RLock()

    def synchronize(self) -> ThemeWorkspaceSyncResult:
        with self._sync_lock:
            self._themes_root.mkdir(parents=True, exist_ok=True)
            restored_theme_ids = self._restore_recovery_themes()
            valid_by_root, invalid_directories = self._scan_valid_themes()
            recovered_catalog_path = self._recover_invalid_catalog()
            default_category = self._default_category_for_new_themes()

            existing_projects = self._catalog.list_projects()
            removed_project_ids: list[str] = []
            for project in existing_projects:
                root = Path(project.root_path).resolve()
                if not root.is_dir():
                    self._catalog.delete_project(project.project_id)
                    removed_project_ids.append(project.project_id)

            current_projects = self._catalog.list_projects()
            existing_by_root = {
                Path(project.root_path).resolve(): project
                for project in current_projects
            }
            existing_ids = {project.project_id for project in current_projects}
            added_project_ids: list[str] = []
            for root, theme in sorted(
                valid_by_root.items(),
                key=lambda item: item[0].name,
            ):
                if root in existing_by_root:
                    continue
                project_id = str(uuid5(NAMESPACE_URL, f"tiance:theme:{theme.id}"))
                if project_id in existing_ids:
                    project_id = str(uuid4())
                now = _utc_now()
                project = Project(
                    project_id=project_id,
                    name=theme.name,
                    root_path=str(root),
                    category_id=default_category.category_id,
                    project_kind=ProjectKind.THEME,
                    is_default=False,
                    sort_order=self._catalog.next_project_sort_order(),
                    created_at=now,
                    updated_at=now,
                )
                self._catalog.save_project(project)
                existing_ids.add(project_id)
                added_project_ids.append(project_id)

            valid_theme_ids = {theme.id for theme in valid_by_root.values()}
            active_theme_id = self._settings_repository.get_active_theme_id()
            if active_theme_id not in valid_theme_ids:
                active_theme_id = DEFAULT_THEME_ID
                self._settings_repository.save_active_theme_id(active_theme_id)

            result = ThemeWorkspaceSyncResult(
                restored_theme_ids=tuple(restored_theme_ids),
                added_project_ids=tuple(added_project_ids),
                removed_project_ids=tuple(removed_project_ids),
                invalid_directories=tuple(invalid_directories),
                active_theme_id=active_theme_id,
                recovered_catalog_path=(
                    None if recovered_catalog_path is None else str(recovered_catalog_path)
                ),
            )
            if any((
                result.restored_theme_ids,
                result.added_project_ids,
                result.removed_project_ids,
                result.invalid_directories,
                result.recovered_catalog_path,
            )):
                logger.info("Theme workspace synchronized: %s", result)
            return result

    @property
    def themes_root(self) -> Path:
        return self._themes_root

    def _restore_recovery_themes(self) -> list[str]:
        restored: list[str] = []
        for theme_id in _RECOVERY_THEME_IDS:
            source = self._recovery_root / f"{theme_id}.json"
            source_theme = _load_recovery_file(source)
            if source_theme.id != theme_id:
                raise RuntimeError(f"内置恢复主题 ID 不匹配：{theme_id}")

            target_root = self._themes_root / theme_id
            target_file = target_root / THEME_MANIFEST_FILE
            try:
                current_theme = load_theme_package(target_root)
            except ThemeCatalogError:
                current_theme = None
            if current_theme is not None and current_theme.id == theme_id:
                continue

            target_root.mkdir(parents=True, exist_ok=True)
            temporary_file = target_file.with_name(
                f".{target_file.name}.{uuid4().hex}.tmp"
            )
            try:
                temporary_file.write_text(
                    source.read_text(encoding="utf-8"),
                    encoding="utf-8",
                )
                atomic_replace_path(temporary_file, target_file)
            finally:
                with suppress(OSError):
                    temporary_file.unlink(missing_ok=True)
            restored.append(theme_id)
        return restored

    def _scan_valid_themes(
        self,
    ) -> tuple[dict[Path, ThemeDefinition], list[str]]:
        valid_by_root: dict[Path, ThemeDefinition] = {}
        invalid_directories: list[str] = []
        roots_by_theme_id: dict[str, list[Path]] = {}
        themes_by_root: dict[Path, ThemeDefinition] = {}
        for child in sorted(
            self._themes_root.iterdir(),
            key=lambda item: item.name.casefold(),
        ):
            if child.name.startswith(".") or not child.is_dir() or child.is_symlink():
                continue
            try:
                theme = load_theme_package(child)
            except ThemeCatalogError:
                invalid_directories.append(child.name)
                continue
            if child.name != theme.id:
                invalid_directories.append(child.name)
                continue
            root = child.resolve()
            themes_by_root[root] = theme
            roots_by_theme_id.setdefault(theme.id, []).append(root)

        duplicate_roots = {
            root
            for roots in roots_by_theme_id.values()
            if len(roots) > 1
            for root in roots
        }
        for root, theme in themes_by_root.items():
            if root in duplicate_roots:
                invalid_directories.append(root.name)
                continue
            valid_by_root[root] = theme
        return valid_by_root, sorted(set(invalid_directories))

    def _recover_invalid_catalog(self) -> Path | None:
        if not self._catalog.exists():
            return None
        try:
            self._catalog.list_project_categories()
            self._catalog.list_projects()
            return None
        except (OSError, UnicodeError, ValueError):
            trash_root = self._themes_root / ".trash"
            trash_root.mkdir(parents=True, exist_ok=True)
            backup_path = trash_root / f"catalog-invalid-{uuid4().hex}.json"
            self._catalog.catalog_path.replace(backup_path)
            logger.warning(
                "Invalid theme catalog moved to %s before rebuilding.",
                backup_path,
                exc_info=True,
            )
            return backup_path

    def _default_category_for_new_themes(self) -> ProjectCategory:
        categories = self._catalog.list_project_categories()
        default = next((category for category in categories if category.is_default), None)
        if default is not None:
            return default
        if categories:
            return categories[0]
        now = _utc_now()
        return self._catalog.save_project_category(ProjectCategory(
            category_id=DEFAULT_THEME_PROJECT_CATEGORY_ID,
            name=DEFAULT_THEME_PROJECT_CATEGORY_NAME,
            category_kind=ProjectKind.THEME,
            is_default=True,
            sort_order=0,
            created_at=now,
            updated_at=now,
        ))


def _load_recovery_file(theme_file: Path) -> ThemeDefinition:
    if not theme_file.is_file():
        raise RuntimeError(f"缺少内置恢复主题：{theme_file.name}")
    try:
        payload = json.loads(theme_file.read_text(encoding="utf-8"))
        return ThemeDefinition.model_validate(payload)
    except Exception as exc:
        raise RuntimeError(f"内置恢复主题无效：{theme_file.name}") from exc


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


@lru_cache
def get_theme_workspace_reconciliation_service() -> ThemeWorkspaceReconciliationService:
    settings = get_settings()
    catalog = get_project_repository().get_file_catalog(ProjectKind.THEME)
    if catalog is None:
        raise RuntimeError("主题集未配置文件目录索引。")
    recovery_root = Path(__file__).resolve().parents[2] / "resources" / "themes"
    return ThemeWorkspaceReconciliationService(
        themes_root=settings.themes_data_path,
        recovery_root=recovery_root,
        catalog=catalog,
        settings_repository=get_theme_settings_repository(),
    )
