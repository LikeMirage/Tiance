from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import datetime, timezone
from functools import lru_cache
import os
from pathlib import Path
import re
import shutil
from tempfile import TemporaryDirectory
from time import monotonic
from uuid import uuid4

from app.core.atomic_replace import atomic_replace_path
from app.core.config import Settings, get_settings
from app.core.errors import BadRequestError, ConflictError, NotFoundError
from app.domain.github_sync import (
    GithubSyncBinding,
    GithubSyncChange,
    GithubSyncChangeKind,
    GithubSyncDirection,
    GithubSyncFile,
    GithubSyncPlan,
)
from app.domain.project import ProjectKind
from app.infra.github import GithubApiError, GithubClient, get_github_client
from app.infra.github.client import parse_github_repository_source
from app.repositories.github_sync_binding_repository import GithubSyncBindingRepository
from app.repositories.project import ProjectRepository, get_project_repository
from app.services.application.github_project_sync import (
    CATALOG_PATH,
    build_board,
    catalog_bytes,
    local_project_target,
    merge_local_catalog_for_pull,
    merge_portable_catalog,
    parse_catalog,
    project_ids_from_paths,
    remote_with_catalog,
    with_catalog,
)
from app.services.application.github_sync_snapshot import (
    LocalSnapshot,
    build_local_snapshot,
    collection_root,
    join_remote_path,
    normalize_remote_path,
    require_safe_relative_path,
    strip_remote_path,
)


PLAN_LIFETIME_SECONDS = 10 * 60
_BRANCH_PATTERN = re.compile(r"^(?!/)(?!.*(?:\.\.|//|@\{|\\))[A-Za-z0-9._/-]{1,250}(?<![/.])$")


