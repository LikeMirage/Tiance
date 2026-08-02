from __future__ import annotations

from functools import lru_cache
import mimetypes
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

from app.core.errors import BadRequestError, NotFoundError
from app.infra.github import GithubApiError, GithubClient, get_github_client
from app.infra.github.client import GithubRepositorySource, parse_github_repository_source
from app.repositories.project import ProjectRepository, get_project_repository


_TOOLS = {
    "github_repository",
    "github_pull_request",
    "github_issue",
    "github_release",
    "github_actions",
}
_MUTATIONS = {
    "github_repository": {
        "create_repository", "update_repository", "fork_repository", "delete_repository",
    },
    "github_pull_request": {
        "create", "update", "comment", "review", "merge", "update_branch",
    },
    "github_issue": {
        "create", "update", "comment", "set_labels", "add_assignees",
        "remove_assignees", "create_label", "delete_label",
    },
    "github_release": {"create", "update", "delete", "upload_asset", "delete_asset"},
    "github_actions": {"dispatch", "rerun", "rerun_failed", "cancel", "delete_run"},
}
_ALLOWED = {
    "github_repository": _MUTATIONS["github_repository"] | {"list_repositories", "get_repository"},
    "github_pull_request": _MUTATIONS["github_pull_request"] | {
        "list", "get", "compare", "list_reviews", "list_comments", "list_files",
    },
    "github_issue": _MUTATIONS["github_issue"] | {"list", "get", "list_comments", "list_labels"},
    "github_release": _MUTATIONS["github_release"] | {"list", "get", "list_assets"},
    "github_actions": _MUTATIONS["github_actions"] | {
        "list_workflows", "list_runs", "get_run", "list_jobs", "get_job_logs",
    },
}
_MAX_RELEASE_ASSET_BYTES = 2 * 1024 * 1024 * 1024
_MAX_ACTION_LOG_BYTES = 32 * 1024 * 1024


