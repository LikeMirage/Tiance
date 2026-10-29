import json
import os
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from app.domain.project import Project, ProjectKind
from app.infra.projects import read_project_identity
from app.repositories.project import FileProjectCatalog, conversation_database as db
from app.repositories.project.conversation_data_view_repository import ConversationDataViewRepository
from app.repositories.themes import ThemeSettingsRepository
from app.services.application.project_workspace_reconciliation import ProjectWorkspaceReconciliationService
from app.services.application.theme_workspace_reconciliation import ThemeWorkspaceReconciliationService
from app.services.locales import locale_catalog as locales


def test_bundled_locale_cache_preserves_external_language_edits(tmp_path, monkeypatch):
    bundled, data = tmp_path / "bundled", tmp_path / "Data-locales"
    shutil.copytree(locales._bundled_locale_dir(), bundled)
    monkeypatch.setattr(locales, "_bundled_locale_dir", lambda: bundled)
    locales._read_bundled_locale_packages.cache_clear()
    original = locales._read_json_file
    reads = []
    def read(path):
        if path.parent == bundled:
            reads.append(path.name)
        return original(path)
    monkeypatch.setattr(locales, "_read_json_file", read)
    try:
        package = locales.get_active_locale("en-US", data)
        assert len(reads) == 3
        locales.list_locales("en-US", data)
        locales.get_active_locale("en-US", data)
        assert len(reads) == 3
        package["messages"]["common"]["productName"] = "User translation"
        (data / "en-US.json").write_text(json.dumps(package), encoding="utf-8")
        assert locales.get_active_locale("en-US", data)["messages"]["common"]["productName"] == "User translation"
        custom = {**package, "locale": "fr-FR", "displayName": "French custom"}
        (data / "fr-FR.json").write_text(json.dumps(custom), encoding="utf-8")
        assert locales.get_active_locale("fr-FR", data)["displayName"] == "French custom"
        (data / "fr-FR.json").unlink()
        assert locales.get_active_locale("fr-FR", data)["locale"] == "en-US"
        # Replacing bundled source while running invalidates only that cache.
        package["displayName"] = "Updated builtin"
        (bundled / "en-US.json").write_text(json.dumps(package), encoding="utf-8")
        assert locales._load_bundled_locale_packages()["en-US"]["displayName"] == "Updated builtin"
        assert len(reads) == 6
        (bundled / "en-US.json").write_text("{broken", encoding="utf-8")
        with pytest.raises(locales.LocaleCatalogError):
            locales._load_bundled_locale_packages()
    finally:
        locales._read_bundled_locale_packages.cache_clear()


def test_index_dashboard_only_decodes_and_loads_states_for_current_page(tmp_path, monkeypatch):
    directory = tmp_path / ".Tiance" / "conversations"
    records = []
    with db.transaction_for_conversations(directory):
        for i in range(100):
            sid = f"s{i:03}"
            payload = {"session_id": sid, "created_at": "2026-10-29", "sequence_number": i,
                       "settings": {"system_prompt": "x" * 16_000}}
            records.append(payload)
            db.write_session(directory, sid, payload)
            db.write_session_draft(directory, sid, "d" * 8_000, "now")
            db.write_session_references(directory, sid, [{"path": f"/{sid}"}], "now")
        db.write_meta(directory, "conversation_index", {"active_session_id": "s099", "pinned_session_ids": ["s002", "s090", "missing"]})
    decoded, state_counts = [], []
    original_decode, original_states = db._decode, db._session_state_payloads_from_rows
    def decode(raw):
        value = original_decode(raw)
        if isinstance(value, dict) and "session_id" in value:
            decoded.append(value["session_id"])
        return value
    def states(rows):
        state_counts.append(len(rows))
        return original_states(rows)
    monkeypatch.setattr(db, "_decode", decode)
    monkeypatch.setattr(db, "_session_state_payloads_from_rows", states)
    project = Project("project", "Project", str(tmp_path), False, 0, "now", "now")
    repository = ConversationDataViewRepository(SimpleNamespace(get_project=lambda _: project))
    expected = sorted(records, key=lambda p: (p["session_id"] in {"s002", "s090"}, p["created_at"], p["sequence_number"]), reverse=True)
    for page in (1, 2, 999):
        view = repository.read("project", name="index.json", session_id=None, page=page, page_size=20)
        actual = json.loads(view.content)
        resolved = min(page, 5)
        assert view.total_count == 100 and view.page == resolved and view.total_pages == 5
        assert actual["sessions"] == expected[(resolved - 1) * 20:resolved * 20]
        assert actual["active_session_id"] == "s099"
        visible = {item["session_id"] for item in actual["sessions"]}
        assert set(actual["session_states"]) == visible
        assert set(actual["pinned_session_ids"]) == visible & {"s002", "s090"}
        assert all(s["draft"] == "d" * 8_000 for s in actual["session_states"].values())
    assert len(decoded) == 60 and state_counts == [20, 20, 20]


