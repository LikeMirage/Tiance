from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
from typing import Iterable

from app.core.config import Settings
from app.core.errors import BadRequestError, ConflictError
from app.domain.project import ProjectKind
from app.repositories.project import ProjectRepository


MAX_SYNC_FILES = 20_000
MAX_SYNC_FILE_BYTES = 100 * 1024 * 1024
GITHUB_SYNC_TOOL_ID = "c44767b0-4693-4647-9542-c158402ce8a6"
LOCAL_ONLY_DIRECTORY_NAMES = frozenset({
    ".cache",
    ".codex_tmp",
    ".git",
    ".market-cache",
    ".pytest_cache",
    ".trash",
    ".venv",
    "__pycache__",
    "dependencies",
    "node_modules",
    "venv",
})


@dataclass(frozen=True, slots=True)
class LocalSnapshotFile:
    path: str
    size: int
    sha: str
    source_path: Path | None = None
    content: bytes | None = None

    def read_bytes(self) -> bytes:
        if self.content is not None:
            return self.content
        if self.source_path is None:
            raise RuntimeError("同步文件没有内容来源。")
        try:
            content = self.source_path.read_bytes()
        except OSError as exc:
            raise ConflictError(f"同步文件 '{self.path}' 已无法读取，请重新生成计划。") from exc
        if _git_blob_sha(content) != self.sha:
            raise ConflictError(f"同步文件 '{self.path}' 已发生变化，请重新生成计划。")
        return content


@dataclass(frozen=True, slots=True)
class LocalSnapshot:
    files: dict[str, LocalSnapshotFile]
    fingerprint: str


def collection_root(settings: Settings, collection: ProjectKind) -> Path:
    return {
        ProjectKind.PROJECT: settings.projects_data_path,
        ProjectKind.KNOWLEDGE: settings.knowledge_data_path,
        ProjectKind.EXPERIENCE: settings.experience_data_path,
        ProjectKind.ROLE: settings.roles_data_path,
        ProjectKind.THEME: settings.themes_data_path,
        ProjectKind.TOOL: settings.tools_data_path,
        ProjectKind.PROVIDER: settings.providers_data_path,
    }[collection].resolve()


def build_local_snapshot(
    *,
    settings: Settings,
    project_repository: ProjectRepository,
    collection: ProjectKind,
) -> LocalSnapshot:
    root = collection_root(settings, collection)
    files = (
        _portable_project_files(root, project_repository)
        if collection is ProjectKind.PROJECT
        else _walk_files(root, collection=collection)
    )
    if len(files) > MAX_SYNC_FILES:
        raise BadRequestError(f"当前集合包含超过 {MAX_SYNC_FILES} 个文件，无法安全同步。")
    ordered = dict(sorted(files.items()))
    fingerprint = hashlib.sha256()
    for path, item in ordered.items():
        fingerprint.update(path.encode("utf-8"))
        fingerprint.update(b"\0")
        fingerprint.update(item.sha.encode("ascii"))
        fingerprint.update(b"\0")
        fingerprint.update(str(item.size).encode("ascii"))
        fingerprint.update(b"\n")
    return LocalSnapshot(files=ordered, fingerprint=fingerprint.hexdigest())


def normalize_remote_path(value: str) -> str:
    normalized = value.strip().replace("\\", "/").strip("/")
    if not normalized:
        return ""
    path = PurePosixPath(normalized)
    if path.is_absolute() or ".." in path.parts or any(not part for part in path.parts):
        raise BadRequestError("远端目录无效。")
    return path.as_posix()


def join_remote_path(remote_path: str, local_path: str) -> str:
    return f"{remote_path}/{local_path}" if remote_path else local_path


def strip_remote_path(remote_path: str, repository_path: str) -> str | None:
    if not remote_path:
        return repository_path
    prefix = remote_path + "/"
    return repository_path[len(prefix):] if repository_path.startswith(prefix) else None


def require_safe_relative_path(value: str) -> str:
    normalized = value.replace("\\", "/").strip("/")
    path = PurePosixPath(normalized)
    if not normalized or path.is_absolute() or ".." in path.parts:
        raise BadRequestError("GitHub 仓库包含不安全的文件路径。")
    return path.as_posix()