class GithubSyncService:
    def __init__(
        self,
        *,
        settings: Settings,
        github_client: GithubClient,
        binding_repository: GithubSyncBindingRepository,
        project_repository: ProjectRepository,
    ) -> None:
        self._settings = settings
        self._github = github_client
        self._bindings = binding_repository
        self._projects = project_repository
        self._plans: dict[str, GithubSyncPlan] = {}
        self._locks = {kind: asyncio.Lock() for kind in ProjectKind}

    async def overview(
        self,
        *,
        collection: ProjectKind,
        fallback_token: str | None = None,
    ) -> tuple[bool, GithubSyncBinding | None, list[dict], str]:
        login_token = await self._github.get_valid_access_token(required=False)
        normalized_fallback = (fallback_token or "").strip()
        if login_token:
            try:
                raw_items = await self._github.list_authorized_repositories()
            except GithubApiError as exc:
                raise BadRequestError(str(exc)) from exc
            repositories = self._normalize_repositories(raw_items)
        elif normalized_fallback:
            repositories = await self._list_repositories(normalized_fallback)
        else:
            return False, self._bindings.get_binding(collection), [], self._github.authorization_url
        return True, self._bindings.get_binding(collection), repositories, self._github.authorization_url

    async def save_binding(
        self,
        *,
        collection: ProjectKind,
        repository: str,
        branch: str,
        remote_path: str,
        fallback_token: str | None = None,
    ) -> GithubSyncBinding:
        source = _parse_repository(repository)
        normalized_branch = _normalize_branch(branch)
        normalized_remote_path = normalize_remote_path(remote_path)
        token = await self._resolve_access_token(fallback_token=fallback_token, required=True)
        try:
            await self._github.get_repository_for_sync(source, access_token=token)
        except GithubApiError as exc:
            raise BadRequestError(str(exc)) from exc
        return self._bindings.save_binding(
            collection=collection,
            repository=source.canonical_url,
            branch=normalized_branch,
            remote_path=normalized_remote_path,
        )

    def delete_binding(self, collection: ProjectKind) -> None:
        self._bindings.delete_binding(collection)

    async def create_plan(
        self,
        *,
        collection: ProjectKind,
        direction: GithubSyncDirection,
        paths: list[str] | None = None,
        project_ids: list[str] | None = None,
        fallback_token: str | None = None,
    ) -> GithubSyncPlan:
        binding = self._require_binding(collection)
        token = await self._resolve_access_token(fallback_token=fallback_token, required=True)
        async with self._locks[collection]:
            # 集合可能包含大量项目文件。文件遍历和哈希不能占用 FastAPI 的
            # 主事件循环，否则桌面端会表现为所有按钮同时卡死。
            local, remote_snapshot = await asyncio.gather(
                asyncio.to_thread(self._local_snapshot, collection),
                self._remote_snapshot(binding, token),
            )
            remote_head, _remote_tree, remote = remote_snapshot
            selected_paths = _normalize_selected_paths(paths)
            selected_project_ids = _normalize_project_ids(project_ids)
            catalog_content: bytes | None = None
            if collection is ProjectKind.PROJECT:
                (
                    local,
                    remote,
                    selected_project_ids,
                    catalog_content,
                ) = await self._prepare_project_state(
                    local=local,
                    remote=remote,
                    binding=binding,
                    access_token=token,
                    direction=direction,
                    selected_paths=selected_paths,
                    selected_project_ids=selected_project_ids,
                )
            elif selected_project_ids is not None:
                raise BadRequestError("projectIds 只适用于项目集同步。")
            changes = _filter_changes(
                _compare_snapshots(local, remote, direction=direction),
                selected_paths=selected_paths,
                selected_project_ids=selected_project_ids,
                include_catalog=collection is ProjectKind.PROJECT,
            )
            now = monotonic()
            plan = GithubSyncPlan(
                plan_id=uuid4().hex,
                collection=collection,
                direction=direction,
                binding=binding,
                local_fingerprint=local.fingerprint,
                remote_head_sha=remote_head,
                changes=changes,
                selected_paths=selected_paths,
                selected_project_ids=selected_project_ids,
                catalog_content=catalog_content,
                created_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                expires_at=now + PLAN_LIFETIME_SECONDS,
            )
            self._prune_plans(now)
            self._plans[plan.plan_id] = plan
            return plan

    async def apply_plan(
        self,
        plan_id: str,
        *,
        commit_message: str | None = None,
        fallback_token: str | None = None,
        expected_direction: GithubSyncDirection | None = None,
    ) -> tuple[GithubSyncPlan, str | None]:
        plan = self._plans.get(plan_id.strip())
        if plan is None or plan.expires_at <= monotonic():
            self._plans.pop(plan_id.strip(), None)
            raise ConflictError("同步计划不存在或已过期，请重新检查差异。")
        if expected_direction is not None and plan.direction is not expected_direction:
            raise ConflictError("同步计划方向与当前操作不一致，请重新检查差异。")
        token = await self._resolve_access_token(fallback_token=fallback_token, required=True)
        async with self._locks[plan.collection]:
            current_binding = self._require_binding(plan.collection)
            if current_binding != plan.binding:
                raise ConflictError("仓库绑定已经改变，请重新检查差异。")
            local, remote_snapshot = await asyncio.gather(
                asyncio.to_thread(self._local_snapshot, plan.collection),
                self._remote_snapshot(plan.binding, token),
            )
            if local.fingerprint != plan.local_fingerprint:
                raise ConflictError("本地文件已经改变，请重新检查差异。")
            remote_head, remote_tree, remote = remote_snapshot
            if remote_head != plan.remote_head_sha:
                raise ConflictError("远端仓库已经出现新提交，请重新检查差异。")
            catalog_content: bytes | None = None
            if plan.collection is ProjectKind.PROJECT:
                local, remote, _project_ids, catalog_content = await self._prepare_project_state(
                    local=local,
                    remote=remote,
                    binding=plan.binding,
                    access_token=token,
                    direction=plan.direction,
                    selected_paths=plan.selected_paths,
                    selected_project_ids=plan.selected_project_ids,
                )
            current_changes = _filter_changes(
                _compare_snapshots(local, remote, direction=plan.direction),
                selected_paths=plan.selected_paths,
                selected_project_ids=plan.selected_project_ids,
                include_catalog=plan.collection is ProjectKind.PROJECT,
            )
            if current_changes != plan.changes:
                raise ConflictError("同步差异已经改变，请重新生成计划。")
            if catalog_content != plan.catalog_content:
                raise ConflictError("项目索引已经改变，请重新生成计划。")
            if not plan.changes:
                self._plans.pop(plan.plan_id, None)
                return plan, remote_head
            if plan.direction is GithubSyncDirection.PUSH:
                commit_sha = await self._apply_push(
                    plan,
                    local=local,
                    remote_tree_sha=remote_tree,
                    access_token=token,
                    commit_message=commit_message,
                )
            else:
                await self._apply_pull(plan, remote=remote, access_token=token)
                commit_sha = remote_head
            self._plans.pop(plan.plan_id, None)
            return plan, commit_sha

    def resolve_tool_collection(
        self,
        *,
        explicit: ProjectKind | None,
        project_id: str | None,
    ) -> ProjectKind:
        inferred: ProjectKind | None = None
        if project_id:
            project = self._projects.get_project(project_id)
            inferred = project.project_kind if project is not None else None
        if explicit is not None and inferred is not None and explicit is not inferred:
            raise BadRequestError("指定集合与当前工作区类型不一致。")
        if explicit is not None:
            return explicit
        if inferred is not None:
            return inferred
        raise BadRequestError("无法判断要同步的集合，请明确指定 collection。")

    def get_binding(self, collection: ProjectKind) -> GithubSyncBinding | None:
        return self._bindings.get_binding(collection)

    async def get_project_board(self) -> tuple[GithubSyncBinding, str | None, list[dict], list[dict], int]:
        binding = self._require_binding(ProjectKind.PROJECT)
        token = await self._resolve_access_token(fallback_token=None, required=True)
        async with self._locks[ProjectKind.PROJECT]:
            local, remote_snapshot = await asyncio.gather(
                asyncio.to_thread(self._local_snapshot, ProjectKind.PROJECT),
                self._remote_snapshot(binding, token),
            )
            remote_head, _remote_tree, remote = remote_snapshot
            local_catalog = parse_catalog(
                local.files.get(CATALOG_PATH).read_bytes() if CATALOG_PATH in local.files else None,
                label="本地项目集",
            )
            remote_catalog = await self._read_remote_catalog(
                binding=binding,
                remote=remote,
                access_token=token,
            )
            categories, projects, changed_files = build_board(
                local=local,
                remote=remote,
                local_catalog=local_catalog,
                remote_catalog=remote_catalog,
            )
            return binding, remote_head, categories, projects, changed_files

    async def _prepare_project_state(
        self,
        *,
        local: LocalSnapshot,
        remote: dict[str, GithubSyncFile],
        binding: GithubSyncBinding,
        access_token: str,
        direction: GithubSyncDirection,
        selected_paths: tuple[str, ...] | None,
        selected_project_ids: tuple[str, ...] | None,
    ) -> tuple[LocalSnapshot, dict[str, GithubSyncFile], tuple[str, ...], bytes]:
        local_catalog = parse_catalog(
            local.files.get(CATALOG_PATH).read_bytes() if CATALOG_PATH in local.files else None,
            label="本地项目集",
        )
        remote_catalog = await self._read_remote_catalog(
            binding=binding,
            remote=remote,
            access_token=access_token,
        )
        project_ids = selected_project_ids
        if project_ids is None and selected_paths is not None:
            project_ids = project_ids_from_paths(selected_paths)
        if project_ids is None:
            project_ids = tuple(sorted(
                _catalog_project_ids(local_catalog)
                | _catalog_project_ids(remote_catalog)
                | set(project_ids_from_paths(set(local.files) | set(remote)))
            ))
        portable = merge_portable_catalog(
            local=local_catalog,
            remote=remote_catalog,
            selected_project_ids=project_ids,
            direction=direction.value,
        )
        portable_content = catalog_bytes(portable)
        if direction is GithubSyncDirection.PUSH:
            return with_catalog(local, portable_content), remote, project_ids, portable_content

        raw_local = _read_raw_catalog(collection_root(self._settings, ProjectKind.PROJECT))
        local_content = catalog_bytes(merge_local_catalog_for_pull(
            raw_local=raw_local,
            remote=remote_catalog,
            selected_project_ids=project_ids,
            projects_root=collection_root(self._settings, ProjectKind.PROJECT),
        ))
        return local, remote_with_catalog(remote, portable_content), project_ids, local_content

    async def _read_remote_catalog(
        self,
        *,
        binding: GithubSyncBinding,
        remote: dict[str, GithubSyncFile],
        access_token: str,
    ) -> dict:
        remote_file = remote.get(CATALOG_PATH)
        if remote_file is None:
            return parse_catalog(None, label="远端项目集")
        repository = _parse_repository(binding.repository)
        content = await self._github.fetch_blob(
            repository,
            remote_file.sha,
            access_token=access_token,
        )
        return parse_catalog(content, label="远端项目集")

    async def _apply_push(
        self,
        plan: GithubSyncPlan,
        *,
        local: LocalSnapshot,
        remote_tree_sha: str | None,
        access_token: str,
        commit_message: str | None,
    ) -> str:
        repository = _parse_repository(plan.binding.repository)
        repository_payload = await self._github.get_repository_for_sync(
            repository,
            access_token=access_token,
        )
        permissions = repository_payload.get("permissions")
        if not isinstance(permissions, dict) or permissions.get("push") is not True:
            raise BadRequestError("当前 GitHub 授权对该仓库没有提交权限。")

        parent_sha = plan.remote_head_sha
        base_tree_sha = remote_tree_sha
        initialization_path: str | None = None
        if parent_sha is None:
            default_branch = repository_payload.get("default_branch")
            if not isinstance(default_branch, str) or not default_branch:
                raise BadRequestError("GitHub 仓库没有有效的默认分支。")
            if default_branch != plan.binding.branch:
                raise BadRequestError(
                    f"空仓库第一次同步必须使用默认分支 {default_branch}。"
                )
            initialization_path = _initialization_path(plan.binding.remote_path, local)
            initialization_commit_sha = await self._github.create_initial_file(
                repository,
                path=initialization_path,
                content=b"Tiance repository sync initialization.\n",
                message="初始化天策仓库同步",
                branch=plan.binding.branch,
                access_token=access_token,
            )
            parent_sha, base_tree_sha, _entries = await self._github.get_commit_snapshot(
                repository,
                initialization_commit_sha,
                access_token=access_token,
            )
            if parent_sha is None or base_tree_sha is None:
                raise ConflictError("GitHub 空仓库初始化后仍无法读取，请重新检查差异。")

        tree_entries: list[dict] = []
        if initialization_path is not None:
            tree_entries.append({
                "path": initialization_path,
                "mode": "100644",
                "type": "blob",
                "sha": None,
            })
        for change in plan.changes:
            repository_path = join_remote_path(plan.binding.remote_path, change.path)
            if change.kind is GithubSyncChangeKind.DELETE:
                tree_entries.append({"path": repository_path, "mode": "100644", "type": "blob", "sha": None})
                continue
            local_file = local.files[change.path]
            blob_sha = await self._github.create_blob(
                repository,
                local_file.read_bytes(),
                access_token=access_token,
            )
            tree_entries.append({
                "path": repository_path,
                "mode": "100644",
                "type": "blob",
                "sha": blob_sha,
            })
        tree_sha = await self._github.create_tree(
            repository,
            tree_entries,
            base_tree_sha=base_tree_sha,
            access_token=access_token,
        )
        message = (commit_message or "同步天策集合数据").strip()
        if not message:
            message = "同步天策集合数据"
        commit_sha = await self._github.create_commit(
            repository,
            message=message,
            tree_sha=tree_sha,
            parent_sha=parent_sha,
            access_token=access_token,
        )
        try:
            await self._github.publish_branch_commit(
                repository,
                branch=plan.binding.branch,
                commit_sha=commit_sha,
                branch_exists=True,
                access_token=access_token,
            )
        except GithubApiError as exc:
            if exc.status_code in {409, 422}:
                raise ConflictError("远端分支已改变，提交未覆盖远端，请重新检查差异。") from exc
            raise BadRequestError(str(exc)) from exc
        return commit_sha

    async def _apply_pull(
        self,
        plan: GithubSyncPlan,
        *,
        remote: dict[str, GithubSyncFile],
        access_token: str,
    ) -> None:
        repository = _parse_repository(plan.binding.repository)
        root = collection_root(self._settings, plan.collection)
        root.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix="tiance-github-sync-") as temporary_name:
            temporary_root = Path(temporary_name)
            staged_root = temporary_root / "staged"
            backup_root = temporary_root / "backup"
            created_paths: list[Path] = []
            backed_up: list[tuple[Path, Path]] = []

            for change in plan.changes:
                if change.kind is GithubSyncChangeKind.DELETE:
                    continue
                if change.path == CATALOG_PATH and plan.catalog_content is not None:
                    content = plan.catalog_content
                else:
                    remote_file = remote[change.path]
                    content = await self._github.fetch_blob(
                        repository,
                        remote_file.sha,
                        access_token=access_token,
                    )
                staged = staged_root.joinpath(*Path(change.path).parts)
                staged.parent.mkdir(parents=True, exist_ok=True)
                staged.write_bytes(content)

            try:
                for change in plan.changes:
                    target = self._local_target(plan.collection, root, change.path)
                    if target.exists():
                        backup = backup_root.joinpath(*Path(change.path).parts)
                        backup.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(target, backup)
                        backed_up.append((target, backup))
                    elif change.kind is not GithubSyncChangeKind.DELETE:
                        created_paths.append(target)

                for change in plan.changes:
                    target = self._local_target(plan.collection, root, change.path)
                    if change.kind is GithubSyncChangeKind.DELETE:
                        target.unlink(missing_ok=True)
                        continue
                    staged = staged_root.joinpath(*Path(change.path).parts)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    temporary_target = target.with_name(f".{target.name}.{uuid4().hex}.sync")
                    shutil.copy2(staged, temporary_target)
                    atomic_replace_path(temporary_target, target)
            except Exception:
                for target in reversed(created_paths):
                    with suppress(OSError):
                        target.unlink(missing_ok=True)
                for target, backup in reversed(backed_up):
                    with suppress(OSError):
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(backup, target)
                raise
        _remove_empty_directories(root)

    def _local_target(self, collection: ProjectKind, root: Path, path: str) -> Path:
        if collection is ProjectKind.PROJECT:
            return local_project_target(
                projects_root=root,
                project_repository=self._projects,
                logical_path=path,
            )
        return _safe_local_target(root, path)

    async def _remote_snapshot(
        self,
        binding: GithubSyncBinding,
        access_token: str,
    ) -> tuple[str | None, str | None, dict[str, GithubSyncFile]]:
        repository = _parse_repository(binding.repository)
        try:
            head_sha, tree_sha, entries = await self._github.get_branch_snapshot(
                repository,
                binding.branch,
                access_token=access_token,
            )
        except GithubApiError as exc:
            raise BadRequestError(str(exc)) from exc
        files: dict[str, GithubSyncFile] = {}
        for entry in entries:
            repository_path = entry.get("path")
            sha = entry.get("sha")
            size = entry.get("size")
            if not isinstance(repository_path, str) or not isinstance(sha, str):
                continue
            local_path = strip_remote_path(binding.remote_path, repository_path)
            if local_path is None:
                continue
            safe_path = require_safe_relative_path(local_path)
            if safe_path.startswith(".tiance-sync-init"):
                continue
            files[safe_path] = GithubSyncFile(
                path=safe_path,
                sha=sha,
                size=size if isinstance(size, int) and size >= 0 else 0,
            )
        return head_sha, tree_sha, files

    async def _resolve_access_token(
        self,
        *,
        fallback_token: str | None,
        required: bool,
    ) -> str | None:
        token = await self._github.get_valid_access_token(required=False)
        if token:
            return token
        normalized_fallback = (fallback_token or "").strip()
        if normalized_fallback:
            return normalized_fallback
        if required:
            raise BadRequestError(
                "请先在设定集中登录 GitHub，或在 GitHub 仓库同步工具的 config.json 中配置 Token。"
            )
        return None

    async def _list_repositories(self, access_token: str) -> list[dict]:
        try:
            raw_items = await self._github.list_repositories_for_sync(access_token=access_token)
        except GithubApiError as exc:
            raise BadRequestError(str(exc)) from exc
        return self._normalize_repositories(raw_items)

    def _normalize_repositories(self, raw_items: list[dict]) -> list[dict]:
        repositories: list[dict] = []
        for item in raw_items:
            repository_id = item.get("id")
            full_name = item.get("full_name")
            if not isinstance(repository_id, int) or not isinstance(full_name, str):
                continue
            permissions = item.get("permissions")
            repositories.append({
                "id": repository_id,
                "fullName": full_name,
                "private": bool(item.get("private")),
                "defaultBranch": str(item.get("default_branch") or "main"),
                "canPush": bool(isinstance(permissions, dict) and permissions.get("push") is True),
            })
        return repositories

    def _local_snapshot(self, collection: ProjectKind) -> LocalSnapshot:
        return build_local_snapshot(
            settings=self._settings,
            project_repository=self._projects,
            collection=collection,
        )

    def _require_binding(self, collection: ProjectKind) -> GithubSyncBinding:
        binding = self._bindings.get_binding(collection)
        if binding is None:
            raise NotFoundError("当前集合尚未绑定 GitHub 仓库。")
        return binding

    def _prune_plans(self, now: float) -> None:
        for plan_id, plan in tuple(self._plans.items()):
            if plan.expires_at <= now:
                self._plans.pop(plan_id, None)


