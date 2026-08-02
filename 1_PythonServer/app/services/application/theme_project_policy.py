from pathlib import Path

from app.core.errors import BadRequestError
from app.domain.project import Project, ProjectKind
from app.services.themes import ThemeCatalogError, get_active_theme_id
from app.services.themes.theme_catalog import load_theme_package


def ensure_theme_project_can_be_deleted(project: Project) -> None:
    if project.project_kind is not ProjectKind.THEME:
        return
    try:
        theme = load_theme_package(Path(project.root_path))
    except ThemeCatalogError:
        return
    if theme.id == get_active_theme_id():
        raise BadRequestError("当前正在使用的主题不能删除，请先切换其他主题。")
