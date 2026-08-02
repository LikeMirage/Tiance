from types import SimpleNamespace

import pytest

from app.core.errors import BadRequestError
from app.domain.project import Project, ProjectKind
from app.services.application import theme_project_policy


def test_active_theme_project_cannot_be_deleted(monkeypatch):
    project = Project(
        project_id="theme-project",
        name="当前主题",
        root_path="C:/themes/current",
        category_id="themes",
        project_kind=ProjectKind.THEME,
        is_default=False,
        sort_order=0,
        created_at="now",
        updated_at="now",
    )
    monkeypatch.setattr(
        theme_project_policy,
        "load_theme_package",
        lambda _root: SimpleNamespace(id="current-theme"),
    )
    monkeypatch.setattr(
        theme_project_policy,
        "get_active_theme_id",
        lambda: "current-theme",
    )

    with pytest.raises(BadRequestError):
        theme_project_policy.ensure_theme_project_can_be_deleted(project)