def _compare_snapshots(
    local: LocalSnapshot,
    remote: dict[str, GithubSyncFile],
    *,
    direction: GithubSyncDirection,
) -> tuple[GithubSyncChange, ...]:
    changes: list[GithubSyncChange] = []
    all_paths = sorted(set(local.files) | set(remote))
    for path in all_paths:
        local_file = local.files.get(path)
        remote_file = remote.get(path)
        if local_file is not None and remote_file is not None and local_file.sha == remote_file.sha:
            continue
        if direction is GithubSyncDirection.PUSH:
            if local_file is None:
                kind, size = GithubSyncChangeKind.DELETE, 0
            elif remote_file is None:
                kind, size = GithubSyncChangeKind.ADD, local_file.size
            else:
                kind, size = GithubSyncChangeKind.UPDATE, local_file.size
        else:
            if remote_file is None:
                kind, size = GithubSyncChangeKind.DELETE, 0
            elif local_file is None:
                kind, size = GithubSyncChangeKind.ADD, remote_file.size
            else:
                kind, size = GithubSyncChangeKind.UPDATE, remote_file.size
        changes.append(GithubSyncChange(path=path, kind=kind, size=size))
    return tuple(changes)


def _normalize_selected_paths(paths: list[str] | None) -> tuple[str, ...] | None:
    if paths is None:
        return None
    return tuple(sorted({require_safe_relative_path(path) for path in paths}))


