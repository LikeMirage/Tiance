from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import pytest

from app.core.config import Settings
from app.core.errors import ConflictError
from app.domain.github_sync import GithubSyncDirection
from app.domain.project import Project, ProjectKind
from app.repositories.github_sync_binding_repository import GithubSyncBindingRepository
from app.services.application.github_sync import GithubSyncService
from app.services.application.github_sync_snapshot import (
    GITHUB_SYNC_TOOL_ID,
    build_local_snapshot,
)
from app.services.tools.host_capability_access import (
    HostCapability,
    HostCapabilityAccessService,
)


class _Projects:
    def __init__(self, projects: tuple[Project, ...] = ()) -> None:
        self.projects = projects

    def list_projects(self):
        return self.projects

    def get_project(self, project_id: str):
        return next((item for item in self.projects if item.project_id == project_id), None)


class _Github:
    authorization_url = "https://github.com/settings/installations"

    def __init__(self) -> None:
        self.head_sha: str | None = None
        self.tree_sha: str | None = None
        self.remote: dict[str, tuple[str, bytes]] = {}
        self.created_blobs: dict[str, bytes] = {}
        self.published_commit: str | None = None
        self.initial_commit_sha: str | None = None

    async def get_valid_access_token(self, *, required: bool):
        return "login-token"

    async def list_repositories_for_sync(self, *, access_token: str):
        return [{
            "id": 1,
            "full_name": "LikeMirage/sync-test",
            "private": True,
            "default_branch": "main",
            "permissions": {"push": True},
        }]

    async def list_authorized_repositories(self):
        return await self.list_repositories_for_sync(access_token="login-token")

    async def get_repository_for_sync(self, _repository, *, access_token: str):
        return {"default_branch": "main", "permissions": {"push": True}}

    async def get_branch_snapshot(self, _repository, _branch: str, *, access_token: str):
        return self.head_sha, self.tree_sha, tuple(
            {"path": path, "type": "blob", "sha": sha, "size": len(content)}
            for path, (sha, content) in self.remote.items()
        )

    async def create_blob(self, _repository, content: bytes, *, access_token: str):
        sha = _git_sha(content)
        self.created_blobs[sha] = content
        return sha

    async def create_initial_file(
        self,
        _repository,
        *,
        path: str,
        content: bytes,
        branch: str,
        **_kwargs,
    ):
        sha = _git_sha(content)
        self.remote[path] = (sha, content)
        self.tree_sha = "tree-initial"
        self.initial_commit_sha = "commit-initial"
        return self.initial_commit_sha

    async def get_commit_snapshot(self, _repository, commit_sha: str, *, access_token: str):
        assert commit_sha == self.initial_commit_sha
        return commit_sha, self.tree_sha, tuple(
            {"path": path, "type": "blob", "sha": sha, "size": len(content)}
            for path, (sha, content) in self.remote.items()
        )

    async def create_tree(self, _repository, entries, *, base_tree_sha, access_token: str):
        for entry in entries:
            if entry["sha"] is None:
                self.remote.pop(entry["path"], None)
            else:
                content = self.created_blobs[entry["sha"]]
                self.remote[entry["path"]] = (entry["sha"], content)
        self.tree_sha = "tree-new"
        return self.tree_sha

    async def create_commit(self, _repository, **_kwargs):
        return "commit-new"

    async def publish_branch_commit(self, _repository, *, commit_sha: str, **_kwargs):
        self.head_sha = commit_sha
        self.published_commit = commit_sha

    async def fetch_blob(self, _repository, sha: str, *, access_token: str):
        return next(content for remote_sha, content in self.remote.values() if remote_sha == sha)


def test_github_sync_tool_receives_scoped_capability_without_model_context() -> None:
    access = HostCapabilityAccessService()
    grant = access.issue_grant(
        tool_name="github_repository_sync",
        tool_call_id="call-1",
        provider_id=None,
        model_id=None,
        project_id="project-1",
        session_id="session-1",
        lifetime_seconds=60,
    )
    assert grant is not None
    assert grant.capability is HostCapability.GITHUB_SYNC
    assert access.authorize(grant.token, HostCapability.GITHUB_SYNC) == grant


