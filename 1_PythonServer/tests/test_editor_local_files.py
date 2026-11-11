from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import editor_files as routes
from app.core.errors import BadRequestError, NotFoundError, register_exception_handlers
from app.infra.file_workspace import FileWorkspaceStorage
from app.services import editor_local_files as service
from app.services.project.project_files import ProjectFileService


@pytest.fixture
def client():
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(routes.router)
    with TestClient(app) as client:
        yield client


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    root = tmp_path / "项目"
    root.mkdir()
    storage = FileWorkspaceStorage()
    project = SimpleNamespace(get_project_root=lambda project_id: str(root),
        _require_project_root=lambda project_id: str(root), _storage=storage)
    project.get_file_path = lambda project_id, target_path: ProjectFileService.get_file_path(project, project_id, target_path)
    monkeypatch.setattr(service, "get_project_file_service", lambda: project)
    return root


def resolve(client, path, **kwargs):
    return client.post("/editor/file-references/resolve", json={"path": str(path),
        "source": "external_path", "owner_project_id": "owner", **kwargs})


def test_internal_paths_and_external_alias_reuse_project_source(client, workspace):
    target = workspace / "报告 #1.md"
    target.write_text("# 正文", encoding="utf-8")
    for result in [resolve(client, target), resolve(client, target.name,
            source="project_file", project_id="owner")]:
        assert result.status_code == 200, result.text
        assert result.json()["kind"] == "project"
        assert result.json()["path"] == target.name


def test_external_reference_preserves_source_file_without_copy(client, workspace, tmp_path):
    target = tmp_path / "外部 # %.md"
    target.write_text("external", encoding="utf-8")
    result = resolve(client, target).json()
    assert result["kind"] == "local"
    assert Path(result["root"]) / result["path"] == target
    assert list(workspace.iterdir()) == []
    assert resolve(client, "relative.md").status_code == 400
    assert resolve(client, tmp_path / "missing.md").status_code == 404


def test_folder_reference_resolves_registry_identity_and_missing_without_mutation(client, workspace, tmp_path, monkeypatch):
    import app.repositories.project as repositories
    folder = tmp_path / "external-folder"
    folder.mkdir()
    project = SimpleNamespace(project_id="target", name="实际项目名", project_kind="project", category_id="cat")
    monkeypatch.setattr(repositories, "get_project_repository", lambda: SimpleNamespace(
        get_project_by_root_path=lambda path: project if Path(path) == folder else None,
        get_project_category=lambda category: SimpleNamespace(name="分类")))
    result = resolve(client, folder, kind="folder")
    assert result.status_code == 200, result.text
    assert result.json()["project"]["name"] == "实际项目名"
    assert result.json()["path"] == folder.as_posix()
    assert list(folder.iterdir()) == []
    assert resolve(client, tmp_path / "absent", kind="folder").status_code == 404
    nested = workspace / "nested"
    nested.mkdir()
    assert resolve(client, "nested", kind="folder", source="project_file", project_id="owner").json()["project"] is None
    assert resolve(client, "../external-folder", kind="folder", source="project_file", project_id="owner").status_code == 400


def test_attachment_resolves_only_in_its_conversation(client, workspace, monkeypatch):
    target = workspace / ".Tiance" / "sessions" / "s" / "attachments" / "att.png"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"image")
    calls = []
    def read(project, session, uri):
        calls.append((project, session, uri))
        if session != "s":
            raise NotFoundError("找不到附件。")
        return SimpleNamespace(display_name="粘贴图片.png"), target
    monkeypatch.setattr(service, "get_conversation_attachment_repository", lambda: SimpleNamespace(read=read))
    result = resolve(client, "tiance-attachment://att_123", source="project_file", project_id="owner", session_id="s")
    assert result.status_code == 200
    assert result.json()["name"] == "粘贴图片.png"
    assert result.json()["path"] == target.relative_to(workspace).as_posix()
    assert resolve(client, "tiance-attachment://att_123", project_id="owner", session_id="wrong").status_code == 404
    assert resolve(client, "tiance-attachment://att_123", project_id="owner").status_code == 400
    assert calls == [("owner", "s", "tiance-attachment://att_123"), ("owner", "wrong", "tiance-attachment://att_123")]


