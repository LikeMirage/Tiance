import json
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.core.atomic_replace import atomic_replace_path
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


def list_themes() -> list[ThemeSummary]:
    summaries: list[ThemeSummary] = []
    seen_theme_ids: set[str] = set()
    for project in _theme_projects():
        theme_file = Path(project.root_path) / THEME_MANIFEST_FILE
        if not theme_file.is_file():
            continue
        try:
            theme = _load_theme_file(theme_file)
        except ThemeCatalogError:
            continue
        if theme.id in seen_theme_ids:
            raise ThemeCatalogError(f"Duplicate theme id: {theme.id}")
        seen_theme_ids.add(theme.id)
        summaries.append(ThemeSummary(id=theme.id, name=project.name, mode=theme.mode))
    return summaries


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

    project, _theme = _find_theme(theme_id)
    assets_root = (Path(project.root_path) / "assets").resolve()
    target = (assets_root / Path(*normalized_path.parts[2:])).resolve()
    if not _is_relative_to(target, assets_root) or not target.is_file():
        raise ThemeAssetNotFoundError("Theme asset not found")
    return target


def _load_theme_file(theme_file: Path) -> ThemePackageDefinition:
    try:
        payload: Any = json.loads(theme_file.read_text(encoding="utf-8"))
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
    matched: tuple[Project, ThemePackageDefinition] | None = None
    for project in _theme_projects():
        theme_file = Path(project.root_path) / THEME_MANIFEST_FILE
        if not theme_file.is_file():
            continue
        if project.project_id == theme_id:
            return project, _load_theme_file(theme_file)
        try:
            theme = _load_theme_file(theme_file)
        except ThemeCatalogError:
            continue
        if theme.id != theme_id:
            continue
        if matched is not None:
            raise ThemeCatalogError(f"Duplicate theme id: {theme_id}")
        matched = (project, theme)
    if matched is None:
        raise ThemeNotFoundError(f"Theme not found: {theme_id}")
    return matched


def _theme_projects() -> tuple[Project, ...]:
    return tuple(
        project
        for project in get_project_service().list_projects()
        if project.project_kind is ProjectKind.THEME
    )


def _validate_theme_id(theme_id: str) -> None:
    if not _THEME_ID_PATTERN.fullmatch(theme_id):
        raise ThemeNotFoundError(f"Theme not found: {theme_id}")


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False