def _normalize_project_ids(project_ids: list[str] | None) -> tuple[str, ...] | None:
    if project_ids is None:
        return None
    normalized: set[str] = set()
    for project_id in project_ids:
        value = project_id.strip()
        if not value or "/" in value or "\\" in value or value in {".", ".."}:
            raise BadRequestError("项目同步范围包含无效项目 ID。")
        normalized.add(value)
    return tuple(sorted(normalized))


def _filter_changes(
    changes: tuple[GithubSyncChange, ...],
    *,
    selected_paths: tuple[str, ...] | None,
    selected_project_ids: tuple[str, ...] | None,
    include_catalog: bool,
) -> tuple[GithubSyncChange, ...]:
    if selected_paths is None and selected_project_ids is None:
        return changes
    exact_paths = set(selected_paths or ())
    project_prefixes = (
        tuple(f"{project_id}/" for project_id in selected_project_ids or ())
        if selected_paths is None
        else ()
    )
    return tuple(
        change for change in changes
        if (include_catalog and change.path == CATALOG_PATH)
        or change.path in exact_paths
        or any(change.path.startswith(prefix) for prefix in project_prefixes)
    )


def _catalog_project_ids(catalog: dict) -> set[str]:
    return {
        item["project_id"]
        for item in catalog.get("projects", [])
        if isinstance(item, dict) and isinstance(item.get("project_id"), str)
    }


