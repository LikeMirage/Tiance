import json
import re
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4

from app.core.atomic_replace import atomic_replace_path
from app.core.config import get_settings
from app.domain.project import Project, ProjectKind
from app.repositories.themes import get_theme_settings_repository
from app.schemas.themes import (
    ThemeDefinition,
    ThemePackageDefinition,
    ThemeSummary,
    theme_definition_from_package,
    theme_package_from_definition,
)
from app.services.project import get_project_service

DEFAULT_THEME_ID = "dark-gold"
THEME_SETTINGS_FILE = "theme-settings.json"
THEME_MANIFEST_FILE = "theme.json"
_THEME_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


class ThemeCatalogError(RuntimeError):
    pass


class ThemeNotFoundError(ThemeCatalogError):
    pass


class ThemeSaveRejectedError(ThemeCatalogError):
    pass


class ThemeAssetNotFoundError(ThemeCatalogError):
    pass


@dataclass(frozen=True)
class _ThemeEntry:
    project: Project
    stamp: tuple | None
    theme: ThemePackageDefinition | None
    error: str | None = None


@dataclass(frozen=True)
class _ThemeIndex:
    owner: object
    catalog_stamp: tuple
    projects: dict[str, _ThemeEntry]
    theme_ids: dict[str, list[_ThemeEntry]]


_index_lock = RLock()
_theme_index: _ThemeIndex | None = None


def invalidate_theme_catalog() -> None:
    global _theme_index
    with _index_lock:
        _theme_index = None


def _file_stamp(path: Path) -> tuple | None:
    try:
        stat = path.stat()
        return stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size, stat.st_ino
    except OSError:
        return None


def _catalog_stamp() -> tuple:
    root = get_settings().themes_data_path
    return str(root), _file_stamp(root / "catalog.json"), _file_stamp(root)


def _build_index(owner, stamp: tuple) -> _ThemeIndex:
    projects: dict[str, _ThemeEntry] = {}
    theme_ids: dict[str, list[_ThemeEntry]] = {}
    for project in owner.list_projects():
        if project.project_kind is not ProjectKind.THEME:
            continue
        path = Path(project.root_path) / THEME_MANIFEST_FILE
        file_stamp = _file_stamp(path)
        try:
            theme = _load_theme_file(path)
            entry = _ThemeEntry(project, file_stamp, theme)
            theme_ids.setdefault(theme.id, []).append(entry)
        except ThemeCatalogError as exc:
            entry = _ThemeEntry(project, file_stamp, None, str(exc))
        projects[project.project_id] = entry
    return _ThemeIndex(owner, stamp, projects, theme_ids)


def _get_index(*, check_all: bool = False) -> _ThemeIndex:
    global _theme_index
    owner, stamp = get_project_service(), _catalog_stamp()
    index = _theme_index
    if (index is None or index.owner is not owner or index.catalog_stamp != stamp
        or (check_all and any(_entry_changed(entry) for entry in index.projects.values()))):
        index = _theme_index = _build_index(owner, stamp)
    return index


def _entry_changed(entry: _ThemeEntry) -> bool:
    return entry.stamp != _file_stamp(Path(entry.project.root_path) / THEME_MANIFEST_FILE)


def list_themes() -> list[ThemeSummary]:
    with _index_lock:
        index = _get_index(check_all=True)
        for theme_id, entries in index.theme_ids.items():
            if len(entries) > 1:
                raise ThemeCatalogError(f"Duplicate theme id: {theme_id}")
        return [ThemeSummary(id=entry.theme.id, name=entry.project.name, mode=entry.theme.mode)
            for entry in index.projects.values() if entry.theme is not None]


def get_active_theme_id() -> str:
    theme_id = get_theme_settings_repository().get_active_theme_id()
    if theme_id is None:
        return DEFAULT_THEME_ID

    _validate_theme_id(theme_id)
    return theme_id


def ensure_active_theme_selection() -> None:
    repository = get_theme_settings_repository()
    active_theme_id = repository.get_active_theme_id()
    if active_theme_id is not None:
        try:
            get_theme(active_theme_id)
            return
        except ThemeCatalogError:
            pass
    get_theme(DEFAULT_THEME_ID)
    repository.save_active_theme_id(DEFAULT_THEME_ID)


def get_active_theme() -> ThemeDefinition:
    return get_theme(get_active_theme_id())


def set_active_theme(theme_id: str) -> ThemeDefinition:
    theme = get_theme(theme_id)
    get_theme_settings_repository().save_active_theme_id(theme.id)
    return theme


