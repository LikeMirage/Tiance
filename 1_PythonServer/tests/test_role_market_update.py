import asyncio
import json
from pathlib import Path

import pytest

from app.core.errors import BadRequestError
from app.domain.project import ProjectKind
from app.services.application import role_market as role_market_module

from tests.role_market_test_support import build_role_market_service, role_files


def test_update_preserves_project_identity_category_name_sort_and_workspace(tmp_path) -> None:
    service, project_service, conversations, catalog, _remote, _roles_root = (
        build_role_market_service(tmp_path, version="1.1.0")
    )
    category = project_service.create_project_category(
        name="保留分类",
        category_kind=ProjectKind.ROLE,
    )
    project = service._project_creation_service.create_role_project(
        name="用户改过的名称",
        category_id=category.category_id,
    )
    project_service.save_project_order((project.project_id,))
    root = Path(project.root_path)
    _write_market_files(root, "1.0.0")
    session = conversations.list_sessions(project.project_id)[0]
    messages = root / ".Tiance" / "conversations" / "sessions" / session.session_id / "messages.jsonl"
    messages.write_text('{"role":"user","content":"保留"}\n', encoding="utf-8")
    (root / "notes.txt").write_text("保留额外文件", encoding="utf-8")
    original = catalog.get_project(project.project_id)

    response = asyncio.run(service.install_role(
        role_id="sample-role",
        category_id=None,
        replace_existing=True,
    ))

    updated = catalog.get_project(project.project_id)
    assert response.updated is True
    assert updated == original
    assert json.loads((root / "manifest.json").read_text(encoding="utf-8"))["version"] == "1.1.0"
    assert messages.read_text(encoding="utf-8") == '{"role":"user","content":"保留"}\n'
    assert (root / "notes.txt").read_text(encoding="utf-8") == "保留额外文件"


def test_update_failure_restores_every_managed_file(tmp_path, monkeypatch) -> None:
    service, project_service, _conversations, _catalog, _remote, _roles_root = (
        build_role_market_service(tmp_path, version="1.1.0")
    )
    category = project_service.ensure_default_role_project_category()
    project = service._project_creation_service.create_role_project(
        name="保留角色",
        category_id=category.category_id,
    )
    root = Path(project.root_path)
    _write_market_files(root, "1.0.0")
    originals = {path.name: path.read_bytes() for path in root.glob("*.json")}
    real_atomic_copy = role_market_module._atomic_copy
    calls = 0

    def fail_mid_update(source: Path, target: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 4:
            raise OSError("disk full")
        real_atomic_copy(source, target)

    monkeypatch.setattr(role_market_module, "_atomic_copy", fail_mid_update)
    with pytest.raises(OSError, match="disk full"):
        asyncio.run(service.install_role(
            role_id="sample-role",
            category_id=None,
            replace_existing=True,
        ))

    assert {path.name: path.read_bytes() for path in root.glob("*.json")} == originals


def test_status_recognizes_installed_update_and_ignores_plain_local_roles(tmp_path) -> None:
    service, project_service, _conversations, _catalog, _remote, _roles_root = (
        build_role_market_service(tmp_path, version="1.1.0")
    )
    category = project_service.ensure_default_role_project_category()
    plain = service._project_creation_service.create_role_project(
        name="同名普通角色",
        category_id=category.category_id,
    )

    first = asyncio.run(service.get_index())
    assert first.roles[0].installation_status == "not-installed"

    _write_market_files(Path(plain.root_path), "1.0.0")
    second = asyncio.run(service.get_index())
    assert second.roles[0].installation_status == "update-available"
    assert second.roles[0].local_project_id == plain.project_id


def test_network_failure_reads_only_same_source_cache(tmp_path) -> None:
    service, _projects, _conversations, _catalog, remote, _roles_root = (
        build_role_market_service(tmp_path)
    )
    live = asyncio.run(service.get_index())
    remote.fail_index = True
    cached = asyncio.run(service.get_index())

    assert live.cached is False
    assert cached.cached is True
    service._settings_repository.save_source("https://example.com/other-market")
    with pytest.raises(Exception, match="网络失败"):
        asyncio.run(service.get_index())


def test_invalid_live_index_is_not_hidden_by_old_cache(tmp_path, monkeypatch) -> None:
    service, _projects, _conversations, _catalog, remote, _roles_root = (
        build_role_market_service(tmp_path)
    )
    asyncio.run(service.get_index())

    async def invalid_index(_source: str) -> dict[str, object]:
        return {"schemaVersion": 1, "kind": "wrong", "roles": []}

    monkeypatch.setattr(remote, "fetch_index", invalid_index)
    with pytest.raises(BadRequestError, match="索引格式无效"):
        asyncio.run(service.get_index())


def _write_market_files(root: Path, version: str) -> None:
    for name, payload in role_files(version).items():
        (root / name).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
