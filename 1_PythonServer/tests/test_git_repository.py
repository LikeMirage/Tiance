from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from dulwich import porcelain

from app.core.errors import BadRequestError
from app.domain.project import Project, ProjectKind
from app.infra.git_repository import GitRepositoryAdapter, GitRepositoryError
from app.infra.git_repository.adapter import GitIdentity
from app.schemas.git_repository import GitRepositoryToolRequest
from app.services.application.git_repository import GitRepositoryService
from app.services.tools.host_capability_access import (
    HostCapability,
    HostCapabilityAccessService,
)


IDENTITY = GitIdentity("Tiance Test", "tiance@example.com")


class _Projects:
    def __init__(self, project: Project) -> None:
        self.project = project

    def get_project(self, project_id: str):
        return self.project if project_id == self.project.project_id else None


def _project(root: Path, *, kind: ProjectKind = ProjectKind.PROJECT) -> Project:
    return Project(
        project_id="project-1",
        name="测试项目",
        root_path=str(root),
        category_id="category-1",
        project_kind=kind,
        is_default=False,
        sort_order=0,
        created_at="2026-08-03T00:00:00Z",
        updated_at="2026-08-03T00:00:00Z",
    )


def test_adapter_uses_standard_repository_and_local_remote(tmp_path: Path):
    root = tmp_path / "work"
    remote = tmp_path / "remote.git"
    root.mkdir()
    porcelain.init(remote, bare=True).close()
    adapter = GitRepositoryAdapter(root)

    initialized = adapter.init(branch="main")
    (root / "README.md").write_text("hello", encoding="utf-8")
    commit_sha = adapter.commit(message="initial", paths=None, identity=IDENTITY)
    adapter.add_remote(name="origin", url=str(remote))
    comparison = adapter.push(remote="origin", branch="main", token=None)

    assert initialized["initialized"] is True
    assert len(commit_sha) == 40
    assert comparison["ahead"] == 0
    assert comparison["behind"] == 0
    assert (root / ".git" / "config").is_file()


def test_adapter_status_diff_and_restore_are_scoped_to_project(tmp_path: Path):
    root = tmp_path / "work"
    root.mkdir()
    adapter = GitRepositoryAdapter(root)
    adapter.init(branch="main")
    (root / "tracked.txt").write_text("before\n", encoding="utf-8")
    adapter.commit(message="initial", paths=None, identity=IDENTITY)
    (root / "tracked.txt").write_text("after\n", encoding="utf-8")

    assert adapter.status()["changes"] == [{"path": "tracked.txt", "state": "modified"}]
    assert "+after" in adapter.diff(staged=False, paths=["tracked.txt"])
    adapter.restore(paths=["tracked.txt"])
    assert (root / "tracked.txt").read_text(encoding="utf-8") == "before\n"

    with pytest.raises(GitRepositoryError):
        adapter.restore(paths=["../outside.txt"])


def test_dry_run_restore_never_changes_project(tmp_path: Path):
    root = tmp_path / "work"
    root.mkdir()
    adapter = GitRepositoryAdapter(root)
    adapter.init(branch="main")
    (root / "tracked.txt").write_text("before", encoding="utf-8")
    adapter.commit(message="initial", paths=None, identity=IDENTITY)
    (root / "tracked.txt").write_text("first", encoding="utf-8")
    service = GitRepositoryService(_Projects(_project(root)))

    preview = asyncio.run(service.execute(
        GitRepositoryToolRequest(action="restore", paths=["tracked.txt"], dryRun=True),
        project_id="project-1",
    ))

    assert preview["dryRun"] is True
    assert preview["preview"]["changes"] == [{"path": "tracked.txt", "state": "modified"}]
    assert (root / "tracked.txt").read_text(encoding="utf-8") == "first"


def test_branch_and_tag_management(tmp_path: Path):
    root = tmp_path / "work"
    root.mkdir()
    adapter = GitRepositoryAdapter(root)
    adapter.init(branch="main")
    (root / "tracked.txt").write_text("before", encoding="utf-8")
    adapter.commit(message="initial", paths=None, identity=IDENTITY)

    adapter.create_branch(branch="topic")
    adapter.create_tag(tag="v1.0.0", revision="HEAD")
    assert adapter.list_tags() == ["v1.0.0"]
    adapter.delete_branch(branch="topic")
    adapter.delete_tag(tag="v1.0.0")
    assert adapter.list_tags() == []


def test_standard_git_tool_rejects_non_project_collection(tmp_path: Path):
    service = GitRepositoryService(_Projects(_project(tmp_path, kind=ProjectKind.TOOL)))

    with pytest.raises(BadRequestError):
        asyncio.run(service.execute(
            GitRepositoryToolRequest(action="overview"),
            project_id="project-1",
        ))


def test_git_tool_receives_only_its_own_host_capability():
    access = HostCapabilityAccessService()
    grant = access.issue_grant(
        tool_name="git_repository",
        tool_call_id="call-1",
        provider_id="provider-1",
        model_id="model-1",
        project_id="project-1",
        session_id="session-1",
        lifetime_seconds=60,
    )

    assert grant is not None
    assert access.authorize(grant.token, HostCapability.GIT_REPOSITORY) == grant
    assert access.authorize(grant.token, HostCapability.GITHUB_SYNC) is None