def test_external_text_reads_saves_and_detects_conflict(client, tmp_path):
    target = tmp_path / "文本.md"
    target.write_text("before", encoding="utf-8")
    endpoint = "/editor/local/files/content"
    read = client.get(endpoint, params={"path": str(target)})
    assert read.status_code == 200
    stamp = read.json()["mtime_ms"]
    conflict = client.put(endpoint, params={"path": str(target)}, json={"content": "bad", "expected_mtime_ms": stamp - 1000})
    assert conflict.status_code == 409
    assert target.read_text(encoding="utf-8") == "before"
    saved = client.put(endpoint, params={"path": str(target)}, json={"content": "after", "expected_mtime_ms": stamp})
    assert saved.status_code == 200, saved.text
    assert target.read_text(encoding="utf-8") == "after"
    assert client.get(endpoint, params={"path": "relative.txt"}).status_code == 400
    assert client.get(endpoint, params={"path": str(tmp_path / "gone.txt")}).status_code == 404


@pytest.mark.parametrize("suffix,route,params,operation", [
    (".png", "preview", {}, None),
    (".xlsx", "preview/spreadsheet", {"version": "v", "sheet": 2, "row": 50}, "spreadsheet"),
    (".docx", "preview/word", {"version": "v", "chunk": 3}, "word"),
])
def test_previews_use_shared_worker(client, tmp_path, monkeypatch, suffix, route, params, operation):
    target = tmp_path / ("file" + suffix)
    target.touch()
    preview = AsyncMock(return_value={"mode": "ready"})
    monkeypatch.setattr(routes, "preview_file", preview)
    monkeypatch.setattr(routes, "validate_asset_version", lambda *args: None)
    result = client.get("/editor/local/files/" + route, params={"path": str(target), **params})
    assert result.status_code == 200, result.text
    args = preview.call_args.args
    assert args[1] == target
    if operation:
        assert args[2] == operation


def test_local_assets_use_same_media_policy_and_version_validation(client, tmp_path):
    target = tmp_path / "sample.png"
    target.write_bytes(b"png contents")
    result = client.get("/editor/local/files/asset", params={"path": str(target)})
    assert result.status_code == 200
    assert result.content == b"png contents"
    assert result.headers["content-type"] == "image/png"
    rejected = client.get("/editor/local/files/asset", params={"path": str(target), "preview_version": "stale"})
    assert rejected.status_code == 409


def test_project_reference_cannot_escape_project_root(client, workspace):
    outside = workspace.parent / "outside.md"
    outside.write_text("outside", encoding="utf-8")
    response = resolve(client, "../outside.md", source="project_file", project_id="owner")
    assert response.status_code == 400
    assert resolve(client, outside).status_code == 200


def test_external_database_uses_shared_read_only_worker(tmp_path):
    import sqlite3
    from app.api.routes.editor_database import router
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router)
    target = tmp_path / "外部.sqlite"
    with sqlite3.connect(target) as conn:
        conn.execute("create table samples(value text)")
        conn.execute("insert into samples values ('正文')")
    with TestClient(app) as client:
        result = client.get("/editor/local/databases/overview", params={"path": str(target)})
        assert result.status_code == 200, result.text
        assert result.json()["tables_count"] == 1
        result = client.get("/editor/local/databases/table-data", params={"path": str(target), "object_name": "samples"})
        assert result.status_code == 200, result.text
        assert result.json()["rows"][0][0]["value"] == "正文"
        result = client.post("/editor/local/databases/query", json={"path": str(target), "sql": "delete from samples"})
        assert result.status_code == 400, result.text
    with sqlite3.connect(target) as conn:
        assert conn.execute("select count(*) from samples").fetchone()[0] == 1
