from __future__ import annotations

import asyncio
from dataclasses import dataclass
from functools import lru_cache
import re
from threading import Lock
from time import monotonic
from typing import Any
from uuid import uuid4

from app.core.errors import BadRequestError, ConflictError, NotFoundError
from app.domain.project import Project, ProjectKind
from app.infra.git_repository import GitRepositoryAdapter, GitRepositoryError
from app.infra.git_repository.adapter import GitIdentity
from app.infra.github import get_github_client, normalize_github_repository_source
from app.repositories.project import ProjectRepository, get_project_repository
from app.schemas.git_repository import GitRepositoryToolRequest


_BRANCH_PATTERN = re.compile(r"^(?![./])(?!.*(?:\.\.|//|@\{|\\|\s))[A-Za-z0-9._/-]{1,250}(?<![./])$")
_REMOTE_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
_PLAN_TTL_SECONDS = 600


@dataclass(frozen=True, slots=True)
class _GitPlan:
    plan_id: str
    project_id: str
    action: str
    fingerprint: str
    arguments: dict[str, Any]
    expires_at: float


class GitRepositoryService:
    def __init__(self, project_repository: ProjectRepository) -> None:
        self._projects = project_repository
        self._plans: dict[str, _GitPlan] = {}
        self._plan_lock = Lock()

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
            if action == "overview":
                return self._result(action, project, await asyncio.to_thread(adapter.overview))
            if action == "status":
                return self._result(action, project, await asyncio.to_thread(adapter.status))
            if action == "diff":
                diff = await asyncio.to_thread(
                    adapter.diff,
                    staged=payload.staged,
                    paths=payload.paths,
                )
                return self._result(action, project, {"diff": diff, "staged": payload.staged})
            if action == "log":
                commits = await asyncio.to_thread(adapter.log, limit=payload.limit)
                return self._result(action, project, {"commits": commits})
            if action == "show_commit":
                revision = self._required(payload.revision, "show_commit 必须提供 revision。")
                commit = await asyncio.to_thread(adapter.show_commit, revision)
                return self._result(action, project, {"commit": commit})
            if action == "init":
                branch = self._branch(payload.branch or "main")
                data = await asyncio.to_thread(adapter.init, branch=branch)
                return self._result(action, project, data)
            if action == "connect_remote":
                repository = self._repository_url(payload.repository)
                remote = self._remote(payload.remote)
                data = await asyncio.to_thread(adapter.add_remote, name=remote, url=repository)
                return self._result(action, project, data)
            if action == "disconnect_remote":
                remote = self._remote(payload.remote)
                data = await asyncio.to_thread(adapter.remove_remote, name=remote)
                return self._result(action, project, data)
            if action == "fetch":
                token = await self._access_token(fallback_token)
                data = await asyncio.to_thread(
                    adapter.fetch,
                    remote=self._remote(payload.remote),
                    token=token,
                )
                return self._result(action, project, data)
            if action == "create_branch":
                branch = self._branch(self._required(payload.branch, "create_branch 必须提供 branch。"))
                data = await asyncio.to_thread(adapter.create_branch, branch=branch)
                return self._result(action, project, data)
            if action == "switch_branch":
                branch = self._branch(self._required(payload.branch, "switch_branch 必须提供 branch。"))
                data = await asyncio.to_thread(adapter.switch_branch, branch=branch)
                return self._result(action, project, data)
            if action.startswith("plan_"):
                return await self._create_plan(action, payload, project, adapter, fallback_token)
            return await self._apply_plan(action, payload, project, adapter, fallback_token)
        except GitRepositoryError as exc:
            raise BadRequestError(str(exc)) from exc

    async def _create_plan(
        self,
        action: str,
        payload: GitRepositoryToolRequest,
        project: Project,
        adapter: GitRepositoryAdapter,
        fallback_token: str | None,
    ) -> dict[str, Any]:
        apply_action = action.removeprefix("plan_")
        arguments: dict[str, Any]
        preview: dict[str, Any]
        if apply_action == "commit":
            message = self._required(payload.message, "plan_commit 必须提供 message。")
            status = await asyncio.to_thread(adapter.status)
            selected = self._select_changes(status["changes"], payload.paths)
            if not selected:
                raise BadRequestError("没有可提交的改动。")
            arguments = {"message": message, "paths": payload.paths}
            preview = {"message": message, "changes": selected}
        elif apply_action == "push":
            token = await self._access_token(fallback_token)
            comparison = await asyncio.to_thread(
                adapter.fetch,
                remote=self._remote(payload.remote),
                token=token,
            )
            if comparison.get("diverged"):
                raise ConflictError("本地与远端已经分叉，当前版本不会自动合并或强制推送。")
            arguments = {
                "remote": self._remote(payload.remote),
                "branch": self._branch(payload.branch or comparison.get("branch") or "main"),
            }
            preview = comparison
        elif apply_action == "pull":
            token = await self._access_token(fallback_token)
            comparison = await asyncio.to_thread(
                adapter.fetch,
                remote=self._remote(payload.remote),
                token=token,
            )
            status = await asyncio.to_thread(adapter.status)
            if not status["clean"]:
                raise ConflictError("当前项目还有未提交改动，不能创建拉取计划。")
            if comparison.get("diverged") or comparison.get("ahead", 0) > 0:
                raise ConflictError("本地含有远端没有的提交，当前版本不会自动合并。")
            arguments = {
                "remote": self._remote(payload.remote),
                "branch": self._branch(payload.branch or comparison.get("branch") or "main"),
            }
            preview = comparison
        elif apply_action == "restore":
            paths = self._required_paths(payload.paths, "plan_restore 必须提供 paths。")
            status = await asyncio.to_thread(adapter.status)
            selected = self._select_changes(status["changes"], paths)
            if not selected:
                raise BadRequestError("指定文件没有可放弃的工作区改动。")
            if any(item["state"].startswith("staged-") for item in selected):
                raise ConflictError("指定文件含有已暂存改动；当前恢复操作只处理未暂存文件。")
            arguments = {"paths": paths}
            preview = {"changes": selected}
        elif apply_action == "revert":
            revision = self._required(payload.revision, "plan_revert 必须提供 revision。")
            status = await asyncio.to_thread(adapter.status)
            if not status["clean"]:
                raise ConflictError("当前项目还有未提交改动，不能撤销历史提交。")
            commit = await asyncio.to_thread(adapter.show_commit, revision)
            arguments = {"revision": revision}
            preview = {"commit": commit}
        else:
            raise BadRequestError(f"不支持的计划操作：{action}")

        fingerprint = await asyncio.to_thread(adapter.fingerprint)
        plan = _GitPlan(
            plan_id=uuid4().hex,
            project_id=project.project_id,
            action=apply_action,
            fingerprint=fingerprint,
            arguments=arguments,
            expires_at=monotonic() + _PLAN_TTL_SECONDS,
        )
        with self._plan_lock:
            self._prune_plans_locked()
            self._plans[plan.plan_id] = plan
        return self._result(
            action,
            project,
            {"plan": {"planId": plan.plan_id, "action": apply_action, **preview}},
        )

    async def _apply_plan(
        self,
        action: str,
        payload: GitRepositoryToolRequest,
        project: Project,
        adapter: GitRepositoryAdapter,
        fallback_token: str | None,
    ) -> dict[str, Any]:
        plan_id = self._required(payload.plan_id, f"{action} 必须提供 planId。")
        with self._plan_lock:
            self._prune_plans_locked()
            plan = self._plans.pop(plan_id, None)
        if plan is None:
            raise ConflictError("Git 操作计划不存在或已经过期，请重新检查。")
        if plan.project_id != project.project_id or plan.action != action:
            raise ConflictError("Git 操作计划与当前项目或操作不匹配。")
        current_fingerprint = await asyncio.to_thread(adapter.fingerprint)
        if current_fingerprint != plan.fingerprint:
            raise ConflictError("项目状态已经变化，请重新检查后再执行。")

        data: dict[str, Any]
        if action == "commit":
            identity = await self._identity(fallback_token)
            sha = await asyncio.to_thread(
                adapter.commit,
                message=plan.arguments["message"],
                paths=plan.arguments["paths"],
                identity=identity,
            )
            data = {"commitSha": sha}
        elif action == "push":
            token = await self._access_token(fallback_token)
            data = await asyncio.to_thread(
                adapter.push,
                remote=plan.arguments["remote"],
                branch=plan.arguments["branch"],
                token=token,
            )
        elif action == "pull":
            token = await self._access_token(fallback_token)
            data = await asyncio.to_thread(
                adapter.pull,
                remote=plan.arguments["remote"],
                branch=plan.arguments["branch"],
                token=token,
            )
        elif action == "restore":
            data = await asyncio.to_thread(adapter.restore, paths=plan.arguments["paths"])
        elif action == "revert":
            identity = await self._identity(fallback_token)
            sha = await asyncio.to_thread(
                adapter.revert,
                revision=plan.arguments["revision"],
                identity=identity,
            )
            data = {"commitSha": sha}
        else:
            raise BadRequestError(f"不支持的 Git 操作：{action}")
        return self._result(action, project, data)

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
    def _remote(value: str) -> str:
        normalized = value.strip()
        if not _REMOTE_PATTERN.fullmatch(normalized):
            raise BadRequestError("Git 远端名称无效。")
        return normalized

    @staticmethod
    def _result(action: str, project: Project, data: dict[str, Any]) -> dict[str, Any]:
        return {
            "ok": True,
            "action": action,
            "project": {"id": project.project_id, "name": project.name},
            **data,
        }

    def _prune_plans_locked(self) -> None:
        now = monotonic()
        for plan_id, plan in tuple(self._plans.items()):
            if plan.expires_at <= now:
                self._plans.pop(plan_id, None)


@lru_cache
def get_git_repository_service() -> GitRepositoryService:
    return GitRepositoryService(get_project_repository())