def _read_raw_catalog(root: Path) -> dict:
    try:
        return parse_catalog((root / CATALOG_PATH).read_bytes(), label="本地项目集")
    except FileNotFoundError:
        return parse_catalog(None, label="本地项目集")


def _parse_repository(value: str):
    normalized = value.strip()
    if "://" not in normalized:
        normalized = f"https://github.com/{normalized.strip('/')}"
    repository = parse_github_repository_source(normalized)
    if repository is None:
        raise BadRequestError("GitHub 仓库地址无效。")
    return repository


def _normalize_branch(value: str) -> str:
    normalized = value.strip()
    if not _BRANCH_PATTERN.fullmatch(normalized) or normalized.endswith(".lock"):
        raise BadRequestError("GitHub 分支名称无效。")
    return normalized


def _initialization_path(remote_path: str, local: LocalSnapshot) -> str:
    for suffix in ("", f"-{uuid4().hex}"):
        filename = f".tiance-sync-init{suffix}"
        logical_path = filename
        if logical_path not in local.files:
            return join_remote_path(remote_path, logical_path)
    raise RuntimeError("无法生成 GitHub 空仓库初始化路径。")


def _safe_local_target(root: Path, relative_path: str) -> Path:
    safe_path = require_safe_relative_path(relative_path)
    target = root.joinpath(*safe_path.split("/")).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise BadRequestError("同步文件路径越过集合根目录。") from exc
    if target.is_symlink():
        raise BadRequestError("同步目标不能是符号链接。")
    return target


def _remove_empty_directories(root: Path) -> None:
    for directory in sorted(
        (path for path in root.rglob("*") if path.is_dir() and not path.is_symlink()),
        key=lambda path: len(path.parts),
        reverse=True,
    ):
        with suppress(OSError):
            directory.rmdir()


@lru_cache
def get_github_sync_service() -> GithubSyncService:
    settings = get_settings()
    return GithubSyncService(
        settings=settings,
        github_client=get_github_client(),
        binding_repository=GithubSyncBindingRepository(
            settings.secrets_data_path / "github-sync-settings.json"
        ),
        project_repository=get_project_repository(),
    )
