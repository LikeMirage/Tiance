from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.domain.project import Project, ProjectKind
from app.services.themes import theme_catalog as catalog
from app.services.themes.theme_workspace_watcher import ThemeWorkspaceEventBroker


@pytest.fixture
def themes(tmp_path, monkeypatch):
    template = json.loads((Path(__file__).parents[1] / "app/resources/themes/dark-gold.json").read_text(encoding="utf-8"))
    projects = []
    for i in range(20):
        root = tmp_path / f"theme-{i}"
        (root / "assets").mkdir(parents=True)
        (root / "assets/bg.png").write_bytes(b"test-image")
        (root / "theme.json").write_text(json.dumps({**template, "id": f"theme-{i}"}), encoding="utf-8")
        projects.append(Project(project_id=f"project-{i}", name=f"Theme {i}", root_path=str(root),
            project_kind=ProjectKind.THEME, is_default=False, sort_order=i, created_at="now", updated_at="now"))
    (tmp_path / "catalog.json").write_text("first")
    counts = {"lists": 0, "parses": 0}
    def list_projects():
        counts["lists"] += 1
        return tuple(projects)
    def rename(project_id, *, name):
        index = next(i for i, p in enumerate(projects) if p.project_id == project_id)
        projects[index] = replace(projects[index], name=name)
        (tmp_path / "catalog.json").write_text(name)
        return projects[index]
    service = SimpleNamespace(list_projects=list_projects, rename_project=rename)
    original = catalog._load_theme_file
    def load(path):
        counts["parses"] += 1
        return original(path)
    monkeypatch.setattr(catalog, "get_project_service", lambda: service)
    monkeypatch.setattr(catalog, "get_settings", lambda: SimpleNamespace(themes_data_path=tmp_path))
    monkeypatch.setattr(catalog, "_load_theme_file", load)
    catalog.invalidate_theme_catalog()
    yield tmp_path, projects, counts
    catalog.invalidate_theme_catalog()


def test_ten_assets_resolve_with_one_catalog_read_and_one_parse_per_theme(themes):
    root, _, counts = themes
    for i in range(10):
        assert catalog.get_theme_asset_path(f"theme-{i}/assets/bg.png") == root / f"theme-{i}/assets/bg.png"
    assert counts == {"lists": 1, "parses": 20}


def test_manifest_edit_save_and_project_rename_invalidate_cached_definitions(themes):
    root, projects, counts = themes
    theme = catalog.get_theme("theme-0")
    catalog.save_theme("theme-0", theme.model_copy(update={"name": "New name"}))
    assert catalog.get_theme("theme-0").name == "New name"
    file = root / "theme-0/theme.json"
    payload = json.loads(file.read_text(encoding="utf-8"))
    payload["id"] = "changed-id"
    file.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(catalog.ThemeNotFoundError):
        catalog.get_theme("theme-0")
    assert catalog.get_theme("changed-id").id == "changed-id"
    assert catalog.get_theme(projects[0].project_id).id == "changed-id"


def test_catalog_delete_and_relocate_cannot_serve_stale_paths(themes):
    root, projects, _ = themes
    catalog.get_theme_asset_path("theme-0/assets/bg.png")
    moved = root / "relocated"
    (root / "theme-0").rename(moved)
    projects[0] = replace(projects[0], root_path=str(moved))
    (root / "catalog.json").write_text("moved directory")
    assert catalog.get_theme_asset_path("theme-0/assets/bg.png") == moved / "assets/bg.png"
    projects.pop(0)
    (root / "catalog.json").write_text("removed registration")
    with pytest.raises(catalog.ThemeAssetNotFoundError):
        catalog.get_theme_asset_path("theme-0/assets/bg.png")


def test_workspace_event_invalidates_duplicate_ids_and_invalid_config(themes):
    root, _, _ = themes
    catalog.get_theme("theme-0")
    other = root / "theme-1/theme.json"
    payload = json.loads(other.read_text(encoding="utf-8"))
    payload["id"] = "theme-0"
    other.write_text(json.dumps(payload), encoding="utf-8")
    ThemeWorkspaceEventBroker().publish(("theme-1/theme.json",))
    with pytest.raises(catalog.ThemeCatalogError, match="Duplicate"):
        catalog.get_theme("theme-0")
    other.write_text("broken", encoding="utf-8")
    ThemeWorkspaceEventBroker().publish(("theme-1/theme.json",))
    assert catalog.get_theme("theme-0").id == "theme-0"


@pytest.mark.parametrize("path", ["theme-0/assets/../../catalog.json", "/theme-0/assets/bg.png",
                                 "theme-0/theme.json", "theme-0/assets/missing.png"])
def test_cached_asset_lookup_retains_path_validation(themes, path):
    catalog.get_theme_asset_path("theme-0/assets/bg.png")
    with pytest.raises(catalog.ThemeAssetNotFoundError):
        catalog.get_theme_asset_path(path)


def test_mutating_a_returned_definition_does_not_change_the_cached_package(themes):
    first = catalog.get_theme("theme-0")
    expected = first.model_dump()
    first.tokens.structure.width = 1.9
    assert catalog.get_theme("theme-0").model_dump() == expected


def test_removed_manifest_stops_cached_asset_access_immediately(themes):
    root, _, _ = themes
    catalog.get_theme_asset_path("theme-0/assets/bg.png")
    (root / "theme-0/theme.json").unlink()
    with pytest.raises(catalog.ThemeAssetNotFoundError):
        catalog.get_theme_asset_path("theme-0/assets/bg.png")


def test_asset_replacement_does_not_rebuild_the_theme_index(themes):
    root, _, counts = themes
    asset = catalog.get_theme_asset_path("theme-0/assets/bg.png")
    asset.write_bytes(b"new image")
    assert catalog.get_theme_asset_path("theme-0/assets/bg.png").read_bytes() == b"new image"
    assert counts == {"lists": 1, "parses": 20}
