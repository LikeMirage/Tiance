import asyncio
from datetime import UTC, datetime
import json
from pathlib import Path

import pytest

from app.domain.project import Project, ProjectCategory, ProjectKind
from app.repositories.project import FileProjectCatalog
from app.repositories.themes import (
    ThemeMarketCacheRepository,
    ThemeMarketSettingsRepository,
)
from app.services.application.theme_market import ThemeMarketApplicationService


class FakeRemoteClient:
    async def fetch_index(self, _source: str) -> dict[str, object]:
        return {
            "schemaVersion": 1,
            "kind": "tiance-theme-market",
            "name": "Test market",
            "updatedAt": "2026-08-01T00:00:00Z",
            "themes": [{
                "id": "sample-theme",
                "name": "示例主题",
                "mode": "light",
                "version": "1.1.0",
                "author": "LikeMirage",
                "summary": "更新后的主题。",
                "license": "CC0-1.0",
                "baseColors": ["white", "blue"],
                "previewUrl": "previews/sample-theme.png",
                "packageUrl": "packages/sample-theme-1.1.0.zip",
                "sha256": "0" * 64,
                "size": 1,
                "compatibility": {
                    "themeSchemaVersion": 2,
                    "minTianceVersion": "0.1.0",
                },
            }],
        }

    async def download_package(self, *, target: Path, **_kwargs) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"x")


class FakeArchive:
    def validate_and_extract(self, *, staging_root: Path, market_entry, **_kwargs) -> Path:
        root = staging_root / market_entry.id
        root.mkdir(parents=True)
        (root / "theme.json").write_text(
            json.dumps({
                "id": market_entry.id,
                "registrationName": market_entry.name,
            }),
            encoding="utf-8",
        )
        (root / "manifest.json").write_text(
            json.dumps({"version": market_entry.version}),
            encoding="utf-8",
        )
        (root / "assets").mkdir()
        (root / "assets/new.png").write_bytes(b"new")
        return root


class FakeProjectService:
    def get_project_category(self, _category_id: str):
        return None

    def move_project_to_category(self, *_args, **_kwargs):
        raise AssertionError("更新现有主题时不应修改用户分类。")


class FakeReconciliationService:
    def __init__(self, themes_root: Path, *, fail_once: bool = False) -> None:
        self.themes_root = themes_root
        self._fail_once = fail_once

    def synchronize(self) -> None:
        if self._fail_once:
            self._fail_once = False
            raise RuntimeError("同步失败")


def test_theme_update_preserves_project_data_without_archiving_previous_version(tmp_path) -> None:
    service, themes_root, catalog, project = _create_service(tmp_path)

    response = asyncio.run(service.install_theme(
        theme_id="sample-theme",
        category_id=None,
        replace_existing=True,
    ))

    assert response.project_id == project.project_id
    assert response.category_id == project.category_id
    assert _version(themes_root / "sample-theme") == "1.1.0"
    assert catalog.get_project(project.project_id) == project
    assert (themes_root / "sample-theme/.Tiance/local.json").read_text(encoding="utf-8") == "keep"
    assert (themes_root / "sample-theme/notes.md").read_text(encoding="utf-8") == "keep"
    assert not (themes_root / "sample-theme/assets/old.png").exists()
    assert (themes_root / "sample-theme/assets/new.png").read_bytes() == b"new"
    assert not (themes_root / ".trash").exists()


def test_theme_update_restores_previous_version_when_sync_fails(tmp_path) -> None:
    service, themes_root, _, _ = _create_service(tmp_path, fail_once=True)

    with pytest.raises(RuntimeError, match="同步失败"):
        asyncio.run(service.install_theme(
            theme_id="sample-theme",
            category_id=None,
            replace_existing=True,
        ))

    assert _version(themes_root / "sample-theme") == "1.0.0"
    assert (themes_root / "sample-theme/.Tiance/local.json").read_text(encoding="utf-8") == "keep"
    assert (themes_root / "sample-theme/notes.md").read_text(encoding="utf-8") == "keep"
    assert (themes_root / "sample-theme/assets/old.png").read_bytes() == b"old"


def _create_service(tmp_path, *, fail_once: bool = False):
    themes_root = tmp_path / "themes"
    theme_root = themes_root / "sample-theme"
    theme_root.mkdir(parents=True)
    (theme_root / "theme.json").write_text(
        json.dumps({"id": "sample-theme", "registrationName": "示例主题"}),
        encoding="utf-8",
    )
    (theme_root / "manifest.json").write_text(
        json.dumps({"version": "1.0.0"}),
        encoding="utf-8",
    )
    (theme_root / ".Tiance").mkdir()
    (theme_root / ".Tiance/local.json").write_text("keep", encoding="utf-8")
    (theme_root / "notes.md").write_text("keep", encoding="utf-8")
    (theme_root / "assets").mkdir()
    (theme_root / "assets/old.png").write_bytes(b"old")
    catalog = FileProjectCatalog(themes_root, project_kind=ProjectKind.THEME)
    now = datetime.now(UTC).isoformat()
    category = catalog.save_project_category(ProjectCategory(
        category_id="my-themes",
        name="我的主题",
        category_kind=ProjectKind.THEME,
        is_default=True,
        sort_order=0,
        created_at=now,
        updated_at=now,
    ))
    project = catalog.save_project(Project(
        project_id="sample-project",
        name="用户保留名称",
        root_path=str(theme_root),
        category_id=category.category_id,
        project_kind=ProjectKind.THEME,
        is_default=False,
        sort_order=7,
        created_at=now,
        updated_at=now,
    ))
    service = ThemeMarketApplicationService(
        app_version="0.1.0",
        settings_repository=ThemeMarketSettingsRepository(
            themes_root / "market-settings.json"
        ),
        cache_repository=ThemeMarketCacheRepository(themes_root / ".market-cache"),
        remote_client=FakeRemoteClient(),
        archive=FakeArchive(),
        catalog=catalog,
        project_service=FakeProjectService(),
        reconciliation_service=FakeReconciliationService(
            themes_root,
            fail_once=fail_once,
        ),
    )
    return service, themes_root, catalog, project


def _version(theme_root: Path) -> str:
    return json.loads((theme_root / "manifest.json").read_text(encoding="utf-8"))["version"]