def test_project_snapshot_makes_external_project_portable(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    external_root = tmp_path / "external-project"
    external_root.mkdir()
    (external_root / "notes.md").write_text("portable", encoding="utf-8")
    settings.projects_data_path.mkdir(parents=True)
    (settings.projects_data_path / "catalog.json").write_text(json.dumps({
        "schema_version": 1,
        "metadata": {},
        "categories": [{
            "category_id": "category",
            "name": "项目",
            "is_default": True,
            "sort_order": 0,
            "created_at": "2026-08-02T00:00:00Z",
            "updated_at": "2026-08-02T00:00:00Z",
        }],
        "projects": [{
            "project_id": "project-a",
            "name": "外部项目",
            "category_id": "category",
            "root_path": str(external_root),
            "is_default": False,
            "sort_order": 0,
            "created_at": "2026-08-02T00:00:00Z",
            "updated_at": "2026-08-02T00:00:00Z",
        }],
    }), encoding="utf-8")
    project = Project(
        project_id="project-a",
        name="外部项目",
        root_path=str(external_root),
        category_id="category",
        project_kind=ProjectKind.PROJECT,
        is_default=False,
        sort_order=0,
        created_at="2026-08-02T00:00:00Z",
        updated_at="2026-08-02T00:00:00Z",
    )

    snapshot = build_local_snapshot(
        settings=settings,
        project_repository=_Projects((project,)),  # type: ignore[arg-type]
        collection=ProjectKind.PROJECT,
    )

    assert snapshot.files["project-a/notes.md"].read_bytes() == b"portable"
    catalog = json.loads(snapshot.files["catalog.json"].read_bytes())
    assert "root_path" not in catalog["projects"][0]


def test_project_snapshot_does_not_duplicate_internal_root_name(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    internal_root = settings.projects_data_path / "friendly-folder"
    internal_root.mkdir(parents=True)
    (internal_root / "notes.md").write_text("portable", encoding="utf-8")
    (settings.projects_data_path / "catalog.json").write_text(json.dumps({
        "schema_version": 1,
        "metadata": {},
        "categories": [],
        "projects": [{
            "project_id": "project-a",
            "name": "内部项目",
            "category_id": None,
            "root_path": str(internal_root),
            "root_name": "friendly-folder",
            "is_default": False,
            "sort_order": 0,
            "created_at": "2026-08-02T00:00:00Z",
            "updated_at": "2026-08-02T00:00:00Z",
        }],
    }), encoding="utf-8")
    project = Project(
        project_id="project-a",
        name="内部项目",
        root_path=str(internal_root),
        category_id=None,
        project_kind=ProjectKind.PROJECT,
        is_default=False,
        sort_order=0,
        created_at="2026-08-02T00:00:00Z",
        updated_at="2026-08-02T00:00:00Z",
    )

    snapshot = build_local_snapshot(
        settings=settings,
        project_repository=_Projects((project,)),  # type: ignore[arg-type]
        collection=ProjectKind.PROJECT,
    )

    assert "project-a/notes.md" in snapshot.files
    assert "friendly-folder/notes.md" not in snapshot.files


def test_tool_sync_snapshot_never_contains_its_token_config(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    config = settings.tools_data_path / GITHUB_SYNC_TOOL_ID / "program" / "config.json"
    config.parent.mkdir(parents=True)
    config.write_text('{"github_token":"secret"}', encoding="utf-8")
    (config.parent / "main.py").write_text("print('ok')", encoding="utf-8")

    snapshot = build_local_snapshot(
        settings=settings,
        project_repository=_Projects(),  # type: ignore[arg-type]
        collection=ProjectKind.TOOL,
    )

    assert f"{GITHUB_SYNC_TOOL_ID}/program/config.json" not in snapshot.files
    assert f"{GITHUB_SYNC_TOOL_ID}/program/main.py" in snapshot.files


def test_sync_snapshot_ignores_office_lock_files(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    settings.themes_data_path.mkdir(parents=True)
    (settings.themes_data_path / "theme.json").write_text("content", encoding="utf-8")
    (settings.themes_data_path / "~$theme.docx").write_text("lock", encoding="utf-8")

    snapshot = build_local_snapshot(
        settings=settings,
        project_repository=_Projects(),  # type: ignore[arg-type]
        collection=ProjectKind.THEME,
    )

    assert "theme.json" in snapshot.files
    assert "~$theme.docx" not in snapshot.files


def test_sync_snapshot_ignores_local_cache_directories(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    settings.themes_data_path.mkdir(parents=True)
    (settings.themes_data_path / "theme.json").write_text("content", encoding="utf-8")
    cache_file = settings.themes_data_path / ".cache" / "generated.bin"
    cache_file.parent.mkdir()
    cache_file.write_bytes(b"cache")

    snapshot = build_local_snapshot(
        settings=settings,
        project_repository=_Projects(),  # type: ignore[arg-type]
        collection=ProjectKind.THEME,
    )

    assert "theme.json" in snapshot.files
    assert ".cache/generated.bin" not in snapshot.files


def test_push_requires_fresh_plan_and_publishes_atomic_commit(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    settings.themes_data_path.mkdir(parents=True)
    theme_file = settings.themes_data_path / "theme.json"
    theme_file.write_text('{"name":"theme"}', encoding="utf-8")
    github = _Github()
    bindings = GithubSyncBindingRepository(tmp_path / "secrets" / "sync.json")
    service = GithubSyncService(
        settings=settings,
        github_client=github,  # type: ignore[arg-type]
        binding_repository=bindings,
        project_repository=_Projects(),  # type: ignore[arg-type]
    )

    async def run():
        await service.save_binding(
            collection=ProjectKind.THEME,
            repository="LikeMirage/sync-test",
            branch="main",
            remote_path="themes",
        )
        plan = await service.create_plan(
            collection=ProjectKind.THEME,
            direction=GithubSyncDirection.PUSH,
        )
        result = await service.apply_plan(plan.plan_id, commit_message="sync themes")
        return plan, result

    plan, (_applied, commit_sha) = asyncio.run(run())

    assert [change.path for change in plan.changes] == ["theme.json"]
    assert commit_sha == "commit-new"
    assert github.published_commit == "commit-new"
    assert github.initial_commit_sha == "commit-initial"
    assert github.remote["themes/theme.json"][1] == b'{"name":"theme"}'


def test_plan_stops_when_local_files_change(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    settings.themes_data_path.mkdir(parents=True)
    theme_file = settings.themes_data_path / "theme.json"
    theme_file.write_text("first", encoding="utf-8")
    github = _Github()
    service = GithubSyncService(
        settings=settings,
        github_client=github,  # type: ignore[arg-type]
        binding_repository=GithubSyncBindingRepository(tmp_path / "sync.json"),
        project_repository=_Projects(),  # type: ignore[arg-type]
    )

    async def run():
        await service.save_binding(
            collection=ProjectKind.THEME,
            repository="LikeMirage/sync-test",
            branch="main",
            remote_path="",
        )
        plan = await service.create_plan(
            collection=ProjectKind.THEME,
            direction=GithubSyncDirection.PUSH,
        )
        theme_file.write_text("second", encoding="utf-8")
        await service.apply_plan(plan.plan_id)

    with pytest.raises(ConflictError, match="本地文件已经改变"):
        asyncio.run(run())


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        database_file=str(tmp_path / "db" / "tiance.db"),
        projects_data_dir=str(tmp_path / "projects"),
        tools_data_dir=str(tmp_path / "tools"),
        knowledge_data_dir=str(tmp_path / "knowledge"),
        experience_data_dir=str(tmp_path / "experience"),
        roles_data_dir=str(tmp_path / "roles"),
        themes_data_dir=str(tmp_path / "themes"),
        providers_data_dir=str(tmp_path / "providers"),
    )


def _git_sha(content: bytes) -> str:
    return hashlib.sha1(
        f"blob {len(content)}\0".encode("ascii") + content,
        usedforsecurity=False,
    ).hexdigest()
