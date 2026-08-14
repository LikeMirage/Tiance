from __future__ import annotations

from io import BytesIO
from pathlib import Path
import re
import shutil
from typing import Any

from dulwich import porcelain
from dulwich.errors import NotGitRepository
from dulwich.graph import can_fast_forward
from dulwich.objects import Commit
from dulwich.objectspec import parse_object
from dulwich.repo import Repo

from configuration import GitCredential, GitIdentity, redact_remote_url


class GitRepositoryError(RuntimeError):
    pass


class GitRepositoryAdapter:
    """内嵌 Git 实现，只操作传入的工作区目录。"""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve(strict=False)

    @property
    def initialized(self) -> bool:
        if not (self.root / ".git").is_dir():
            return False
        try:
            repo = Repo(str(self.root))
        except NotGitRepository:
            return False
        try:
            return Path(repo.path).resolve(strict=False) == self.root
        finally:
            repo.close()

    @classmethod
    def clone(
        cls,
        *,
        source: str,
        target: Path,
        branch: str | None,
        credential: GitCredential | None,
    ) -> GitRepositoryAdapter:
        target = target.resolve(strict=False)
        existed = target.exists()
        if existed and (not target.is_dir() or any(target.iterdir())):
            raise GitRepositoryError("克隆目标必须不存在或为空目录。")
        try:
            repo = porcelain.clone(
                source,
                str(target),
                checkout=True,
                branch=branch,
                **_credential_kwargs(credential),
            )
            repo.close()
        except Exception as exc:
            if not existed and target.exists():
                shutil.rmtree(target, ignore_errors=True)
            raise GitRepositoryError(
                _friendly_error(exc, remote=True, credential=credential)
            ) from exc
        return cls(target)

    def init(self, *, branch: str) -> dict[str, Any]:
        if self.initialized:
            raise GitRepositoryError("当前工作区已经是 Git 仓库。")
        repo = porcelain.init(str(self.root))
        try:
            repo.refs.set_symbolic_ref(b"HEAD", f"refs/heads/{branch}".encode("utf-8"))
        finally:
            repo.close()
        return self.overview()

    def overview(self) -> dict[str, Any]:
        if not self.initialized:
            return {
                "initialized": False,
                "branch": None,
                "head": None,
                "remotes": [],
                "changes": [],
                "clean": True,
            }
        repo = self.open()
        try:
            return {
                "initialized": True,
                "branch": self._active_branch(repo),
                "head": self._head(repo),
                "remotes": self._remotes(repo),
                **self._status(repo),
            }
        finally:
            repo.close()

    def status(self) -> dict[str, Any]:
        repo = self.open()
        try:
            return self._status(repo)
        finally:
            repo.close()

    def diff(self, *, staged: bool, paths: list[str] | None, limit: int = 200_000) -> str:
        repo = self.open()
        output = BytesIO()
        try:
            porcelain.diff(
                repo,
                staged=staged,
                paths=[self._normalize_path(path) for path in paths] if paths else None,
                outstream=output,
            )
        finally:
            repo.close()
        raw = output.getvalue()
        if len(raw) > limit:
            return raw[:limit].decode("utf-8", errors="replace") + "\n…差异内容已截断。"
        return raw.decode("utf-8", errors="replace")

    def log(self, *, limit: int) -> list[dict[str, Any]]:
        repo = self.open()
        try:
            if self._head(repo) is None:
                return []
            commits: list[dict[str, Any]] = []
            for entry in repo.get_walker(max_entries=max(1, min(limit, 100))):
                commit = entry.commit
                commits.append(
                    {
                        "sha": commit.id.decode("ascii"),
                        "shortSha": commit.id.decode("ascii")[:12],
                        "message": commit.message.decode("utf-8", errors="replace").strip(),
                        "author": commit.author.decode("utf-8", errors="replace"),
                        "timestamp": commit.commit_time,
                        "parents": [parent.decode("ascii") for parent in commit.parents],
                    }
                )
            return commits
        finally:
            repo.close()

    def show_commit(self, revision: str) -> dict[str, Any]:
        repo = self.open()
        try:
            commit = parse_object(repo, revision)
            if not isinstance(commit, Commit):
                raise GitRepositoryError("指定对象不是提交。")
            return {
                "sha": commit.id.decode("ascii"),
                "message": commit.message.decode("utf-8", errors="replace").strip(),
                "author": commit.author.decode("utf-8", errors="replace"),
                "timestamp": commit.commit_time,
                "parents": [parent.decode("ascii") for parent in commit.parents],
            }
        except (KeyError, ValueError) as exc:
            raise GitRepositoryError("找不到指定提交。") from exc
        finally:
            repo.close()

    def add_remote(self, *, name: str, url: str) -> dict[str, Any]:
        repo = self.open()
        try:
            if name in {item["name"] for item in self._remotes(repo)}:
                config = repo.get_config()
                config.set((b"remote", name.encode("utf-8")), b"url", url.encode("utf-8"))
                config.write_to_path()
            else:
                porcelain.remote_add(repo, name, url)
        finally:
            repo.close()
        return self.overview()

    def remove_remote(self, *, name: str) -> dict[str, Any]:
        repo = self.open()
        try:
            porcelain.remote_remove(repo, name)
        except KeyError as exc:
            raise GitRepositoryError(f"远端 {name} 不存在。") from exc
        finally:
            repo.close()
        return self.overview()

    def remote_url(self, remote: str) -> str:
        repo = self.open()
        try:
            return self._remote_url(repo, remote)
        finally:
            repo.close()

    def fetch(self, *, remote: str, credential: GitCredential | None) -> dict[str, Any]:
        repo = self.open()
        try:
            remote_url = self._remote_url(repo, remote)
            result = porcelain.fetch(
                repo,
                remote_url,
                quiet=True,
                **_credential_kwargs(credential),
            )
            self._store_remote_tracking_ref(repo, remote, result.refs)
            return self._remote_comparison(repo, remote)
        except Exception as exc:
            raise GitRepositoryError(
                _friendly_error(exc, remote=True, credential=credential)
            ) from exc
        finally:
            repo.close()

    def remote_comparison(self, *, remote: str) -> dict[str, Any]:
        repo = self.open()
        try:
            self._remote_url(repo, remote)
            return self._remote_comparison(repo, remote)
        finally:
            repo.close()

    def commit(self, *, message: str, paths: list[str] | None, identity: GitIdentity) -> str:
        repo = self.open()
        try:
            all_changes = self._all_changes(repo)
            internal_staged = [
                item for item in all_changes
                if item["state"].startswith("staged-") and not self._is_user_path(item["path"])
            ]
            if internal_staged:
                raise GitRepositoryError("暂存区包含 .Tiance 或 .git 内部文件，请先从暂存区移除。")
            user_changes = [item for item in all_changes if self._is_user_path(item["path"])]
            requested = [self._normalize_path(path) for path in paths] if paths else None
            selected = (
                sorted({item["path"] for item in user_changes if item["path"] in set(requested or [])})
                if requested is not None
                else sorted({item["path"] for item in user_changes})
            )
            if not selected:
                raise GitRepositoryError("没有可提交的改动。")
            staged_outside_selection = [
                item for item in user_changes
                if item["state"].startswith("staged-") and item["path"] not in set(selected)
            ]
            if staged_outside_selection:
                raise GitRepositoryError("暂存区还包含 paths 之外的改动；为避免误提交，请先处理这些暂存内容。")
            porcelain.add(repo, paths=selected)
            commit_id = porcelain.commit(
                repo,
                message=message,
                author=identity.encoded,
                committer=identity.encoded,
            )
            return commit_id.decode("ascii")
        except GitRepositoryError:
            raise
        except Exception as exc:
            raise GitRepositoryError(_friendly_error(exc)) from exc
        finally:
            repo.close()

    def push(
        self,
        *,
        remote: str,
        branch: str,
        credential: GitCredential | None,
        force: bool = False,
    ) -> dict[str, Any]:
        repo = self.open()
        try:
            remote_url = self._remote_url(repo, remote)
            result = porcelain.push(
                repo,
                remote_url,
                refspecs=f"refs/heads/{branch}:refs/heads/{branch}",
                force=force,
                **_credential_kwargs(credential),
            )
            errors = [
                value.decode("utf-8", errors="replace")
                for value in result.ref_status.values()
                if value
            ]
            if errors:
                raise GitRepositoryError("；".join(errors))
            branch_ref = f"refs/heads/{branch}".encode("utf-8")
            try:
                repo.refs[f"refs/remotes/{remote}/{branch}".encode("utf-8")] = repo.refs[branch_ref]
            except KeyError:
                pass
            return self._remote_comparison(repo, remote)
        except GitRepositoryError:
            raise
        except Exception as exc:
            raise GitRepositoryError(
                _friendly_error(exc, remote=True, credential=credential)
            ) from exc
        finally:
            repo.close()

    def pull(
        self,
        *,
        remote: str,
        branch: str,
        credential: GitCredential | None,
    ) -> dict[str, Any]:
        repo = self.open()
        try:
            if not self._status(repo)["clean"]:
                raise GitRepositoryError("当前仓库还有未提交改动，拉取前请先处理。")
            remote_url = self._remote_url(repo, remote)
            porcelain.pull(
                repo,
                remote_url,
                refspecs=f"refs/heads/{branch}",
                ff_only=True,
                **_credential_kwargs(credential),
            )
            return self.overview()
        except GitRepositoryError:
            raise
        except Exception as exc:
            raise GitRepositoryError(
                _friendly_error(exc, remote=True, credential=credential)
            ) from exc
        finally:
            repo.close()

    def create_branch(self, *, branch: str) -> dict[str, Any]:
        repo = self.open()
        try:
            porcelain.branch_create(repo, branch)
        except Exception as exc:
            raise GitRepositoryError(_friendly_error(exc)) from exc
        finally:
            repo.close()
        return self.overview()

    def switch_branch(self, *, branch: str) -> dict[str, Any]:
        repo = self.open()
        try:
            if not self._status(repo)["clean"]:
                raise GitRepositoryError("当前仓库还有未提交改动，切换分支前请先处理。")
            porcelain.checkout(repo, branch)
        except GitRepositoryError:
            raise
        except Exception as exc:
            raise GitRepositoryError(_friendly_error(exc)) from exc
        finally:
            repo.close()
        return self.overview()

    def delete_branch(self, *, branch: str) -> dict[str, Any]:
        repo = self.open()
        try:
            if self._active_branch(repo) == branch:
                raise GitRepositoryError("不能删除当前正在使用的分支。")
            porcelain.branch_delete(repo, branch)
        except GitRepositoryError:
            raise
        except Exception as exc:
            raise GitRepositoryError(_friendly_error(exc)) from exc
        finally:
            repo.close()
        return self.overview()

    def list_tags(self) -> list[str]:
        repo = self.open()
        try:
            return sorted(self._decode_path(tag) for tag in porcelain.tag_list(repo))
        finally:
            repo.close()

    def create_tag(self, *, tag: str, revision: str) -> list[str]:
        repo = self.open()
        try:
            porcelain.tag_create(repo, tag, objectish=revision)
        except Exception as exc:
            raise GitRepositoryError(_friendly_error(exc)) from exc
        finally:
            repo.close()
        return self.list_tags()

    def delete_tag(self, *, tag: str) -> list[str]:
        repo = self.open()
        try:
            porcelain.tag_delete(repo, tag.encode("utf-8"))
        except Exception as exc:
            raise GitRepositoryError(_friendly_error(exc)) from exc
        finally:
            repo.close()
        return self.list_tags()

    def list_submodules(self) -> list[dict[str, str]]:
        repo = self.open()
        try:
            return [
                {"path": str(path).replace("\\", "/"), "url": redact_remote_url(str(url))}
                for path, url in porcelain.submodule_list(repo)
            ]
        finally:
            repo.close()

    def add_submodule(self, *, url: str, path: str) -> list[dict[str, str]]:
        normalized = self._normalize_path(path)
        repo = self.open()
        try:
            porcelain.submodule_add(repo, url, path=normalized)
        except Exception as exc:
            raise GitRepositoryError(_friendly_error(exc, remote=True)) from exc
        finally:
            repo.close()
        return self.list_submodules()

    def update_submodules(self, *, paths: list[str] | None, force: bool) -> list[dict[str, str]]:
        normalized = [self._normalize_path(path) for path in paths] if paths else None
        repo = self.open()
        try:
            porcelain.submodule_update(repo, paths=normalized, init=True, force=force, recursive=True)
        except Exception as exc:
            raise GitRepositoryError(_friendly_error(exc, remote=True)) from exc
        finally:
            repo.close()
        return self.list_submodules()

    def restore(self, *, paths: list[str]) -> dict[str, Any]:
        repo = self.open()
        try:
            porcelain.checkout(repo, paths=[self._normalize_path(path) for path in paths])
        except Exception as exc:
            raise GitRepositoryError(_friendly_error(exc)) from exc
        finally:
            repo.close()
        return self.overview()

    def revert(self, *, revision: str, identity: GitIdentity) -> str:
        repo = self.open()
        try:
            if not self._status(repo)["clean"]:
                raise GitRepositoryError("当前仓库还有未提交改动，撤销提交前请先处理。")
            commit_id = porcelain.revert(
                repo,
                revision,
                author=identity.encoded,
                committer=identity.encoded,
            )
            if commit_id is None:
                raise GitRepositoryError("没有产生可提交的撤销结果。")
            return commit_id.decode("ascii")
        except GitRepositoryError:
            raise
        except Exception as exc:
            raise GitRepositoryError(_friendly_error(exc)) from exc
        finally:
            repo.close()

    def reset(self, *, revision: str, hard: bool) -> dict[str, Any]:
        repo = self.open()
        try:
            porcelain.reset(repo, "hard" if hard else "mixed", treeish=revision)
        except Exception as exc:
            raise GitRepositoryError(_friendly_error(exc)) from exc
        finally:
            repo.close()
        return self.overview()

    def open(self) -> Repo:
        if not self.initialized:
            raise GitRepositoryError("当前工作区还不是 Git 仓库，请先初始化或克隆仓库。")
        return Repo(str(self.root))

    def _status(self, repo: Repo) -> dict[str, Any]:
        changes = [item for item in self._all_changes(repo) if self._is_user_path(item["path"])]
        return {"changes": changes, "clean": not changes}

    def _all_changes(self, repo: Repo) -> list[dict[str, str]]:
        raw = porcelain.status(repo, untracked_files="all")
        changes: list[dict[str, str]] = []
        for kind, paths in raw.staged.items():
            changes.extend(
                {"path": self._decode_path(path), "state": f"staged-{kind}"}
                for path in paths
            )
        changes.extend(
            {"path": self._decode_path(path), "state": "modified"}
            for path in raw.unstaged
        )
        changes.extend(
            {"path": self._decode_path(path), "state": "untracked"}
            for path in raw.untracked
        )
        changes.sort(key=lambda item: (item["path"].casefold(), item["state"]))
        return changes

    @staticmethod
    def _head(repo: Repo) -> str | None:
        try:
            return repo.head().decode("ascii")
        except KeyError:
            return None

    @staticmethod
    def _active_branch(repo: Repo) -> str | None:
        try:
            return porcelain.active_branch(repo).decode("utf-8")
        except (KeyError, TypeError):
            return None

    @staticmethod
    def _remotes(repo: Repo) -> list[dict[str, str]]:
        config = repo.get_config()
        remotes: list[dict[str, str]] = []
        for section in config.sections():
            if len(section) != 2 or section[0] != b"remote":
                continue
            try:
                url = config.get(section, b"url").decode("utf-8")
            except KeyError:
                continue
            remotes.append(
                {"name": section[1].decode("utf-8"), "url": redact_remote_url(url)}
            )
        return sorted(remotes, key=lambda item: item["name"])

    @staticmethod
    def _remote_url(repo: Repo, name: str) -> str:
        try:
            return repo.get_config().get(
                (b"remote", name.encode("utf-8")), b"url"
            ).decode("utf-8")
        except KeyError as exc:
            raise GitRepositoryError(f"远端 {name} 不存在。") from exc

    def _remote_comparison(self, repo: Repo, remote: str) -> dict[str, Any]:
        branch = self._active_branch(repo)
        local = self._head(repo)
        if not branch or not local:
            return {"remote": remote, "branch": branch, "ahead": 0, "behind": 0, "diverged": False}
        remote_ref = f"refs/remotes/{remote}/{branch}".encode("utf-8")
        try:
            remote_head = repo.refs[remote_ref]
        except KeyError:
            return {"remote": remote, "branch": branch, "ahead": 0, "behind": 0, "diverged": False}
        local_id = local.encode("ascii")
        ahead = sum(1 for _ in repo.get_walker(include=[local_id], exclude=[remote_head]))
        behind = sum(1 for _ in repo.get_walker(include=[remote_head], exclude=[local_id]))
        return {
            "remote": remote,
            "branch": branch,
            "remoteHead": remote_head.decode("ascii"),
            "ahead": ahead,
            "behind": behind,
            "diverged": ahead > 0 and behind > 0,
            "canFastForward": can_fast_forward(repo, local_id, remote_head),
        }

    def _store_remote_tracking_ref(self, repo: Repo, remote: str, refs: dict[bytes, bytes]) -> None:
        branch = self._active_branch(repo)
        if not branch:
            return
        remote_head = refs.get(f"refs/heads/{branch}".encode("utf-8"))
        if remote_head is not None:
            repo.refs[f"refs/remotes/{remote}/{branch}".encode("utf-8")] = remote_head

    @staticmethod
    def _normalize_path(path: str) -> str:
        normalized = path.strip().replace("\\", "/").strip("/")
        parts = Path(normalized).parts
        if (
            not normalized
            or Path(normalized).is_absolute()
            or ".." in parts
            or any(part.casefold() in {".git", ".tiance"} for part in parts)
        ):
            raise GitRepositoryError("文件路径必须位于当前工作区内，且不能指向 .git 或 .Tiance。")
        return normalized

    @classmethod
    def _is_user_path(cls, path: bytes | str) -> bool:
        parts = Path(cls._decode_path(path)).parts
        return not any(part.casefold() in {".git", ".tiance"} for part in parts)

    @staticmethod
    def _decode_path(path: bytes | str) -> str:
        value = path.decode("utf-8", errors="replace") if isinstance(path, bytes) else path
        return value.replace("\\", "/")


def _credential_kwargs(credential: GitCredential | None) -> dict[str, str]:
    return credential.porcelain_kwargs() if credential else {}


def _friendly_error(
    exc: Exception,
    *,
    remote: bool = False,
    credential: GitCredential | None = None,
) -> str:
    message = str(exc).strip() or type(exc).__name__
    message = re.sub(r"(https?://)[^/@\s]+@", r"\1***@", message, flags=re.IGNORECASE)
    if credential is not None and credential.password:
        message = message.replace(credential.password, "***")
    lowered = message.casefold()
    if remote and any(
        marker in lowered
        for marker in ("401", "403", "authentication", "unauthorized", "forbidden", "credentials")
    ):
        return "远端拒绝认证。请配置该仓库的 HTTPS 凭据，或确认系统 SSH/Git Credential Manager 中已有可用凭据。"
    return message
