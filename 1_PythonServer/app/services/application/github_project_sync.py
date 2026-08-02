from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any, Iterable

from app.core.errors import BadRequestError
from app.domain.github_sync import GithubSyncFile
from app.repositories.project import ProjectRepository
from app.services.application.github_sync_snapshot import (
    LocalSnapshot,
    LocalSnapshotFile,
    require_safe_relative_path,
)


CATALOG_PATH = "catalog.json"
UNCATEGORIZED_ID = "__uncategorized__"


def parse_catalog(content: bytes | None, *, label: str) -> dict[str, Any]:
    if content is None:
        return _empty_catalog()
    try:
        payload = json.loads(content.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BadRequestError(f"{label} catalog.json 格式无效。") from exc
    if not isinstance(payload, dict):
        raise BadRequestError(f"{label} catalog.json 格式无效。")
    if not isinstance(payload.get("categories"), list) or not isinstance(payload.get("projects"), list):
        raise BadRequestError(f"{label} catalog.json 缺少分类或项目列表。")
    return payload


def catalog_bytes(catalog: dict[str, Any]) -> bytes:
    return (json.dumps(catalog, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def project_ids_from_paths(paths: Iterable[str]) -> tuple[str, ...]:
    project_ids: set[str] = set()
    for value in paths:
        path = require_safe_relative_path(value)
        if path == CATALOG_PATH:
            continue
        project_ids.add(path.split("/", 1)[0])
    return tuple(sorted(project_ids))


def merge_portable_catalog(
    *,
    local: dict[str, Any],
    remote: dict[str, Any],
    selected_project_ids: Iterable[str],
    direction: str,
) -> dict[str, Any]:
    source = local if direction == "push" else remote
    base = deepcopy(remote if direction == "push" else local)
    selected = set(selected_project_ids)
    source_projects = _items_by_id(source.get("projects", []), "project_id")
    base_projects = _items_by_id(base.get("projects", []), "project_id")
    for project_id in selected:
        item = source_projects.get(project_id)
        if item is None:
            base_projects.pop(project_id, None)
        else:
            base_projects[project_id] = deepcopy(item)
    base["projects"] = _ordered_items(base.get("projects", []), base_projects, "project_id")

    source_categories = _items_by_id(source.get("categories", []), "category_id")
    base_categories = _items_by_id(base.get("categories", []), "category_id")
    for project_id in selected:
        project = source_projects.get(project_id)
        category_id = project.get("category_id") if project else None
        if isinstance(category_id, str) and category_id in source_categories:
            base_categories[category_id] = deepcopy(source_categories[category_id])
    base["categories"] = _ordered_items(
        base.get("categories", []), base_categories, "category_id"
    )
    base.setdefault("schema_version", 1)
    base.setdefault("metadata", {})
    return base


def merge_local_catalog_for_pull(
    *,
    raw_local: dict[str, Any],
    remote: dict[str, Any],
    selected_project_ids: Iterable[str],
    projects_root: Path,
) -> dict[str, Any]:
    result = deepcopy(raw_local)
    selected = set(selected_project_ids)
    local_projects = _items_by_id(result.get("projects", []), "project_id")
    remote_projects = _items_by_id(remote.get("projects", []), "project_id")
    for project_id in selected:
        remote_item = remote_projects.get(project_id)
        if remote_item is None:
            local_projects.pop(project_id, None)
            continue
        existing = local_projects.get(project_id, {})
        merged = deepcopy(remote_item)
        root_path = existing.get("root_path")
        root_name = existing.get("root_name")
        if isinstance(root_path, str) and root_path.strip():
            merged["root_path"] = root_path
        else:
            merged["root_path"] = str((projects_root / project_id).resolve())
            merged["root_name"] = project_id
        if isinstance(root_name, str) and root_name.strip():
            merged["root_name"] = root_name
        local_projects[project_id] = merged
    result["projects"] = _ordered_items(
        result.get("projects", []), local_projects, "project_id"
    )

    remote_categories = _items_by_id(remote.get("categories", []), "category_id")
    local_categories = _items_by_id(result.get("categories", []), "category_id")
    for project_id in selected:
        remote_item = remote_projects.get(project_id)
        category_id = remote_item.get("category_id") if remote_item else None
        if isinstance(category_id, str) and category_id in remote_categories:
            local_categories[category_id] = deepcopy(remote_categories[category_id])
    result["categories"] = _ordered_items(
        result.get("categories", []), local_categories, "category_id"
    )
    result.setdefault("schema_version", 1)
    result.setdefault("metadata", {})
    return result


def with_catalog(snapshot: LocalSnapshot, content: bytes) -> LocalSnapshot:
    from app.services.application.github_sync_snapshot import git_blob_sha

    files = dict(snapshot.files)
    files[CATALOG_PATH] = LocalSnapshotFile(
        path=CATALOG_PATH,
        size=len(content),
        sha=git_blob_sha(content),
        content=content,
    )
    return LocalSnapshot(files=files, fingerprint=snapshot.fingerprint)


def remote_with_catalog(
    remote: dict[str, GithubSyncFile],
    content: bytes,
) -> dict[str, GithubSyncFile]:
    from app.services.application.github_sync_snapshot import git_blob_sha

    files = dict(remote)
    files[CATALOG_PATH] = GithubSyncFile(
        path=CATALOG_PATH,
        size=len(content),
        sha=git_blob_sha(content),
    )
    return files


def build_board(
    *,
    local: LocalSnapshot,
    remote: dict[str, GithubSyncFile],
    local_catalog: dict[str, Any],
    remote_catalog: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    local_projects = _items_by_id(local_catalog.get("projects", []), "project_id")
    remote_projects = _items_by_id(remote_catalog.get("projects", []), "project_id")
    project_ids = set(local_projects) | set(remote_projects)
    for path in set(local.files) | set(remote):
        if path != CATALOG_PATH and "/" in path:
            project_ids.add(path.split("/", 1)[0])

    project_rows: list[dict[str, Any]] = []
    changed_total = 0
    for project_id in sorted(project_ids, key=lambda item: _project_sort_key(
        item, local_projects, remote_projects
    )):
        local_item = local_projects.get(project_id)
        remote_item = remote_projects.get(project_id)
        item = local_item or remote_item or {}
        prefix = f"{project_id}/"
        file_rows: list[dict[str, Any]] = []
        for path in sorted(
            candidate for candidate in set(local.files) | set(remote) if candidate.startswith(prefix)
        ):
            local_file = local.files.get(path)
            remote_file = remote.get(path)
            if local_file and remote_file:
                status = "same" if local_file.sha == remote_file.sha else "different"
            elif local_file:
                status = "local-only"
            else:
                status = "remote-only"
            if status == "same":
                continue
            changed_total += 1
            file_rows.append({
                "path": path,
                "projectId": project_id,
                "relativePath": path[len(prefix):],
                "status": status,
                "localSize": local_file.size if local_file else None,
                "remoteSize": remote_file.size if remote_file else None,
            })
        location = "both" if local_item and remote_item else "local" if local_item else "remote"
        project_rows.append({
            "projectId": project_id,
            "name": str(item.get("name") or project_id),
            "categoryId": item.get("category_id") if isinstance(item.get("category_id"), str) else None,
            "location": location,
            "changedFiles": sum(row["status"] != "same" for row in file_rows),
            "files": file_rows,
        })

    local_categories = _items_by_id(local_catalog.get("categories", []), "category_id")
    remote_categories = _items_by_id(remote_catalog.get("categories", []), "category_id")
    category_ids = set(local_categories) | set(remote_categories)
    if any(row["categoryId"] is None for row in project_rows):
        category_ids.add(UNCATEGORIZED_ID)
    category_rows: list[dict[str, Any]] = []
    for category_id in sorted(category_ids, key=lambda item: _category_sort_key(
        item, local_categories, remote_categories
    )):
        item = local_categories.get(category_id) or remote_categories.get(category_id) or {}
        project_ids_in_category = [
            row["projectId"] for row in project_rows
            if (row["categoryId"] or UNCATEGORIZED_ID) == category_id
        ]
        category_rows.append({
            "categoryId": category_id,
            "name": "未分类" if category_id == UNCATEGORIZED_ID else str(item.get("name") or category_id),
            "projectIds": project_ids_in_category,
            "changedFiles": sum(
                row["changedFiles"] for row in project_rows
                if row["projectId"] in project_ids_in_category
            ),
        })
    return category_rows, project_rows, changed_total


def local_project_target(
    *,
    projects_root: Path,
    project_repository: ProjectRepository,
    logical_path: str,
) -> Path:
    safe_path = require_safe_relative_path(logical_path)
    if safe_path == CATALOG_PATH:
        return (projects_root / CATALOG_PATH).resolve()
    project_id, separator, relative_path = safe_path.partition("/")
    if not separator or not relative_path:
        raise BadRequestError("项目同步文件缺少项目目录。")
    project = project_repository.get_project(project_id)
    project_root = Path(project.root_path).resolve() if project else (projects_root / project_id).resolve()
    target = project_root.joinpath(*relative_path.split("/")).resolve()
    try:
        target.relative_to(project_root)
    except ValueError as exc:
        raise BadRequestError("项目同步文件路径越过项目根目录。") from exc
    if target.is_symlink():
        raise BadRequestError("项目同步目标不能是符号链接。")
    return target


def _empty_catalog() -> dict[str, Any]:
    return {"schema_version": 1, "metadata": {}, "categories": [], "projects": []}


def _items_by_id(items: object, field: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    if not isinstance(items, list):
        return result
    for item in items:
        if not isinstance(item, dict):
            continue
        value = item.get(field)
        if isinstance(value, str) and value:
            result[value] = item
    return result


def _ordered_items(
    previous: object,
    current: dict[str, dict[str, Any]],
    field: str,
) -> list[dict[str, Any]]:
    ordered_ids = [
        item.get(field) for item in previous if isinstance(item, dict)
    ] if isinstance(previous, list) else []
    result = [deepcopy(current[item_id]) for item_id in ordered_ids if item_id in current]
    known = {item.get(field) for item in result}
    result.extend(
        deepcopy(item) for item_id, item in sorted(
            current.items(), key=lambda pair: (pair[1].get("sort_order", 0), pair[0])
        ) if item_id not in known
    )
    return result


def _project_sort_key(
    project_id: str,
    local: dict[str, dict[str, Any]],
    remote: dict[str, dict[str, Any]],
) -> tuple[int, str]:
    item = local.get(project_id) or remote.get(project_id) or {}
    return int(item.get("sort_order", 0) or 0), str(item.get("name") or project_id)


def _category_sort_key(
    category_id: str,
    local: dict[str, dict[str, Any]],
    remote: dict[str, dict[str, Any]],
) -> tuple[int, str]:
    if category_id == UNCATEGORIZED_ID:
        return 2**31 - 1, category_id
    item = local.get(category_id) or remote.get(category_id) or {}
    return int(item.get("sort_order", 0) or 0), str(item.get("name") or category_id)
