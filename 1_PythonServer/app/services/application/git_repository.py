from __future__ import annotations

import asyncio
from functools import lru_cache
import re
from typing import Any

from app.core.errors import BadRequestError, ConflictError, NotFoundError
from app.domain.project import Project, ProjectKind
from app.infra.git_repository import GitRepositoryAdapter, GitRepositoryError
from app.infra.git_repository.adapter import GitIdentity
from app.infra.github import get_github_client, normalize_github_repository_source
from app.repositories.project import ProjectRepository, get_project_repository
from app.schemas.git_repository import GitRepositoryToolRequest


_BRANCH_PATTERN = re.compile(r"^(?![./])(?!.*(?:\.\.|//|@\{|\\|\s))[A-Za-z0-9._/-]{1,250}(?<![./])$")
_REMOTE_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
_TAG_PATTERN = re.compile(r"^(?![./])(?!.*(?:\.\.|//|@\{|\\|\s))[A-Za-z0-9._/-]{1,250}(?<![./])$")
_MUTATIONS = {
    "init", "connect_remote", "disconnect_remote", "create_branch", "switch_branch",
    "delete_branch", "create_tag", "delete_tag", "add_submodule", "update_submodules",
    "commit", "push", "pull", "restore", "revert", "reset",
}


class GitRepositoryService:
    def __init__(self, project_repository: ProjectRepository) -> None:
        self._projects = project_repository

    async def execute(
        self,
        payload: GitRepositoryToolRequest,
        *,
        project_id: str | None,
        fallback_token: str | None = None,
    ) -> dict[str, Any]:
        project = self._resolve_project(project_id)
        adapter = GitRepositoryAdapter(self._project_root(project))
        action = payload.action
        try:
            if payload.dry_run and action in _MUTATIONS:
                preview = await self._preview(action, payload, adapter, fallback_token)
                return self._result(action, project, {"dryRun": True, "preview": preview})
            data = await self._execute(action, payload, adapter, fallback_token)
            return self._result(action, project, {"dryRun": False, **data})
        except GitRepositoryError as exc:
            raise BadRequestError(str(exc)) from exc

    async def _execute(
        self,
        action: str,
        payload: GitRepositoryToolRequest,
        adapter: GitRepositoryAdapter,
        fallback_token: str | None,
    ) -> dict[str, Any]:
        if action == "overview":
            return await asyncio.to_thread(adapter.overview)
        if action == "status":
            return await asyncio.to_thread(adapter.status)
        if action == "diff":
            diff = await asyncio.to_thread(adapter.diff, staged=payload.staged, paths=payload.paths)
            return {"diff": diff, "staged": payload.staged}
        if action == "log":
            return {"commits": await asyncio.to_thread(adapter.log, limit=payload.limit)}
        if action == "show_commit":
            revision = self._required(payload.revision, "show_commit 必须提供 revision。")
            return {"commit": await asyncio.to_thread(adapter.show_commit, revision)}
        if action == "init":
            return await asyncio.to_thread(adapter.init, branch=self._branch(payload.branch or "main"))
        if action == "connect_remote":
            return await asyncio.to_thread(
                adapter.add_remote,
                name=self._remote(payload.remote),
                url=self._repository_url(payload.repository),
            )
        if action == "disconnect_remote":
            return await asyncio.to_thread(adapter.remove_remote, name=self._remote(payload.remote))
        if action == "fetch":
            token = await self._access_token(fallback_token)
            return await asyncio.to_thread(adapter.fetch, remote=self._remote(payload.remote), token=token)
        if action == "create_branch":
            branch = self._branch(self._required(payload.branch, "create_branch 必须提供 branch。"))
            return await asyncio.to_thread(adapter.create_branch, branch=branch)
        if action == "switch_branch":
            branch = self._branch(self._required(payload.branch, "switch_branch 必须提供 branch。"))
            return await asyncio.to_thread(adapter.switch_branch, branch=branch)
        if action == "delete_branch":
            branch = self._branch(self._required(payload.branch, "delete_branch 必须提供 branch。"))
            return await asyncio.to_thread(adapter.delete_branch, branch=branch)
        if action == "list_tags":
            return {"tags": await asyncio.to_thread(adapter.list_tags)}
        if action == "create_tag":
            tag = self._tag(self._required(payload.tag, "create_tag 必须提供 tag。"))
            return {"tags": await asyncio.to_thread(adapter.create_tag, tag=tag, revision=payload.revision or "HEAD")}
        if action == "delete_tag":
            tag = self._tag(self._required(payload.tag, "delete_tag 必须提供 tag。"))
            return {"tags": await asyncio.to_thread(adapter.delete_tag, tag=tag)}
        if action == "list_submodules":
            return {"submodules": await asyncio.to_thread(adapter.list_submodules)}
        if action == "add_submodule":
            repository = self._repository_url(payload.repository)
            path = self._required(payload.submodule_path, "add_submodule 必须提供 submodulePath。")
            return {"submodules": await asyncio.to_thread(adapter.add_submodule, url=repository, path=path)}
        if action == "update_submodules":
            return {"submodules": await asyncio.to_thread(adapter.update_submodules, paths=payload.paths, force=payload.force)}
        if action == "commit":
            message = self._required(payload.message, "commit 必须提供 message。")
            status = await asyncio.to_thread(adapter.status)
            if not self._select_changes(status["changes"], payload.paths):
                raise BadRequestError("没有可提交的改动。")
            identity = await self._identity(fallback_token)
            sha = await asyncio.to_thread(adapter.commit, message=message, paths=payload.paths, identity=identity)
            return {"commitSha": sha}
        if action == "push":
            token = await self._access_token(fallback_token)
            overview = await asyncio.to_thread(adapter.overview)
            branch = self._branch(payload.branch or overview.get("branch") or "main")
            return await asyncio.to_thread(
                adapter.push,
                remote=self._remote(payload.remote),
                branch=branch,
                token=token,
                force=payload.force,
            )
        if action == "pull":
            token = await self._access_token(fallback_token)
            overview = await asyncio.to_thread(adapter.overview)
            branch = self._branch(payload.branch or overview.get("branch") or "main")
            return await asyncio.to_thread(adapter.pull, remote=self._remote(payload.remote), branch=branch, token=token)
        if action == "restore":
            paths = self._required_paths(payload.paths, "restore 必须提供 paths。")
            return await asyncio.to_thread(adapter.restore, paths=paths)
        if action == "revert":
            revision = self._required(payload.revision, "revert 必须提供 revision。")
            identity = await self._identity(fallback_token)
            return {"commitSha": await asyncio.to_thread(adapter.revert, revision=revision, identity=identity)}
        if action == "reset":
            revision = self._required(payload.revision, "reset 必须提供 revision。")
            return await asyncio.to_thread(adapter.reset, revision=revision, hard=payload.force)
        raise BadRequestError(f"不支持的 Git 操作：{action}")

    async def _preview(
        self,
        action: str,
        payload: GitRepositoryToolRequest,
        adapter: GitRepositoryAdapter,
        fallback_token: str | None,
    ) -> dict[str, Any]:
        overview = await asyncio.to_thread(adapter.overview)
        preview: dict[str, Any] = {"simulated": True, "wouldExecute": action, "repository": overview}
        if action == "commit":
            message = self._required(payload.message, "commit 必须提供 message。")
            status = await asyncio.to_thread(adapter.status)
            changes = self._select_changes(status["changes"], payload.paths)
            if not changes:
                raise BadRequestError("没有可提交的改动。")
            preview.update({"message": message, "changes": changes})
        elif action in {"push", "pull"}:
            comparison = await asyncio.to_thread(
                adapter.remote_comparison,
                remote=self._remote(payload.remote),
            )
            if action == "pull" and not overview.get("clean", True):
                raise ConflictError("当前项目还有未提交改动，不能拉取。")
            if action == "pull" and (comparison.get("diverged") or comparison.get("ahead", 0) > 0):
                raise ConflictError("本地含有远端没有的提交，不能快进拉取。")
            if action == "push" and comparison.get("diverged") and not payload.force:
                raise ConflictError("本地与远端已经分叉；若确认覆盖远端，请显式设置 force=true。")
            preview.update(comparison)
            preview["force"] = payload.force
            preview["comparisonBasis"] = "lastFetchedRemoteState"
        elif action in {"restore"}:
            paths = self._required_paths(payload.paths, "restore 必须提供 paths。")
            status = await asyncio.to_thread(adapter.status)
            changes = self._select_changes(status["changes"], paths)
            if not changes:
                raise BadRequestError("指定文件没有可恢复的改动。")
            preview["changes"] = changes
        elif action in {"revert", "reset"}:
            revision = self._required(payload.revision, f"{action} 必须提供 revision。")
            preview["commit"] = await asyncio.to_thread(adapter.show_commit, revision)
            preview["hard"] = payload.force if action == "reset" else None
        else:
            if action == "init":
                self._branch(payload.branch or "main")
                if overview.get("initialized"):
                    raise BadRequestError("当前项目已经是 Git 仓库。")
            elif action == "connect_remote":
                self._remote(payload.remote)
                self._repository_url(payload.repository)
            elif action == "disconnect_remote":
                remote = self._remote(payload.remote)
                if remote not in {item["name"] for item in overview.get("remotes", [])}:
                    raise BadRequestError(f"远端 {remote} 不存在。")
            elif action in {"create_branch", "switch_branch", "delete_branch"}:
                branch = self._branch(self._required(payload.branch, f"{action} 必须提供 branch。"))
                if action == "delete_branch" and branch == overview.get("branch"):
                    raise BadRequestError("不能删除当前正在使用的分支。")
            elif action in {"create_tag", "delete_tag"}:
                self._tag(self._required(payload.tag, f"{action} 必须提供 tag。"))
            elif action == "add_submodule":
                self._repository_url(payload.repository)
                self._required(payload.submodule_path, "add_submodule 必须提供 submodulePath。")
            preview.update({
                "remote": payload.remote,
                "repositoryUrl": payload.repository,
                "branch": payload.branch,
                "tag": payload.tag,
                "paths": payload.paths,
                "submodulePath": payload.submodule_path,
                "force": payload.force,
            })
        return preview

    def _resolve_project(self, project_id: str | None) -> Project:
        normalized = (project_id or "").strip()
        if not normalized:
            raise BadRequestError("当前会话没有关联项目，无法执行 Git 操作。")
        project = self._projects.get_project(normalized)
        if project is None:
            raise NotFoundError("当前项目不存在或已经移除。")
        if project.project_kind is not ProjectKind.PROJECT:
            raise BadRequestError("标准 Git 工具只操作普通项目；其他集请使用对应的仓库同步功能。")
        return project

    @staticmethod
    def _project_root(project: Project):
        from pathlib import Path

        root = Path(project.root_path).expanduser().resolve(strict=False)
        if not root.is_dir():
            raise NotFoundError("当前项目文件夹不存在。")
        return root

    async def _access_token(self, fallback_token: str | None) -> str:
        token = await get_github_client().get_valid_access_token(required=False)
        if token:
            return token
        fallback = (fallback_token or "").strip()
        if fallback:
            return fallback
        raise BadRequestError("请先在设定集中登录 GitHub，或在工具高级配置中提供 Token。")

    async def _identity(self, fallback_token: str | None) -> GitIdentity:
        try:
            token = await self._access_token(fallback_token)
            user = await get_github_client().get_authenticated_user_with_token(token)
        except Exception as exc:
            raise BadRequestError("提交前请先在设定集中登录 GitHub。") from exc
        login = str(user.get("login") or "").strip()
        name = str(user.get("name") or login).strip()
        if not login or not name:
            raise BadRequestError("GitHub 账号缺少可用的提交身份。")
        return GitIdentity(name=name, email=f"{login}@users.noreply.github.com")

    @staticmethod
    def _select_changes(changes: list[dict[str, str]], paths: list[str] | None) -> list[dict[str, str]]:
        if not paths:
            return changes
        normalized = {path.strip().replace("\\", "/").strip("/") for path in paths}
        return [item for item in changes if item["path"] in normalized]

    @staticmethod
    def _required(value: str | None, message: str) -> str:
        normalized = (value or "").strip()
        if not normalized:
            raise BadRequestError(message)
        return normalized

    @staticmethod
    def _required_paths(paths: list[str] | None, message: str) -> list[str]:
        if not paths:
            raise BadRequestError(message)
        return paths

    @staticmethod
    def _repository_url(value: str | None) -> str:
        normalized = normalize_github_repository_source((value or "").strip())
        if normalized is None:
            raise BadRequestError("仓库地址必须是有效的 GitHub HTTPS 仓库地址。")
        return normalized

    @staticmethod
    def _branch(value: str) -> str:
        normalized = value.strip()
        if not _BRANCH_PATTERN.fullmatch(normalized):
            raise BadRequestError("Git 分支名称无效。")
        return normalized

    @staticmethod
    def _tag(value: str) -> str:
        normalized = value.strip()
        if not _TAG_PATTERN.fullmatch(normalized):
            raise BadRequestError("Git 标签名称无效。")
        return normalized

    @staticmethod
    def _remote(value: str) -> str:
        normalized = value.strip()
        if not _REMOTE_PATTERN.fullmatch(normalized):
            raise BadRequestError("Git 远端名称无效。")
        return normalized

    @staticmethod
    def _result(action: str, project: Project, data: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "action": action, "project": {"id": project.project_id, "name": project.name}, **data}


@lru_cache
def get_git_repository_service() -> GitRepositoryService:
    return GitRepositoryService(get_project_repository())