class GithubPlatformService:
    def __init__(self, client: GithubClient, projects: ProjectRepository) -> None:
        self._github = client
        self._projects = projects

    async def execute(
        self,
        *,
        tool_name: str,
        project_id: str | None,
        action: str,
        dry_run: bool,
        parameters: dict[str, Any],
        fallback_token: str | None,
    ) -> dict[str, Any]:
        if tool_name not in _TOOLS:
            raise BadRequestError("当前工具不能调用 GitHub 平台能力。")
        normalized_action = action.strip().lower()
        if normalized_action not in _ALLOWED[tool_name]:
            raise BadRequestError(f"{tool_name} 不支持操作：{action}")
        if len(parameters) > 40:
            raise BadRequestError("GitHub 工具参数过多。")
        token = await self._access_token(fallback_token)
        try:
            if dry_run and normalized_action in _MUTATIONS[tool_name]:
                self._validate_mutation(tool_name, normalized_action, parameters, project_id)
                preview = await self._preview(tool_name, normalized_action, parameters, token)
                return self._result(tool_name, normalized_action, True, preview)
            data = await self._dispatch(
                tool_name,
                normalized_action,
                parameters,
                token,
                project_id=project_id,
            )
            return self._result(tool_name, normalized_action, False, data)
        except GithubApiError as exc:
            raise BadRequestError(str(exc)) from exc

    async def _dispatch(
        self,
        tool: str,
        action: str,
        p: dict[str, Any],
        token: str,
        *,
        project_id: str | None,
    ) -> dict[str, Any]:
        if tool == "github_repository":
            return await self._repository(action, p, token)
        repository = self._repository_source(p)
        if tool == "github_pull_request":
            return await self._pull_request(repository, action, p, token)
        if tool == "github_issue":
            return await self._issue(repository, action, p, token)
        if tool == "github_release":
            return await self._release(repository, action, p, token, project_id)
        return await self._actions(repository, action, p, token)

    async def _preview(
        self,
        tool: str,
        action: str,
        p: dict[str, Any],
        token: str,
    ) -> dict[str, Any]:
        preview: dict[str, Any] = {
            "simulated": True,
            "wouldExecute": action,
            "parameters": _public_parameters(p),
        }
        repository_value = p.get("repository")
        if isinstance(repository_value, str) and repository_value.strip():
            repository = self._repository_source(p)
            try:
                current = await self._github.request_json(
                    "GET", self._repo_path(repository), access_token=token,
                )
                preview["repositoryState"] = _repository_summary(current)
            except GithubApiError as exc:
                if exc.status_code != 404:
                    raise
                preview["repositoryState"] = None
        if tool == "github_pull_request" and action in {"merge", "update", "review", "comment", "update_branch"}:
            repository = self._repository_source(p)
            number = self._positive_int(p, "number")
            pull = await self._github.request_json(
                "GET", f"{self._repo_path(repository)}/pulls/{number}", access_token=token,
            )
            preview["pullRequest"] = _pull_summary(pull)
        if tool == "github_issue" and action in {"update", "comment", "set_labels", "add_assignees", "remove_assignees"}:
            repository = self._repository_source(p)
            number = self._positive_int(p, "number")
            issue = await self._github.request_json(
                "GET", f"{self._repo_path(repository)}/issues/{number}", access_token=token,
            )
            preview["issue"] = _issue_summary(issue)
        if tool == "github_release" and action in {"update", "delete", "upload_asset"}:
            repository = self._repository_source(p)
            release_id = self._positive_int(p, "releaseId")
            release = await self._github.request_json(
                "GET", f"{self._repo_path(repository)}/releases/{release_id}", access_token=token,
            )
            preview["release"] = _release_summary(release)
        return preview

    async def _repository(self, action: str, p: dict[str, Any], token: str) -> dict[str, Any]:
        if action == "list_repositories":
            items = await self._github.list_repositories_for_sync(access_token=token)
            return {"repositories": [_repository_summary(item) for item in items]}
        if action == "get_repository":
            repository = self._repository_source(p)
            payload = await self._github.request_json("GET", self._repo_path(repository), access_token=token)
            return {"repository": payload}
        if action == "create_repository":
            body = _pick(p, {
                "name", "description", "homepage", "private", "visibility", "has_issues",
                "has_projects", "has_wiki", "is_template", "auto_init", "gitignore_template",
                "license_template", "allow_squash_merge", "allow_merge_commit", "allow_rebase_merge",
                "allow_auto_merge", "delete_branch_on_merge",
            })
            name = self._required_string(body, "name")
            body["name"] = name
            owner = _optional_string(p.get("organization"))
            path = f"/orgs/{quote(owner, safe='')}/repos" if owner else "/user/repos"
            created = await self._github.request_json("POST", path, access_token=token, json_body=body)
            return {"repository": created}
        repository = self._repository_source(p)
        if action == "update_repository":
            body = _pick(p, {
                "name", "description", "homepage", "private", "visibility", "has_issues",
                "has_projects", "has_wiki", "is_template", "default_branch", "allow_squash_merge",
                "allow_merge_commit", "allow_rebase_merge", "allow_auto_merge", "delete_branch_on_merge",
                "archived", "security_and_analysis",
            })
            if not body:
                raise BadRequestError("update_repository 没有可更新字段。")
            updated = await self._github.request_json(
                "PATCH", self._repo_path(repository), access_token=token, json_body=body,
            )
            return {"repository": updated}
        if action == "fork_repository":
            body = _pick(p, {"organization", "name", "default_branch_only"})
            fork = await self._github.request_json(
                "POST", f"{self._repo_path(repository)}/forks", access_token=token, json_body=body,
            )
            return {"repository": fork}
        await self._github.request_json("DELETE", self._repo_path(repository), access_token=token)
        return {"deleted": repository.canonical_url}

    async def _pull_request(
        self, repository: GithubRepositorySource, action: str, p: dict[str, Any], token: str,
    ) -> dict[str, Any]:
        base = f"{self._repo_path(repository)}/pulls"
        if action == "list":
            query = urlencode(_pick(p, {"state", "head", "base", "sort", "direction", "per_page", "page"}))
            items = await self._github.request_json_list("GET", f"{base}?{query}" if query else base, access_token=token)
            return {"pullRequests": items}
        if action == "compare":
            base_ref = quote(self._required_string(p, "base"), safe="")
            head_ref = quote(self._required_string(p, "head"), safe="")
            data = await self._github.request_json(
                "GET", f"{self._repo_path(repository)}/compare/{base_ref}...{head_ref}", access_token=token,
            )
            return {"comparison": data}
        number = self._positive_int(p, "number") if action not in {"create"} else None
        path = f"{base}/{number}" if number is not None else base
        if action == "get":
            return {"pullRequest": await self._github.request_json("GET", path, access_token=token)}
        if action == "list_reviews":
            return {"reviews": await self._github.request_json_list("GET", f"{path}/reviews", access_token=token)}
        if action == "list_comments":
            return {"comments": await self._github.request_json_list("GET", f"{self._repo_path(repository)}/issues/{number}/comments", access_token=token)}
        if action == "list_files":
            return {"files": await self._github.request_json_list("GET", f"{path}/files", access_token=token)}
        if action == "create":
            body = _pick(p, {"title", "head", "head_repo", "base", "body", "draft", "maintainer_can_modify"})
            for key in ("title", "head", "base"):
                body[key] = self._required_string(body, key)
            return {"pullRequest": await self._github.request_json("POST", base, access_token=token, json_body=body)}
        if action == "update":
            body = _pick(p, {"title", "body", "state", "base", "maintainer_can_modify"})
            return {"pullRequest": await self._github.request_json("PATCH", path, access_token=token, json_body=body)}
        if action == "comment":
            body = {"body": self._required_string(p, "body")}
            comment = await self._github.request_json(
                "POST", f"{self._repo_path(repository)}/issues/{number}/comments", access_token=token, json_body=body,
            )
            return {"comment": comment}
        if action == "review":
            body = _pick(p, {"body", "event", "comments", "commit_id"})
            body["event"] = self._required_string(body, "event").upper()
            review = await self._github.request_json("POST", f"{path}/reviews", access_token=token, json_body=body)
            return {"review": review}
        if action == "merge":
            body = _pick(p, {"commit_title", "commit_message", "sha", "merge_method"})
            merged = await self._github.request_json("PUT", f"{path}/merge", access_token=token, json_body=body)
            return {"merge": merged}
        body = _pick(p, {"expected_head_sha"})
        result = await self._github.request_json("PUT", f"{path}/update-branch", access_token=token, json_body=body)
        return {"update": result}

    async def _issue(
        self, repository: GithubRepositorySource, action: str, p: dict[str, Any], token: str,
    ) -> dict[str, Any]:
        base = f"{self._repo_path(repository)}/issues"
        if action == "list":
            query = urlencode(_pick(p, {"milestone", "state", "assignee", "creator", "mentioned", "labels", "sort", "direction", "since", "per_page", "page"}))
            return {"issues": await self._github.request_json_list("GET", f"{base}?{query}" if query else base, access_token=token)}
        if action == "list_labels":
            return {"labels": await self._github.request_json_list("GET", f"{self._repo_path(repository)}/labels", access_token=token)}
        if action == "create_label":
            body = _pick(p, {"name", "color", "description"})
            body["name"] = self._required_string(body, "name")
            body["color"] = self._required_string(body, "color").removeprefix("#")
            return {"label": await self._github.request_json("POST", f"{self._repo_path(repository)}/labels", access_token=token, json_body=body)}
        if action == "delete_label":
            name = quote(self._required_string(p, "name"), safe="")
            await self._github.request_json("DELETE", f"{self._repo_path(repository)}/labels/{name}", access_token=token)
            return {"deleted": p["name"]}
        if action == "create":
            body = _pick(p, {"title", "body", "assignees", "milestone", "labels", "type"})
            body["title"] = self._required_string(body, "title")
            return {"issue": await self._github.request_json("POST", base, access_token=token, json_body=body)}
        number = self._positive_int(p, "number")
        path = f"{base}/{number}"
        if action == "get":
            return {"issue": await self._github.request_json("GET", path, access_token=token)}
        if action == "list_comments":
            return {"comments": await self._github.request_json_list("GET", f"{path}/comments", access_token=token)}
        if action == "update":
            body = _pick(p, {"title", "body", "assignees", "milestone", "labels", "state", "state_reason", "type"})
            return {"issue": await self._github.request_json("PATCH", path, access_token=token, json_body=body)}
        if action == "comment":
            body = {"body": self._required_string(p, "body")}
            return {"comment": await self._github.request_json("POST", f"{path}/comments", access_token=token, json_body=body)}
        if action == "set_labels":
            body = {"labels": _string_list(p.get("labels"), "labels")}
            return {"labels": await self._github.request_json_list("POST", f"{path}/labels", access_token=token, json_body=body)}
        if action == "add_assignees":
            body = {"assignees": _string_list(p.get("assignees"), "assignees")}
            return {"issue": await self._github.request_json("POST", f"{path}/assignees", access_token=token, json_body=body)}
        body = {"assignees": _string_list(p.get("assignees"), "assignees")}
        return {"issue": await self._github.request_json("DELETE", f"{path}/assignees", access_token=token, json_body=body)}

    async def _release(
        self, repository: GithubRepositorySource, action: str, p: dict[str, Any], token: str, project_id: str | None,
    ) -> dict[str, Any]:
        base = f"{self._repo_path(repository)}/releases"
        if action == "list":
            return {"releases": await self._github.request_json_list("GET", base, access_token=token)}
        if action == "create":
            body = _pick(p, {"tag_name", "target_commitish", "name", "body", "draft", "prerelease", "generate_release_notes", "make_latest"})
            body["tag_name"] = self._required_string(body, "tag_name")
            return {"release": await self._github.request_json("POST", base, access_token=token, json_body=body)}
        if action == "delete_asset":
            asset_id = self._positive_int(p, "assetId")
            await self._github.request_json("DELETE", f"{self._repo_path(repository)}/releases/assets/{asset_id}", access_token=token)
            return {"deletedAsset": asset_id}
        release_id = self._positive_int(p, "releaseId")
        path = f"{base}/{release_id}"
        if action == "get":
            return {"release": await self._github.request_json("GET", path, access_token=token)}
        if action == "list_assets":
            return {"assets": await self._github.request_json_list("GET", f"{path}/assets", access_token=token)}
        if action == "update":
            body = _pick(p, {"tag_name", "target_commitish", "name", "body", "draft", "prerelease", "make_latest"})
            return {"release": await self._github.request_json("PATCH", path, access_token=token, json_body=body)}
        if action == "delete":
            await self._github.request_json("DELETE", path, access_token=token)
            return {"deleted": release_id}
        source = self._project_file(project_id, self._required_string(p, "path"))
        name = _optional_string(p.get("name")) or source.name
        content_type = _optional_string(p.get("contentType")) or mimetypes.guess_type(name)[0] or "application/octet-stream"
        asset = await self._github.upload_release_asset(
            repository,
            release_id,
            name=name,
            content_type=content_type,
            source=source,
            maximum_bytes=_MAX_RELEASE_ASSET_BYTES,
            access_token=token,
        )
        return {"asset": asset}

    async def _actions(
        self, repository: GithubRepositorySource, action: str, p: dict[str, Any], token: str,
    ) -> dict[str, Any]:
        root = f"{self._repo_path(repository)}/actions"
        if action == "list_workflows":
            return {"workflows": (await self._github.request_json("GET", f"{root}/workflows", access_token=token)).get("workflows", [])}
        if action == "list_runs":
            query = urlencode(_pick(p, {"actor", "branch", "event", "status", "per_page", "page", "created", "exclude_pull_requests", "check_suite_id", "head_sha"}))
            data = await self._github.request_json("GET", f"{root}/runs?{query}" if query else f"{root}/runs", access_token=token)
            return {"workflowRuns": data.get("workflow_runs", [])}
        if action == "dispatch":
            workflow = quote(self._required_string(p, "workflowId"), safe="")
            body = {"ref": self._required_string(p, "ref"), "inputs": p.get("inputs") or {}}
            await self._github.request_json("POST", f"{root}/workflows/{workflow}/dispatches", access_token=token, json_body=body)
            return {"dispatched": workflow, "ref": body["ref"]}
        if action == "get_job_logs":
            job_id = self._positive_int(p, "jobId")
            content = await self._github.request_bytes(
                f"{root}/jobs/{job_id}/logs",
                access_token=token,
                maximum_bytes=_MAX_ACTION_LOG_BYTES,
                accept="text/plain",
            )
            return {"jobId": job_id, "log": content.decode("utf-8", errors="replace")}
        run_id = self._positive_int(p, "runId")
        run_path = f"{root}/runs/{run_id}"
        if action == "get_run":
            return {"workflowRun": await self._github.request_json("GET", run_path, access_token=token)}
        if action == "list_jobs":
            data = await self._github.request_json("GET", f"{run_path}/jobs", access_token=token)
            return {"jobs": data.get("jobs", [])}
        suffix = {
            "rerun": "/rerun",
            "rerun_failed": "/rerun-failed-jobs",
            "cancel": "/cancel",
        }.get(action)
        if suffix:
            await self._github.request_json("POST", run_path + suffix, access_token=token, json_body={})
            return {"runId": run_id, "requested": action}
        await self._github.request_json("DELETE", run_path, access_token=token)
        return {"deletedRun": run_id}

    def _validate_mutation(
        self,
        tool: str,
        action: str,
        p: dict[str, Any],
        project_id: str | None,
    ) -> None:
        if tool == "github_repository":
            if action == "create_repository":
                self._required_string(p, "name")
            else:
                self._repository_source(p)
            if action == "update_repository" and not _pick(p, {
                "name", "description", "homepage", "private", "visibility", "has_issues",
                "has_projects", "has_wiki", "is_template", "default_branch", "allow_squash_merge",
                "allow_merge_commit", "allow_rebase_merge", "allow_auto_merge", "delete_branch_on_merge",
                "archived", "security_and_analysis",
            }):
                raise BadRequestError("update_repository 没有可更新字段。")
            return
        self._repository_source(p)
        if tool == "github_pull_request":
            if action == "create":
                for key in ("title", "head", "base"):
                    self._required_string(p, key)
            else:
                self._positive_int(p, "number")
            if action == "comment":
                self._required_string(p, "body")
            if action == "review":
                self._required_string(p, "event")
            return
        if tool == "github_issue":
            if action == "create":
                self._required_string(p, "title")
            elif action in {"create_label", "delete_label"}:
                self._required_string(p, "name")
                if action == "create_label":
                    self._required_string(p, "color")
            else:
                self._positive_int(p, "number")
            if action == "comment":
                self._required_string(p, "body")
            if action == "set_labels":
                _string_list(p.get("labels"), "labels")
            if action in {"add_assignees", "remove_assignees"}:
                _string_list(p.get("assignees"), "assignees")
            return
        if tool == "github_release":
            if action == "create":
                self._required_string(p, "tag_name")
            elif action == "delete_asset":
                self._positive_int(p, "assetId")
            else:
                self._positive_int(p, "releaseId")
            if action == "upload_asset":
                source = self._project_file(project_id, self._required_string(p, "path"))
                if source.stat().st_size > _MAX_RELEASE_ASSET_BYTES:
                    raise BadRequestError("Release 附件超过允许大小。")
            return
        if action == "dispatch":
            self._required_string(p, "workflowId")
            self._required_string(p, "ref")
        else:
            self._positive_int(p, "runId")

    async def _access_token(self, fallback_token: str | None) -> str:
        token = await self._github.get_valid_access_token(required=False)
        if token:
            return token
        fallback = (fallback_token or "").strip()
        if fallback:
            return fallback
        raise BadRequestError("请先在设定集中登录 GitHub，或在工具高级配置中提供 Token。")

    def _project_file(self, project_id: str | None, relative_path: str) -> Path:
        normalized = (project_id or "").strip()
        if not normalized:
            raise BadRequestError("当前会话没有关联项目，无法读取 Release 附件。")
        project = self._projects.get_project(normalized)
        if project is None:
            raise NotFoundError("当前项目不存在或已经移除。")
        root = Path(project.root_path).expanduser().resolve(strict=False)
        candidate = (root / relative_path).resolve(strict=False)
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise BadRequestError("Release 附件必须位于当前项目内。") from exc
        if not candidate.is_file():
            raise NotFoundError("Release 附件不存在。")
        return candidate

    @staticmethod
    def _repository_source(p: dict[str, Any]) -> GithubRepositorySource:
        raw = _optional_string(p.get("repository"))
        source = parse_github_repository_source(raw or "")
        if source is None and raw and raw.count("/") == 1:
            owner, repository = raw.split("/", 1)
            candidate = parse_github_repository_source(
                f"https://github.com/{owner}/{repository}"
            )
            source = candidate
        if source is None:
            raise BadRequestError("repository 必须是 owner/name 或有效的 GitHub 仓库地址。")
        return source

    @staticmethod
    def _repo_path(repository: GithubRepositorySource) -> str:
        return f"/repos/{quote(repository.owner, safe='')}/{quote(repository.repository, safe='')}"

    @staticmethod
    def _required_string(p: dict[str, Any], key: str) -> str:
        value = _optional_string(p.get(key))
        if not value:
            raise BadRequestError(f"{key} 不能为空。")
        return value

    @staticmethod
    def _positive_int(p: dict[str, Any], key: str) -> int:
        value = p.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise BadRequestError(f"{key} 必须是正整数。")
        return value

    @staticmethod
    def _result(tool: str, action: str, dry_run: bool, data: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "tool": tool, "action": action, "dryRun": dry_run, **data}