def _portable_project_files(
    root: Path,
    project_repository: ProjectRepository,
) -> dict[str, LocalSnapshotFile]:
    root.mkdir(parents=True, exist_ok=True)
    try:
        raw_catalog = json.loads((root / "catalog.json").read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        raw_catalog = {"schema_version": 1, "metadata": {}, "categories": [], "projects": []}
    except (OSError, json.JSONDecodeError) as exc:
        raise BadRequestError("项目集 catalog.json 无法读取。") from exc
    if not isinstance(raw_catalog, dict) or not isinstance(raw_catalog.get("projects"), list):
        raise BadRequestError("项目集 catalog.json 格式无效。")

    projects = {
        project.project_id: project
        for project in project_repository.list_projects()
        if project.project_kind is ProjectKind.PROJECT
    }
    portable_projects: list[dict] = []
    files: dict[str, LocalSnapshotFile] = {}
    managed_top_levels: set[str] = set()
    for raw_item in raw_catalog["projects"]:
        if not isinstance(raw_item, dict):
            raise BadRequestError("项目集 catalog.json 包含无效项目。")
        project_id = raw_item.get("project_id")
        project = projects.get(project_id) if isinstance(project_id, str) else None
        if project is None:
            raise BadRequestError("项目集索引与项目目录不一致，请先刷新项目集。")
        portable_item = dict(raw_item)
        portable_item.pop("root_path", None)
        portable_item.pop("root_name", None)
        portable_projects.append(portable_item)
        project_root = Path(project.root_path).resolve()
        if project_root.parent == root:
            managed_top_levels.add(project_root.name)
        for relative_path, source_path in _iter_regular_files(project_root):
            _add_source_file(files, f"{project.project_id}/{relative_path}", source_path)

    portable_catalog = dict(raw_catalog)
    portable_catalog["projects"] = portable_projects
    content = (json.dumps(portable_catalog, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    files["catalog.json"] = LocalSnapshotFile(
        path="catalog.json",
        size=len(content),
        sha=_git_blob_sha(content),
        content=content,
    )
    for path, source_path in _iter_regular_files(root):
        if path == "catalog.json":
            continue
        top_level = path.split("/", 1)[0]
        if top_level in managed_top_levels:
            continue
        _add_source_file(files, path, source_path)
    return files


def _walk_files(root: Path, *, collection: ProjectKind) -> dict[str, LocalSnapshotFile]:
    root.mkdir(parents=True, exist_ok=True)
    files: dict[str, LocalSnapshotFile] = {}
    for relative_path, source_path in _iter_regular_files(root):
        if (
            collection is ProjectKind.TOOL
            and relative_path == f"{GITHUB_SYNC_TOOL_ID}/program/config.json"
        ):
            continue
        _add_source_file(files, relative_path, source_path)
    return files


def _iter_regular_files(root: Path) -> Iterable[tuple[str, Path]]:
    if not root.is_dir():
        return
    for current, directories, file_names in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        directories[:] = sorted(
            name
            for name in directories
            if name.casefold() not in LOCAL_ONLY_DIRECTORY_NAMES
            and not (current_path / name).is_symlink()
        )
        for file_name in sorted(file_names):
            path = current_path / file_name
            if path.is_symlink() or file_name.startswith("~$"):
                # Office 锁文件和文件链接都不是稳定的跨设备同步事实。
                continue
            yield path.relative_to(root).as_posix(), path


def _add_source_file(
    files: dict[str, LocalSnapshotFile],
    logical_path: str,
    source_path: Path,
) -> None:
    safe_path = require_safe_relative_path(logical_path)
    if safe_path in files:
        raise BadRequestError(f"同步快照包含重复路径 '{safe_path}'。")
    try:
        size = source_path.stat().st_size
    except OSError as exc:
        raise BadRequestError(f"无法读取同步文件 '{safe_path}'。") from exc
    if size > MAX_SYNC_FILE_BYTES:
        raise BadRequestError(f"同步文件 '{safe_path}' 超过 GitHub 单文件大小限制。")
    try:
        content = source_path.read_bytes()
    except OSError as exc:
        raise BadRequestError(f"无法读取同步文件 '{safe_path}'。") from exc
    files[safe_path] = LocalSnapshotFile(
        path=safe_path,
        size=size,
        sha=_git_blob_sha(content),
        source_path=source_path,
    )


def _git_blob_sha(content: bytes) -> str:
    header = f"blob {len(content)}\0".encode("ascii")
    return hashlib.sha1(header + content, usedforsecurity=False).hexdigest()
