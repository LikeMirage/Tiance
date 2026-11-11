from pathlib import Path
from types import SimpleNamespace
import json
import os
import subprocess

import pytest

from app.core.errors import BadRequestError, ConflictError
from app.domain.file_workspace import TextFileUpdate
from app.domain.project import ProjectKind
from app.infra.file_workspace.text_transaction import text_file_transaction
from app.infra.file_workspace import FileWorkspaceStorage
from app.infra.tools import ToolProjectConfigStorage
from app.services.tools.tool_folder_files import ToolFolderFileService
from app.services.application import project_scaffold as scaffold


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    roots = {kind: tmp_path / kind for kind in ("tools", "roles", "themes")}
    root = roots["tools"] / "project"
    root.mkdir(parents=True)
    project = SimpleNamespace(project_id="project", project_kind=ProjectKind.TOOL,
                              category_id="category", root_path=str(root))
    category = SimpleNamespace(category_id="category", category_kind=ProjectKind.TOOL)
    monkeypatch.setattr(scaffold, "get_settings", lambda: SimpleNamespace(
        tools_data_path=roots["tools"], roles_data_path=roots["roles"], themes_data_path=roots["themes"]))
    monkeypatch.setattr(scaffold, "get_project_service", lambda: SimpleNamespace(
        get_project=lambda _: project, list_project_categories=lambda: [category]))
    def write(_id, updates):
        with text_file_transaction(root, updates, lambda base, path: base / path):
            pass
    monkeypatch.setattr(scaffold, "get_project_file_service", lambda: SimpleNamespace(write_text_files=write))
    tool_files = ToolFolderFileService(ToolProjectConfigStorage(), FileWorkspaceStorage(),
        tool_project_service=SimpleNamespace(require_tool_project=lambda *_: project))
    monkeypatch.setattr(scaffold, "get_tool_folder_file_service", lambda: tool_files)
    return root, project, category, roots


@pytest.mark.parametrize("kind,collection", [(ProjectKind.TOOL, "tools"), (ProjectKind.ROLE, "roles"), (ProjectKind.THEME, "themes")])
def test_all_collections_check_registration_kind_and_real_root(workspace, kind, collection):
    _, project, category, roots = workspace
    root = roots[collection] / "target"
    root.mkdir(parents=True)
    project.root_path = str(root)
    project.project_kind = category.category_kind = kind
    assert scaffold.require_collection_workspace("project", kind.value, str(root)) is project
    with pytest.raises(BadRequestError):
        scaffold.require_collection_workspace("project", kind.value, str(root.parent))
    project.root_path = str(root.parent)
    with pytest.raises(BadRequestError):
        scaffold.require_collection_workspace("project", kind.value)
    project.root_path = str(root)
    category.category_kind = ProjectKind.PROJECT
    with pytest.raises(BadRequestError):
        scaffold.require_collection_workspace("project", kind.value)


def test_existing_files_are_preserved_and_repeat_is_idempotent(workspace):
    root, *_ = workspace
    (root / "config.json").write_text("user content", encoding="utf-8")
    files = [TextFileUpdate("config.json", "template"), TextFileUpdate("docs/README.md", "guide")]
    first = scaffold.install_project_scaffold("project", "tool", files)
    assert first["written_files"] == ["docs/README.md"]
    assert first["preserved_files"] == ["config.json"]
    assert (root / "config.json").read_text() == "user content"
    assert scaffold.install_project_scaffold("project", "tool", files)["written_files"] == []


@pytest.mark.parametrize("path", ["../outside", ".Tiance/data", "docs/.Tiance/data", "C:/temp/out", "docs\\out", "docs./out"])
def test_reject_escape_and_private_data_before_any_write(workspace, path):
    root, *_ = workspace
    with pytest.raises(BadRequestError):
        scaffold.install_project_scaffold("project", "tool", [TextFileUpdate("first.txt", "first"), TextFileUpdate(path, "bad")])
    assert not (root / "first.txt").exists()


def test_failed_batch_removes_new_files_and_preserves_existing(workspace, monkeypatch):
    root, *_ = workspace
    (root / "existing.txt").write_text("keep")
    link = os.link
    def fail_second(source, target, **kwargs):
        if Path(target).name == "second.txt":
            raise OSError("simulated full disk")
        return link(source, target, **kwargs)
    monkeypatch.setattr(os, "link", fail_second)
    with pytest.raises(OSError, match="full disk"):
        scaffold.install_project_scaffold("project", "tool", [TextFileUpdate("existing.txt", "overwrite"),
            TextFileUpdate("first.txt", "first"), TextFileUpdate("second.txt", "second")])
    assert [p.name for p in root.iterdir()] == ["existing.txt"]
    assert (root / "existing.txt").read_text() == "keep"


def test_external_file_created_during_commit_is_not_overwritten(workspace, monkeypatch):
    root, *_ = workspace
    link = os.link
    def race(source, target, **kwargs):
        Path(target).write_text("external editor")
        return link(source, target, **kwargs)
    monkeypatch.setattr(os, "link", race)
    with pytest.raises(FileExistsError):
        scaffold.install_project_scaffold("project", "tool", [TextFileUpdate("first.txt", "template")])
    assert (root / "first.txt").read_text() == "external editor"


def manifest_content(name):
    return json.dumps({"registration_name": "Example", "name": name,
                       "execution": {"parallel": True}, "state": {"enabled": False},
                       "runtime": {"type": "python", "entry": "program/main.py", "timeout_seconds": 60}})


def test_tool_init_rejects_invalid_or_duplicate_manifest_before_writing(workspace):
    root, *_ = workspace
    service = scaffold.get_tool_folder_file_service()
    service._registry_service = SimpleNamespace(list_entries=lambda **_: [
        SimpleNamespace(project_id="other", tool_name="duplicate")])
    for content, error in [("not json", BadRequestError),
            (manifest_content("duplicate"), ConflictError)]:
        with pytest.raises(error):
            scaffold.install_project_scaffold("project", "tool", [
                TextFileUpdate("docs/README.md", "guide"), TextFileUpdate(".tool/tool.json", content)])
        assert not (root / "docs/README.md").exists()
        assert not (root / ".tool/tool.json").exists()


def test_tool_init_rolls_back_if_registry_refresh_fails(workspace):
    root, *_ = workspace
    service = scaffold.get_tool_folder_file_service()
    def fail():
        raise RuntimeError("registry unavailable")
    service._registry_service = SimpleNamespace(list_entries=lambda **_: [], rebuild_registry=fail)
    with pytest.raises(RuntimeError, match="registry unavailable"):
        scaffold.install_project_scaffold("project", "tool", [
            TextFileUpdate("docs/README.md", "guide"), TextFileUpdate(".tool/tool.json",
                manifest_content("unique_tool"))])
    assert not (root / "docs/README.md").exists()
    assert not (root / ".tool/tool.json").exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows junction boundary")
def test_junction_workspace_and_nested_junction_rejected(workspace, tmp_path):
    root, project, _, roots = workspace
    outside = tmp_path / "outside"
    outside.mkdir()
    # mklink creates the fixture only; no cross-shell destructive file operations.
    for link in (roots["tools"] / "linked", root / "nested"):
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)], check=True, capture_output=True)
    project.root_path = str(roots["tools"] / "linked")
    with pytest.raises(BadRequestError):
        scaffold.require_collection_workspace("project", "tool")
    project.root_path = str(root)
    with pytest.raises(BadRequestError):
        scaffold.install_project_scaffold("project", "tool", [TextFileUpdate("nested/file.txt", "bad")])
    assert list(outside.iterdir()) == []
