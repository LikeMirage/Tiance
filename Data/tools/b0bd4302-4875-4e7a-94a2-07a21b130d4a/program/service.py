from __future__ import annotations

import os
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlsplit

from configuration import (
    ConfigurationError,
    GitIdentity,
    ToolConfiguration,
    authentication_summary,
    configure_repository_identity,
    redact_remote_url,
    resolve_credential,
    resolve_identity,
    validate_identity,
)
from git_adapter import GitRepositoryAdapter, GitRepositoryError


CONFIG_PATH = Path(__file__).with_name("config.json")
BRANCH_PATTERN = re.compile(r"^(?![./])(?!.*(?:\.\.|//|@\{|\\))[A-Za-z0-9._/-]{1,250}(?<![./])$")
TAG_PATTERN = re.compile(r"^(?![./])(?!.*(?:\.\.|//|@\{|\\))[A-Za-z0-9._/+\-]{1,250}(?<![./])$")
REMOTE_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
WRITE_ACTIONS = {
    "clone", "init", "connect_remote", "disconnect_remote", "fetch",
    "create_branch", "switch_branch", "delete_branch", "create_tag", "delete_tag",
    "add_submodule", "update_submodules", "configure_identity", "commit", "push",
    "pull", "restore", "revert", "reset",
}


