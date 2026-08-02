from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

from dulwich import porcelain
from dulwich.errors import NotGitRepository
from dulwich.graph import can_fast_forward
from dulwich.objects import Commit
from dulwich.objectspec import parse_object
from dulwich.repo import Repo


class GitRepositoryError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class GitIdentity:
    name: str
    email: str

    @property
    def encoded(self) -> bytes:
        return f"{self.name} <{self.email}>".encode("utf-8")


class GitRepositoryAdapter:
    """Standard Git operations for one registered project root."""

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

    def init(self, *, branch: str) -> dict[str, Any]:
        if self.initialized:
            raise GitRepositoryError("当前项目已经是 Git 仓库。")
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
        repo = self._open()
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
        repo = self._open()
        try:
            return self._status(repo)
        finally:
            repo.close()

    def diff(self, *, staged: bool, paths: list[str] | None, limit: int | None = 200_000) -> str:
        repo = self._open()
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
        if limit is not None and len(raw) > limit:
            return raw[:limit].decode("utf-8", errors="replace") + "\n…差异内容超过显示上限。"
        return raw.decode("utf-8", errors="replace")

    def log(self, *, limit: int) -> list[dict[str, Any]]:
        repo = self._open()
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
        repo = self._open()
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
        except GitRepositoryError:
            raise
        except Exception as exc:
            raise GitRepositoryError(self._friendly_error(exc)) from exc
        finally:
            repo.close()

    def add_remote(self, *, name: str, url: str) -> dict[str, Any]:
        repo = self._open()
        try:
            remotes = {item["name"]: item for item in self._remotes(repo)}
            if name in remotes:
                config = repo.get_config()
                config.set((b"remote", name.encode("utf-8")), b"url", url.encode("utf-8"))
                config.write_to_path()
            else:
                porcelain.remote_add(repo, name, url)
        finally:
            repo.close()
        return self.overview()

    def remove_remote(self, *, name: str) -> dict[str, Any]:
        repo = self._open()
        try:
            porcelain.remote_remove(repo, name)
        except KeyError as exc:
            raise GitRepositoryError(f"远端 {name} 不存在。") from exc
        finally:
            repo.close()
        return self.overview()

    def fetch(self, *, remote: str, token: str | None) -> dict[str, Any]:
        repo = self._open()
        try:
            remote_url = self._remote_url(repo, remote)
            result = porcelain.fetch(
                repo,
                remote_url,
                quiet=True,
                **self._credentials(remote_url, token),
            )
            self._store_remote_tracking_ref(repo, remote, result.refs)
            return self._remote_comparison(repo, remote)
        finally:
            repo.close()

    def remote_comparison(self, *, remote: str) -> dict[str, Any]:
        """Compare against the last fetched remote ref without changing the repository."""
        repo = self._open()
        try:
            self._remote_url(repo, remote)
            return self._remote_comparison(repo, remote)
        finally:
            repo.close()

    def commit(
        self,
        *,
        message: str,
        paths: list[str] | None,
        identity: GitIdentity,
    ) -> str:
        repo = self._open()
        try:
            normalized_paths = [self._normalize_path(path) for path in paths] if paths else None
            porcelain.add(repo, paths=normalized_paths)
            commit_id = porcelain.commit(
                repo,
                message=message,
                author=identity.encoded,
                committer=identity.encoded,
            )
            return commit_id.decode("ascii")
        except Exception as exc:
            raise GitRepositoryError(self._friendly_error(exc)) from exc
        finally:
            repo.close()

    def push(self, *, remote: str, branch: str, token: str | None, force: bool = False) -> dict[str, Any]:
        repo = self._open()
        try:
            remote_url = self._remote_url(repo, remote)
            result = porcelain.push(
                repo,
                remote_url,
                refspecs=f"refs/heads/{branch}:refs/heads/{branch}",
                force=force,
                **self._credentials(remote_url, token),
            )
            errors = [value.decode("utf-8", errors="replace") for value in result.ref_status.values() if value]
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
            raise GitRepositoryError(self._friendly_error(exc)) from exc
        finally:
            repo.close()

    def pull(self, *, remote: str, branch: str, token: str | None) -> dict[str, Any]:
        repo = self._open()
        try:
            if not self._status(repo)["clean"]:
                raise GitRepositoryError("当前项目还有未提交改动，拉取前请先提交或处理这些改动。")
            remote_url = self._remote_url(repo, remote)
            porcelain.pull(
                repo,
                remote_url,
                refspecs=f"refs/heads/{branch}",
                ff_only=True,
                **self._credentials(remote_url, token),
            )
            return self.overview()
        except GitRepositoryError:
            raise
        except Exception as exc:
            raise GitRepositoryError(self._friendly_error(exc)) from exc
        finally:
            repo.close()

    def create_branch(self, *, branch: str) -> dict[str, Any]:
        repo = self._open()
        try:
            porcelain.branch_create(repo, branch)
        except Exception as exc:
            raise GitRepositoryError(self._friendly_error(exc)) from exc
        finally:
            repo.close()
        return self.overview()

    def switch_branch(self, *, branch: str) -> dict[str, Any]:
        repo = self._open()
        try:
            if not self._status(repo)["clean"]:
                raise GitRepositoryError("当前项目还有未提交改动，切换分支前请先处理。")
            porcelain.checkout(repo, branch)
        except GitRepositoryError:
            raise
        except Exception as exc:
            raise GitRepositoryError(self._friendly_error(exc)) from exc
        finally:
            repo.close()
        return self.overview()

    def delete_branch(self, *, branch: str) -> dict[str, Any]:
        repo = self._open()
        try:
            if self._active_branch(repo) == branch:
                raise GitRepositoryError("不能删除当前正在使用的分支。")
            porcelain.branch_delete(repo, branch)
        except GitRepositoryError:
            raise
        except Exception as exc:
            raise GitRepositoryError(self._friendly_error(exc)) from exc
        finally:
            repo.close()
        return self.overview()

    def list_tags(self) -> list[str]:
        repo = self._open()
        try:
            return sorted(self._decode_path(tag) for tag in porcelain.tag_list(repo))
        finally:
            repo.close()

    def create_tag(self, *, tag: str, revision: str) -> list[str]:
        repo = self._open()
        try:
            porcelain.tag_create(repo, tag, objectish=revision)
        except Exception as exc:
            raise GitRepositoryError(self._friendly_error(exc)) from exc
        finally:
            repo.close()
        return self.list_tags()

    def delete_tag(self, *, tag: str) -> list[str]:
        repo = self._open()
        try:
            porcelain.tag_delete(repo, tag.encode("utf-8"))
        except Exception as exc:
            raise GitRepositoryError(self._friendly_error(exc)) from exc
        finally:
            repo.close()
        return self.list_tags()

    def list_submodules(self) -> list[dict[str, str]]:
        repo = self._open()
        try:
            return [
                {"path": str(path).replace("\\", "/"), "url": str(url)}
                for path, url in porcelain.submodule_list(repo)
            ]
        finally:
            repo.close()

    def add_submodule(self, *, url: str, path: str) -> list[dict[str, str]]:
        normalized = self._normalize_path(path)
        repo = self._open()
        try:
            porcelain.submodule_add(repo, url, path=normalized)
        except Exception as exc:
            raise GitRepositoryError(self._friendly_error(exc)) from exc
        finally:
            repo.close()
        return self.list_submodules()

    def update_submodules(self, *, paths: list[str] | None, force: bool) -> list[dict[str, str]]:
        normalized = [self._normalize_path(path) for path in paths] if paths else None
        repo = self._open()
        try:
            porcelain.submodule_update(repo, paths=normalized, init=True, force=force, recursive=True)
        except Exception as exc:
            raise GitRepositoryError(self._friendly_error(exc)) from exc
        finally:
            repo.close()
        return self.list_submodules()

    def restore(self, *, paths: list[str]) -> dict[str, Any]:
        repo = self._open()
        try:
            porcelain.checkout(repo, paths=[self._normalize_path(path) for path in paths])
        except Exception as exc:
            raise GitRepositoryError(self._friendly_error(exc)) from exc
        finally:
            repo.close()
        return self.overview()

    def revert(self, *, revision: str, identity: GitIdentity) -> str:
        repo = self._open()
        try:
            if not self._status(repo)["clean"]:
                raise GitRepositoryError("当前项目还有未提交改动，撤销提交前请先处理。")
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
            raise GitRepositoryError(self._friendly_error(exc)) from exc
        finally:
            repo.close()

    def reset(self, *, revision: str, hard: bool) -> dict[str, Any]:
        repo = self._open()
        try:
            porcelain.reset(repo, "hard" if hard else "mixed", treeish=revision)
        except Exception as exc:
            raise GitRepositoryError(self._friendly_error(exc)) from exc
        finally:
            repo.close()
        return self.overview()

    def fingerprint(self) -> str:
        import hashlib
        import json

        payload = self.overview()
        digest = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        )
        if payload["initialized"]:
            digest.update(self.diff(staged=False, paths=None, limit=None).encode("utf-8"))
            digest.update(self.diff(staged=True, paths=None, limit=None).encode("utf-8"))
            for change in payload["changes"]:
                if change["state"] != "untracked":
                    continue
                file_path = (self.root / change["path"]).resolve(strict=False)
                try:
                    file_path.relative_to(self.root)
                except ValueError:
                    continue
                if not file_path.is_file():
                    continue
                with file_path.open("rb") as stream:
                    while chunk := stream.read(1024 * 1024):
                        digest.update(chunk)
        return digest.hexdigest()

    def _open(self) -> Repo:
        if not self.initialized:
            raise GitRepositoryError("当前项目还不是 Git 仓库，请先初始化或克隆仓库。")
        return Repo(str(self.root))

    def _status(self, repo: Repo) -> dict[str, Any]:
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
        return {"changes": changes, "clean": not changes}

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
            remotes.append({"name": section[1].decode("utf-8"), "url": url})
        return sorted(remotes, key=lambda item: item["name"])

    def _remote_url(self, repo: Repo, name: str) -> str:
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

    def _store_remote_tracking_ref(
        self,
        repo: Repo,
        remote: str,
        refs: dict[bytes, bytes],
    ) -> None:
        branch = self._active_branch(repo)
        if not branch:
            return
        remote_head = refs.get(f"refs/heads/{branch}".encode("utf-8"))
        if remote_head is not None:
            repo.refs[f"refs/remotes/{remote}/{branch}".encode("utf-8")] = remote_head

    @staticmethod
    def _credentials(url: str, token: str | None) -> dict[str, str]:
        if url.startswith("https://github.com/") and token:
            return {"username": "x-access-token", "password": token}
        return {}

    @staticmethod
    def _normalize_path(path: str) -> str:
        normalized = path.strip().replace("\\", "/").strip("/")
        parts = Path(normalized).parts
        if not normalized or Path(normalized).is_absolute() or ".." in parts or ".git" in parts:
            raise GitRepositoryError("文件路径必须位于当前项目内，且不能指向 .git。")
        return normalized

    @staticmethod
    def _decode_path(path: bytes | str) -> str:
        value = path.decode("utf-8", errors="replace") if isinstance(path, bytes) else path
        return value.replace("\\", "/")

    @staticmethod
    def _friendly_error(exc: Exception) -> str:
        message = str(exc).strip()
        return message or "Git 操作失败。"