def get_theme(theme_id: str) -> ThemeDefinition:
    _validate_theme_id(theme_id)
    project, theme = _find_theme(theme_id)
    return theme_definition_from_package(theme, name=project.name)


def save_theme(theme_id: str, theme: ThemeDefinition) -> ThemeDefinition:
    _validate_theme_id(theme_id)
    project, current = _find_theme(theme_id)
    if theme.id != current.id:
        raise ThemeSaveRejectedError("Theme id does not match request path")

    theme_file = Path(project.root_path) / THEME_MANIFEST_FILE

    package = theme_package_from_definition(
        theme,
        registration_name=current.registration_name,
    )
    payload = package.model_dump(mode="json", by_alias=True)
    content = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    temp_file = theme_file.with_name(f".{theme_file.name}.{uuid4().hex}.tmp")

    try:
        temp_file.write_text(content, encoding="utf-8")
        atomic_replace_path(temp_file, theme_file)
    except OSError as exc:
        try:
            temp_file.unlink(missing_ok=True)
        except OSError:
            pass
        raise ThemeCatalogError(f"Unable to save theme: {theme_id}") from exc
    finally:
        invalidate_theme_catalog()

    if project.name != theme.name:
        get_project_service().rename_project(project.project_id, name=theme.name)
    return get_theme(theme_id)


def get_theme_asset_path(asset_path: str) -> Path:
    normalized_path = Path(asset_path.replace("\\", "/"))
    if normalized_path.is_absolute() or ".." in normalized_path.parts or len(normalized_path.parts) < 3:
        raise ThemeAssetNotFoundError("Theme asset not found")

    theme_id = normalized_path.parts[0]
    if not _THEME_ID_PATTERN.fullmatch(theme_id) or normalized_path.parts[1] != "assets":
        raise ThemeAssetNotFoundError("Theme asset not found")

    try:
        entry = _find_theme_entry(theme_id)
    except ThemeNotFoundError as exc:
        raise ThemeAssetNotFoundError("Theme asset not found") from exc
    assets_root = (Path(entry.project.root_path) / "assets").resolve()
    target = (assets_root / Path(*normalized_path.parts[2:])).resolve()
    if not _is_relative_to(target, assets_root) or not target.is_file():
        raise ThemeAssetNotFoundError("Theme asset not found")
    return target


def _load_theme_file(theme_file: Path) -> ThemePackageDefinition:
    try:
        payload: Any = json.loads(theme_file.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ThemeCatalogError(f"Invalid theme JSON: {theme_file.name}") from exc
    except OSError as exc:
        raise ThemeCatalogError(f"Unable to read theme: {theme_file.name}") from exc

    try:
        theme = ThemePackageDefinition.model_validate(payload)
    except Exception as exc:
        raise ThemeCatalogError(f"Invalid theme contract: {theme_file.name}") from exc

    _validate_theme_id(theme.id)
    return theme


def load_theme_package(theme_root: Path) -> ThemePackageDefinition:
    return _load_theme_file(theme_root / THEME_MANIFEST_FILE)


def _find_theme(theme_id: str) -> tuple[Project, ThemePackageDefinition]:
    entry = _find_theme_entry(theme_id)
    # Callers may edit definitions; cached package objects are never handed out.
    return entry.project, entry.theme.model_copy(deep=True)


def _find_theme_entry(theme_id: str) -> _ThemeEntry:
    with _index_lock:
        index = _get_index()
        candidates = ([index.projects[theme_id]] if theme_id in index.projects
            else index.theme_ids.get(theme_id, []))
        if any(_entry_changed(entry) for entry in candidates):
            invalidate_theme_catalog()
            index = _get_index()
            candidates = ([index.projects[theme_id]] if theme_id in index.projects
                else index.theme_ids.get(theme_id, []))
        if not candidates:
            raise ThemeNotFoundError(f"Theme not found: {theme_id}")
        if len(candidates) > 1:
            raise ThemeCatalogError(f"Duplicate theme id: {theme_id}")
        entry = candidates[0]
        if entry.theme is None:
            if entry.stamp is None:
                raise ThemeNotFoundError(f"Theme not found: {theme_id}")
            raise ThemeCatalogError(entry.error or f"Invalid theme: {theme_id}")
        return entry


def _validate_theme_id(theme_id: str) -> None:
    if not _THEME_ID_PATTERN.fullmatch(theme_id):
        raise ThemeNotFoundError(f"Theme not found: {theme_id}")


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False
