from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
import logging
from pathlib import Path
from threading import RLock
from uuid import uuid4

from app.core.config import get_settings
from app.domain.project import Project, ProjectCategory, ProjectKind
from app.infra.projects import (
    ProjectIdentity,
    read_project_identity,
    write_project_identity,
)
from app.repositories.project import FileProjectCatalog, get_project_repository
from app.services.project.projects import (
    DEFAULT_PROJECT_CATEGORY_ID,
    DEFAULT_PROJECT_CATEGORY_NAME,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ProjectWorkspaceSyncResult:
    added_project_ids: tuple[str, ...]
    removed_project_ids: tuple[str, ...]
    relocated_project_ids: tuple[str, ...]
    updated_identity_project_ids: tuple[str, ...]
    invalid_directories: tuple[str, ...]


class ProjectWorkspaceReconciliationService:
    """Keep ordinary project folders, stable identities, and catalog.json aligned."""

    def __init__(self, *, projects_root: Path, catalog: FileProjectCatalog) -> None:
        self._projects_root = projects_root.resolve()
        self._catalog = catalog
        self._sync_lock = RLock()

    @property
    def projects_root(self) -> Path:
        return self._projects_root

    def synchronize(self) -> ProjectWorkspaceSyncResult:
        with self._sync_lock:
            self._projects_root.mkdir(parents=True, exist_ok=True)
            default_category = self._default_category_for_new_projects()
            roots, identities, invalid_directories = self._scan_project_roots()
            duplicate_identity_roots = _duplicate_identity_roots(identities)
            invalid_directories.update(root.name for root in duplicate_identity_roots)

            existing_projects = self._catalog.list_projects()
            existing_by_root = {
                Path(project.root_path).resolve(): project
                for project in existing_projects
            }
            claimed_roots = {
                root
                for root in existing_by_root
                if root.is_dir()
            }
            relocated_project_ids: list[str] = []
            removed_project_ids: list[str] = []

            for project in existing_projects:
                indexed_root = Path(project.root_path).resolve()
                if not self._is_managed_root(indexed_root) or indexed_root.is_dir():
                    continue
                candidates = [
                    root
                    for root, identity in identities.items()
                    if root not in duplicate_identity_roots
                    and root not in claimed_roots
                    and identity is not None
                    and identity.project_id == project.project_id
                ]
                if len(candidates) == 1:
                    relocated_root = candidates[0]
                    self._catalog.save_project(_replace_project_root(
                        project,
                        root_path=relocated_root,
                    ))
                    claimed_roots.add(relocated_root)
                    relocated_project_ids.append(project.project_id)
                    continue
                self._catalog.delete_project(project.project_id)
                removed_project_ids.append(project.project_id)

            current_projects = self._catalog.list_projects()
            existing_ids = {project.project_id for project in current_projects}
            claimed_roots = {
                Path(project.root_path).resolve()
                for project in current_projects
                if Path(project.root_path).resolve().is_dir()
            }
            updated_identity_project_ids: list[str] = []
            for project in current_projects:
                root = Path(project.root_path).resolve()
                if (
                    not root.is_dir()
                    or root.is_symlink()
                    or root in duplicate_identity_roots
                ):
                    continue
                try:
                    current_identity = read_project_identity(root)
                except ValueError:
                    invalid_directories.add(root.name)
                    continue
                expected_identity = ProjectIdentity(
                    project_id=project.project_id,
                    name=project.name,
                )
                if current_identity != expected_identity:
                    write_project_identity(root, expected_identity)
                    updated_identity_project_ids.append(project.project_id)

            added_project_ids: list[str] = []
            for root in roots:
                if root in claimed_roots or root in duplicate_identity_roots:
                    continue
                identity = identities[root]
                project_id = (
                    identity.project_id
                    if identity is not None and identity.project_id not in existing_ids
                    else str(uuid4())
                )
                name = identity.name if identity is not None else root.name
                now = _utc_now()
                project = Project(
                    project_id=project_id,
                    name=name,
                    root_path=str(root),
                    category_id=default_category.category_id,
                    project_kind=ProjectKind.PROJECT,
                    is_default=False,
                    sort_order=self._catalog.next_project_sort_order(),
                    created_at=now,
                    updated_at=now,
                )
                self._catalog.save_project(project)
                write_project_identity(
                    root,
                    ProjectIdentity(project_id=project_id, name=name),
                )
                existing_ids.add(project_id)
                claimed_roots.add(root)
                added_project_ids.append(project_id)
                if identity is None or identity.project_id != project_id:
                    updated_identity_project_ids.append(project_id)

            result = ProjectWorkspaceSyncResult(
                added_project_ids=tuple(added_project_ids),
                removed_project_ids=tuple(removed_project_ids),
                relocated_project_ids=tuple(relocated_project_ids),
                updated_identity_project_ids=tuple(updated_identity_project_ids),
                invalid_directories=tuple(sorted(invalid_directories)),
            )
            if any((
                result.added_project_ids,
                result.removed_project_ids,
                result.relocated_project_ids,
                result.updated_identity_project_ids,
                result.invalid_directories,
            )):
                logger.info("Project workspace synchronized: %s", result)
            return result

    def _scan_project_roots(
        self,
    ) -> tuple[list[Path], dict[Path, ProjectIdentity | None], set[str]]:
        roots: list[Path] = []
        identities: dict[Path, ProjectIdentity | None] = {}
        invalid_directories: set[str] = set()
        for child in sorted(
            self._projects_root.iterdir(),
            key=lambda item: item.name.casefold(),
        ):
            if child.name.startswith(".") or not child.is_dir() or child.is_symlink():
                continue
            root = child.resolve()
            try:
                identity = read_project_identity(root)
            except ValueError:
                invalid_directories.add(child.name)
                continue
            roots.append(root)
            identities[root] = identity
        return roots, identities, invalid_directories

    def _default_category_for_new_projects(self) -> ProjectCategory:
        categories = self._catalog.list_project_categories()
        default = next((category for category in categories if category.is_default), None)
        if default is not None:
            return default
        if categories:
            return categories[0]
        now = _utc_now()
        return self._catalog.save_project_category(ProjectCategory(
            category_id=DEFAULT_PROJECT_CATEGORY_ID,
            name=DEFAULT_PROJECT_CATEGORY_NAME,
            category_kind=ProjectKind.PROJECT,
            is_default=True,
            sort_order=0,
            created_at=now,
            updated_at=now,
        ))

    def _is_managed_root(self, root: Path) -> bool:
        return root.parent == self._projects_root


def _duplicate_identity_roots(
    identities: dict[Path, ProjectIdentity | None],
) -> set[Path]:
    roots_by_id: dict[str, list[Path]] = {}
    for root, identity in identities.items():
        if identity is not None:
            roots_by_id.setdefault(identity.project_id, []).append(root)
    return {
        root
        for roots in roots_by_id.values()
        if len(roots) > 1
        for root in roots
    }


def _replace_project_root(project: Project, *, root_path: Path) -> Project:
    return Project(
        project_id=project.project_id,
        name=project.name,
        root_path=str(root_path),
        category_id=project.category_id,
        project_kind=project.project_kind,
        is_default=project.is_default,
        sort_order=project.sort_order,
        created_at=project.created_at,
        updated_at=_utc_now(),
    )


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


@lru_cache
def get_project_workspace_reconciliation_service() -> ProjectWorkspaceReconciliationService:
    settings = get_settings()
    catalog = get_project_repository().get_file_catalog(ProjectKind.PROJECT)
    if catalog is None:
        raise RuntimeError("普通项目集未配置文件目录索引。")
    return ProjectWorkspaceReconciliationService(
        projects_root=settings.projects_data_path,
        catalog=catalog,
    )