class ToolError(Exception):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def execute(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        if not isinstance(payload, dict):
            raise ToolError("INVALID_ARGUMENT", "工具参数必须是对象。")
        action = _required(payload.get("action"), "action 不能为空。")
        root = _workspace_root()
        config = ToolConfiguration(CONFIG_PATH)
        adapter = GitRepositoryAdapter(root)
        dry_run = bool(payload.get("dry_run", False))

        if action in WRITE_ACTIONS and dry_run:
            data = _preview(action, payload, root, adapter, config)
            return _success(action, {"dryRun": True, "preview": data})

        data = _execute(action, payload, root, adapter, config)
        return _success(action, data)
    except ToolError as exc:
        return _failure(exc.code, exc.message, exc.details)
    except ConfigurationError as exc:
        return _failure("CONFIGURATION_ERROR", str(exc))
    except GitRepositoryError as exc:
        return _failure("GIT_OPERATION_FAILED", str(exc))
    except Exception as exc:
        return _failure("GIT_TOOL_FAILED", str(exc) or type(exc).__name__)


def _execute(
    action: str,
    payload: dict[str, Any],
    root: Path,
    adapter: GitRepositoryAdapter,
    config: ToolConfiguration,
) -> dict[str, Any]:
    if action == "overview":
        return _overview(adapter, config)
    if action == "status":
        return {"repository": adapter.status()}
    if action == "diff":
        return {
            "diff": adapter.diff(
                staged=bool(payload.get("staged", False)),
                paths=_paths(payload.get("paths")),
            ),
            "staged": bool(payload.get("staged", False)),
        }
    if action == "log":
        return {"commits": adapter.log(limit=_integer(payload.get("limit"), 30, 1, 100))}
    if action == "show_commit":
        return {"commit": adapter.show_commit(_required(payload.get("revision"), "show_commit 必须提供 revision。"))}
    if action == "clone":
        repository = _repository(payload.get("repository"))
        target = _clone_target(root, payload.get("target_path"), repository)
        branch = _optional_branch(payload.get("branch"))
        cloned = GitRepositoryAdapter.clone(
            source=repository,
            target=target,
            branch=branch,
            credential=resolve_credential(repository, config),
        )
        return {
            "targetPath": _relative(target, root),
            "repository": _overview(cloned, config),
        }
    if action == "init":
        return {"repository": adapter.init(branch=_branch(payload.get("branch") or "main"))}
    if action == "connect_remote":
        return {
            "repository": adapter.add_remote(
                name=_remote(payload.get("remote") or "origin"),
                url=_repository(payload.get("repository")),
            )
        }
    if action == "disconnect_remote":
        return {"repository": adapter.remove_remote(name=_remote(payload.get("remote") or "origin"))}
    if action == "fetch":
        remote = _remote(payload.get("remote") or "origin")
        url = adapter.remote_url(remote)
        return {
            "comparison": adapter.fetch(remote=remote, credential=resolve_credential(url, config)),
            "authentication": authentication_summary(url, config),
        }
    if action == "create_branch":
        return {"repository": adapter.create_branch(branch=_branch(payload.get("branch")))}
    if action == "switch_branch":
        return {"repository": adapter.switch_branch(branch=_branch(payload.get("branch")))}
    if action == "delete_branch":
        return {"repository": adapter.delete_branch(branch=_branch(payload.get("branch")))}
    if action == "list_tags":
        return {"tags": adapter.list_tags()}
    if action == "create_tag":
        return {
            "tags": adapter.create_tag(
                tag=_tag(payload.get("tag")),
                revision=str(payload.get("revision") or "HEAD"),
            )
        }
    if action == "delete_tag":
        return {"tags": adapter.delete_tag(tag=_tag(payload.get("tag")))}
    if action == "list_submodules":
        return {"submodules": adapter.list_submodules()}
    if action == "add_submodule":
        return {
            "submodules": adapter.add_submodule(
                url=_repository(payload.get("repository")),
                path=_required(payload.get("submodule_path"), "add_submodule 必须提供 submodule_path。"),
            )
        }
    if action == "update_submodules":
        return {
            "submodules": adapter.update_submodules(
                paths=_paths(payload.get("paths")),
                force=bool(payload.get("force", False)),
            )
        }
    if action == "configure_identity":
        identity = _explicit_identity(payload)
        scope = str(payload.get("identity_scope") or "repository").strip()
        if scope == "repository":
            repo = adapter.open()
            try:
                configure_repository_identity(repo, identity)
            finally:
                repo.close()
        elif scope == "tool":
            config.save_identity(identity)
        else:
            raise ToolError("INVALID_ARGUMENT", "identity_scope 只能是 repository 或 tool。")
        return {"identity": {**identity.public_dict(), "source": scope}}
    if action == "commit":
        identity, candidates = _identity(adapter, config, payload, required=True)
        sha = adapter.commit(
            message=_required(payload.get("message"), "commit 必须提供 message。"),
            paths=_paths(payload.get("paths")),
            identity=identity,
        )
        return {"commitSha": sha, "identity": identity.public_dict(), "identityCandidates": candidates}
    if action in {"push", "pull"}:
        remote = _remote(payload.get("remote") or "origin")
        overview = adapter.overview()
        branch = _branch(payload.get("branch") or overview.get("branch") or "main")
        url = adapter.remote_url(remote)
        credential = resolve_credential(url, config)
        if action == "push":
            result = adapter.push(
                remote=remote,
                branch=branch,
                credential=credential,
                force=bool(payload.get("force", False)),
            )
        else:
            result = adapter.pull(remote=remote, branch=branch, credential=credential)
        return {"repository": result, "authentication": authentication_summary(url, config)}
    if action == "restore":
        return {"repository": adapter.restore(paths=_required_paths(payload.get("paths"), "restore 必须提供 paths。"))}
    if action == "revert":
        identity, candidates = _identity(adapter, config, payload, required=True)
        sha = adapter.revert(
            revision=_required(payload.get("revision"), "revert 必须提供 revision。"),
            identity=identity,
        )
        return {"commitSha": sha, "identity": identity.public_dict(), "identityCandidates": candidates}
    if action == "reset":
        return {
            "repository": adapter.reset(
                revision=_required(payload.get("revision"), "reset 必须提供 revision。"),
                hard=bool(payload.get("force", False)),
            )
        }
    raise ToolError("UNSUPPORTED_ACTION", f"不支持的 Git 操作：{action}")


def _preview(
    action: str,
    payload: dict[str, Any],
    root: Path,
    adapter: GitRepositoryAdapter,
    config: ToolConfiguration,
) -> dict[str, Any]:
    preview: dict[str, Any] = {"wouldExecute": action, "engine": "embedded_dulwich"}
    if action == "clone":
        repository = _repository(payload.get("repository"))
        target = _clone_target(root, payload.get("target_path"), repository)
        preview.update(
            {
                "repositoryUrl": redact_remote_url(repository),
                "targetPath": _relative(target, root),
                "branch": _optional_branch(payload.get("branch")),
                "authentication": authentication_summary(repository, config),
            }
        )
        return preview

    overview = adapter.overview()
    preview["repository"] = overview
    if action == "init":
        if overview["initialized"]:
            raise ToolError("ALREADY_INITIALIZED", "当前工作区已经是 Git 仓库。")
        preview["branch"] = _branch(payload.get("branch") or "main")
    elif action == "commit":
        identity, candidates = _identity(adapter, config, payload, required=True)
        changes = _selected_changes(adapter.status()["changes"], _paths(payload.get("paths")))
        if not changes:
            raise ToolError("NO_CHANGES", "没有可提交的改动。")
        preview.update(
            {
                "message": _required(payload.get("message"), "commit 必须提供 message。"),
                "changes": changes,
                "identity": identity.public_dict(),
                "identityCandidates": candidates,
            }
        )
    elif action == "configure_identity":
        identity = _explicit_identity(payload)
        scope = str(payload.get("identity_scope") or "repository").strip()
        if scope not in {"repository", "tool"}:
            raise ToolError("INVALID_ARGUMENT", "identity_scope 只能是 repository 或 tool。")
        if scope == "repository":
            adapter.open().close()
        preview.update({"identity": identity.public_dict(), "identityScope": scope})
    elif action in {"fetch", "push", "pull"}:
        remote = _remote(payload.get("remote") or "origin")
        url = adapter.remote_url(remote)
        preview.update(
            {
                "remote": remote,
                "branch": payload.get("branch") or overview.get("branch"),
                "authentication": authentication_summary(url, config),
                "comparison": adapter.remote_comparison(remote=remote),
                "force": bool(payload.get("force", False)),
            }
        )
        if action == "pull" and not overview.get("clean", True):
            raise ToolError("WORKTREE_NOT_CLEAN", "当前仓库还有未提交改动，不能拉取。")
    elif action == "restore":
        paths = _required_paths(payload.get("paths"), "restore 必须提供 paths。")
        changes = _selected_changes(adapter.status()["changes"], paths)
        if not changes:
            raise ToolError("NO_CHANGES", "指定文件没有可恢复的改动。")
        preview["changes"] = changes
    elif action in {"revert", "reset"}:
        revision = _required(payload.get("revision"), f"{action} 必须提供 revision。")
        preview["commit"] = adapter.show_commit(revision)
        if action == "revert":
            identity, candidates = _identity(adapter, config, payload, required=True)
            preview.update({"identity": identity.public_dict(), "identityCandidates": candidates})
        else:
            preview["hard"] = bool(payload.get("force", False))
    else:
        _validate_simple_preview(action, payload, overview)
        preview.update(
            {
                "remote": payload.get("remote"),
                "repositoryUrl": redact_remote_url(str(payload.get("repository") or "")),
                "branch": payload.get("branch"),
                "tag": payload.get("tag"),
                "paths": _paths(payload.get("paths")),
                "submodulePath": payload.get("submodule_path"),
                "force": bool(payload.get("force", False)),
            }
        )
    return preview


def _overview(adapter: GitRepositoryAdapter, config: ToolConfiguration) -> dict[str, Any]:
    repository = adapter.overview()
    selected: GitIdentity | None = None
    candidates: list[dict[str, str]] = []
    if repository["initialized"]:
        repo = adapter.open()
        try:
            selected, candidates = resolve_identity(repo, config)
        finally:
            repo.close()
    remotes = []
    for remote in repository.get("remotes", []):
        raw_url = adapter.remote_url(remote["name"])
        remotes.append(
            {
                **remote,
                "authentication": authentication_summary(raw_url, config),
            }
        )
    repository["remotes"] = remotes
    return {
        "repository": repository,
        "identity": selected.public_dict() if selected else None,
        "identityCandidates": candidates,
    }


def _identity(
    adapter: GitRepositoryAdapter,
    config: ToolConfiguration,
    payload: dict[str, Any],
    *,
    required: bool,
) -> tuple[GitIdentity, list[dict[str, str]]]:
    repo = adapter.open()
    try:
        selected, candidates = resolve_identity(
            repo,
            config,
            author_name=payload.get("author_name"),
            author_email=payload.get("author_email"),
        )
    finally:
        repo.close()
    if selected is None and required:
        raise ToolError(
            "GIT_IDENTITY_MISSING",
            "缺少 Git 作者姓名和邮箱。请显式提供 author_name、author_email，或先调用 configure_identity。",
        )
    assert selected is not None
    return selected, candidates


def _explicit_identity(payload: dict[str, Any]) -> GitIdentity:
    try:
        return validate_identity(payload.get("author_name"), payload.get("author_email"))
    except ConfigurationError as exc:
        raise ToolError(
            "GIT_IDENTITY_MISSING",
            "configure_identity 必须提供有效的 author_name 和 author_email。",
        ) from exc


def _validate_simple_preview(action: str, payload: dict[str, Any], overview: dict[str, Any]) -> None:
    if action == "connect_remote":
        _remote(payload.get("remote") or "origin")
        _repository(payload.get("repository"))
    elif action == "disconnect_remote":
        remote = _remote(payload.get("remote") or "origin")
        if remote not in {item["name"] for item in overview.get("remotes", [])}:
            raise ToolError("REMOTE_NOT_FOUND", f"远端 {remote} 不存在。")
    elif action in {"create_branch", "switch_branch", "delete_branch"}:
        branch = _branch(payload.get("branch"))
        if action == "delete_branch" and branch == overview.get("branch"):
            raise ToolError("ACTIVE_BRANCH", "不能删除当前正在使用的分支。")
    elif action in {"create_tag", "delete_tag"}:
        _tag(payload.get("tag"))
    elif action == "add_submodule":
        _repository(payload.get("repository"))
        _required(payload.get("submodule_path"), "add_submodule 必须提供 submodule_path。")


def _workspace_root() -> Path:
    raw = os.environ.get("TIANCE_WORKSPACE_ROOT") or os.environ.get("WORKSPACE_ROOT") or os.getcwd()
    root = Path(raw).expanduser().resolve(strict=False)
    if not root.is_dir():
        raise ToolError("WORKSPACE_NOT_FOUND", "当前工作区不存在。", {"workspaceRoot": str(root)})
    return root


def _clone_target(root: Path, value: object, repository: str) -> Path:
    raw = str(value or "").strip()
    if not raw:
        path_part = urlsplit(repository).path if "://" in repository else repository.rsplit(":", 1)[-1]
        raw = Path(path_part.rstrip("/")).name.removesuffix(".git")
    if not raw:
        raise ToolError("INVALID_TARGET_PATH", "无法从仓库地址推断克隆目录，请提供 target_path。")
    target = (root / raw).resolve(strict=False) if not Path(raw).is_absolute() else Path(raw).resolve(strict=False)
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ToolError("PATH_OUTSIDE_WORKSPACE", "克隆目标必须位于当前工作区内。") from exc
    if target == root:
        raise ToolError("INVALID_TARGET_PATH", "请把仓库克隆到工作区内的子目录。")
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise ToolError("TARGET_NOT_EMPTY", "克隆目标必须不存在或为空目录。", {"targetPath": str(target)})
    return target


def _repository(value: object) -> str:
    normalized = str(value or "").strip()
    if not normalized or any(char in normalized for char in ("\r", "\n", "\0")):
        raise ToolError("INVALID_REPOSITORY", "必须提供有效的 Git 仓库地址。")
    parsed = urlsplit(normalized)
    if parsed.scheme in {"http", "https", "ssh", "file"}:
        if parsed.scheme in {"http", "https"} and (parsed.username or parsed.password):
            raise ToolError(
                "CREDENTIAL_IN_URL",
                "仓库地址不能内嵌账号或密钥，请把 HTTPS 凭据写入工具 config.json。",
            )
        return normalized
    if "@" in normalized.split(":", 1)[0] and ":" in normalized:
        return normalized
    path = Path(normalized).expanduser()
    if path.exists():
        return str(path.resolve())
    raise ToolError("INVALID_REPOSITORY", "仓库地址必须是 HTTPS、SSH、file URL 或现有本地路径。")


def _branch(value: object) -> str:
    normalized = _required(value, "必须提供 branch。")
    if BRANCH_PATTERN.fullmatch(normalized) is None:
        raise ToolError("INVALID_BRANCH", "Git 分支名称无效。")
    return normalized


def _optional_branch(value: object) -> str | None:
    normalized = str(value or "").strip()
    return _branch(normalized) if normalized else None


def _tag(value: object) -> str:
    normalized = _required(value, "必须提供 tag。")
    if TAG_PATTERN.fullmatch(normalized) is None:
        raise ToolError("INVALID_TAG", "Git 标签名称无效。")
    return normalized


def _remote(value: object) -> str:
    normalized = str(value or "origin").strip()
    if REMOTE_PATTERN.fullmatch(normalized) is None:
        raise ToolError("INVALID_REMOTE", "Git 远端名称无效。")
    return normalized


def _paths(value: object) -> list[str] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        raise ToolError("INVALID_PATHS", "paths 必须是字符串数组。")
    result = [str(item).strip() for item in value if str(item).strip()]
    if len(result) > 5000:
        raise ToolError("TOO_MANY_PATHS", "paths 最多包含 5000 项。")
    return result or None


def _required_paths(value: object, message: str) -> list[str]:
    result = _paths(value)
    if not result:
        raise ToolError("MISSING_PATHS", message)
    return result


def _selected_changes(changes: list[dict[str, str]], paths: list[str] | None) -> list[dict[str, str]]:
    if not paths:
        return changes
    normalized = {path.strip().replace("\\", "/").strip("/") for path in paths}
    return [item for item in changes if item["path"] in normalized]


def _required(value: object, message: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ToolError("MISSING_ARGUMENT", message)
    return normalized


def _integer(value: object, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value) if value is not None else default
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _success(action: str, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": True,
        "action": action,
        "engine": "embedded_dulwich",
        "systemGitRequired": False,
        **data,
    }


def _failure(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "ok": False,
        "error": f"{code}: {message}",
        "error_info": {"code": code, "message": message, "details": details or {}},
    }