def test_index_page_is_a_consistent_snapshot_and_empty_reads_create_nothing(tmp_path, monkeypatch):
    directory = tmp_path / ".Tiance" / "conversations"
    assert db.read_session_index_page(directory, page=1, page_size=20)[0] == 0
    assert not directory.parent.exists()
    db.write_session(directory, "a", {"session_id": "a"})
    db.write_meta(directory, "conversation_index", {"active_session_id": "a"})
    original = db._decode
    changed = False
    def decode(raw):
        nonlocal changed
        value = original(raw)
        if not changed:
            changed = True
            db.write_session(directory, "b", {"session_id": "b"})
        return value
    monkeypatch.setattr(db, "_decode", decode)
    count, payload = db.read_session_index_page(directory, page=1, page_size=20)
    assert count == 1 and [p["session_id"] for p in payload["sessions"]] == ["a"]
    assert db.read_session_index_page(directory, page=1, page_size=20)[0] == 2


def _link(link, target):
    if os.name == "nt":
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], check=True, capture_output=True)
    else:
        link.symlink_to(target, target_is_directory=True)


def test_project_auto_discovery_ignores_links_but_keeps_explicit_external_projects(tmp_path):
    root, external = tmp_path / "projects", tmp_path / "external"
    root.mkdir(); external.mkdir()
    normal = root / "normal"
    normal.mkdir()
    _link(root / "outside-link", external)
    _link(root / "inside-link", normal)
    catalog = FileProjectCatalog(root, project_kind=ProjectKind.PROJECT, allow_external_roots=True)
    service = ProjectWorkspaceReconciliationService(projects_root=root, catalog=catalog)
    result = service.synchronize()
    assert len(result.added_project_ids) == 1
    assert [p.root_path for p in catalog.list_projects()] == [str(normal.resolve())]
    assert not (external / ".Tiance").exists()
    # Only remove the link itself, never the external target.
    if os.name == "nt": (root / "outside-link").rmdir()
    else: (root / "outside-link").unlink()
    assert not service.synchronize().added_project_ids
    category = catalog.list_project_categories()[0]
    explicit_id = "4a118c53-213d-493a-85f0-dbdc80b64da5"
    explicit = Project(explicit_id, "External", str(external), False, 1, "now", "now", category.category_id, ProjectKind.PROJECT)
    catalog.save_project(explicit)
    service.synchronize()
    assert read_project_identity(external).project_id == explicit_id
    assert catalog.get_project(explicit_id) is not None


def test_theme_discovery_and_builtin_recovery_never_write_through_junction(tmp_path):
    root, external = tmp_path / "themes", tmp_path / "external"
    root.mkdir(); external.mkdir()
    _link(root / "dark-gold", external)
    recovery = Path(__file__).resolve().parents[1] / "app/resources/themes"
    catalog = FileProjectCatalog(root, project_kind=ProjectKind.THEME)
    settings = ThemeSettingsRepository(root / "theme-settings.json")
    service = ThemeWorkspaceReconciliationService(themes_root=root, recovery_root=recovery, catalog=catalog, settings_repository=settings)
    result = service.synchronize()
    assert not list(external.iterdir())
    assert result.active_theme_id == "light"
    assert {Path(p.root_path).name for p in catalog.list_projects()} == {"light"}
