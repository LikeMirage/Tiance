import asyncio
import json
from pathlib import Path

import pytest

from app.core.errors import BadRequestError
from app.domain.project import ProjectKind
from role_market_test_support import build_role_market_service


def test_new_role_install_uses_role_project_lifecycle_and_selected_category(tmp_path) -> None:
    service, project_service, conversation_service, catalog, _remote, _roles_root = (
        build_role_market_service(tmp_path)
    )
    category = project_service.create_project_category(
        name="写作角色",
        category_kind=ProjectKind.ROLE,
    )

    response = asyncio.run(service.install_role(
        role_id="sample-role",
        category_id=category.category_id,
    ))

    project = catalog.get_project(response.project_id)
    assert project is not None
    assert project.category_id == category.category_id
    assert project.name == "示例角色"
    root = Path(project.root_path)
    assert (root / ".Tiance" / "conversations").is_dir()
    assert len(conversation_service.list_sessions(project.project_id)) == 1
    assert json.loads((root / "manifest.json").read_text(encoding="utf-8"))["id"] == (
        "sample-role"
    )
    assert json.loads((root / "model.json").read_text(encoding="utf-8")) == {
        "provider_id": "remote",
        "model_id": "preferred",
        "reasoning_mode": None,
    }


def test_install_rejects_non_role_category_before_download(tmp_path) -> None:
    service, project_service, _conversations, _catalog, remote, _roles_root = (
        build_role_market_service(tmp_path)
    )
    invalid = project_service.ensure_default_project_category()

    with pytest.raises(BadRequestError, match="角色分类"):
        asyncio.run(service.install_role(
            role_id="sample-role",
            category_id=invalid.category_id,
        ))

    assert remote.download_calls == 0


def test_install_failure_removes_incomplete_project_registration(tmp_path, monkeypatch) -> None:
    service, project_service, _conversations, catalog, _remote, _roles_root = (
        build_role_market_service(tmp_path)
    )
    category = project_service.ensure_default_role_project_category()

    def fail_replace(*_args, **_kwargs):
        raise OSError("write failed")

    monkeypatch.setattr(service, "_replace_managed_files", fail_replace)
    with pytest.raises(OSError, match="write failed"):
        asyncio.run(service.install_role(
            role_id="sample-role",
            category_id=category.category_id,
        ))

    assert all(project.name != "示例角色" for project in catalog.list_projects())


def test_install_preserves_model_and_tool_preferences_without_resolving_them(tmp_path) -> None:
    service, project_service, _conversations, catalog, remote, _roles_root = (
        build_role_market_service(tmp_path)
    )
    category = project_service.ensure_default_role_project_category()
    response = asyncio.run(service.install_role(
        role_id="sample-role",
        category_id=category.category_id,
    ))

    project = catalog.get_project(response.project_id)
    assert project is not None
    root = Path(project.root_path)
    assert json.loads((root / "model.json").read_text(encoding="utf-8")) == {
        "provider_id": "remote",
        "model_id": "preferred",
        "reasoning_mode": None,
    }
    assert json.loads((root / "tools.json").read_text(encoding="utf-8")) == {
        "tools_enabled": True,
        "enabled_tool_names": ["missing-tool"],
        "max_tool_calls": 8,
    }
    assert remote.download_calls == 1