def _pick(source: dict[str, Any], names: set[str]) -> dict[str, Any]:
    return {key: value for key, value in source.items() if key in names and value is not None}


def _optional_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _string_list(value: Any, key: str) -> list[str]:
    if not isinstance(value, list):
        raise BadRequestError(f"{key} 必须是字符串数组。")
    normalized = [item.strip() for item in value if isinstance(item, str) and item.strip()]
    if len(normalized) != len(value):
        raise BadRequestError(f"{key} 只能包含非空字符串。")
    return normalized


def _public_parameters(parameters: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in parameters.items() if "token" not in key.casefold()}


def _repository_summary(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item.get("id"),
        "fullName": item.get("full_name"),
        "private": item.get("private"),
        "visibility": item.get("visibility"),
        "defaultBranch": item.get("default_branch"),
        "htmlUrl": item.get("html_url"),
        "archived": item.get("archived"),
        "permissions": item.get("permissions"),
    }


def _pull_summary(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "number": item.get("number"),
        "title": item.get("title"),
        "state": item.get("state"),
        "draft": item.get("draft"),
        "mergeable": item.get("mergeable"),
        "mergeableState": item.get("mergeable_state"),
        "headSha": (item.get("head") or {}).get("sha") if isinstance(item.get("head"), dict) else None,
        "baseSha": (item.get("base") or {}).get("sha") if isinstance(item.get("base"), dict) else None,
        "htmlUrl": item.get("html_url"),
    }


def _issue_summary(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "number": item.get("number"),
        "title": item.get("title"),
        "state": item.get("state"),
        "updatedAt": item.get("updated_at"),
        "htmlUrl": item.get("html_url"),
    }


def _release_summary(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item.get("id"),
        "tagName": item.get("tag_name"),
        "name": item.get("name"),
        "draft": item.get("draft"),
        "prerelease": item.get("prerelease"),
        "publishedAt": item.get("published_at"),
        "htmlUrl": item.get("html_url"),
        "assets": [
            {"id": asset.get("id"), "name": asset.get("name"), "size": asset.get("size")}
            for asset in item.get("assets", [])
            if isinstance(asset, dict)
        ],
    }


@lru_cache
def get_github_platform_service() -> GithubPlatformService:
    return GithubPlatformService(get_github_client(), get_project_repository())
