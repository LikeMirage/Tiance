from __future__ import annotations

from contextlib import suppress
import json
from pathlib import Path
import re
from uuid import uuid4

from app.core.atomic_replace import atomic_replace_path


_LEGACY_ROOT_NAME = "literature"
_LEGACY_CATEGORY_ID = "default-literature-category"
_KNOWLEDGE_CATEGORY_ID = "default-knowledge-category"
_GENERATED_PROJECT_NAME = re.compile(r"^新建文献(?P<suffix> \d+)?$")


def migrate_knowledge_workspace(knowledge_root: Path) -> None:
    """把旧文献集目录一次性迁为知识集目录。"""

    resolved_root = knowledge_root.resolve()
    legacy_root = resolved_root.with_name(_LEGACY_ROOT_NAME)
    if legacy_root.exists():
        if not legacy_root.is_dir():
            raise RuntimeError("旧文献集路径不是文件夹，无法迁移为知识集。")
        if resolved_root.exists():
            if not _remove_empty_generated_knowledge_root(resolved_root):
                raise RuntimeError("知识集新旧目录同时存在，已停止自动迁移以避免覆盖数据。")
        legacy_root.rename(resolved_root)

    _migrate_catalog(resolved_root / "catalog.json")


def _remove_empty_generated_knowledge_root(knowledge_root: Path) -> bool:
    if not knowledge_root.is_dir():
        return False
    children = tuple(knowledge_root.iterdir())
    if not children:
        knowledge_root.rmdir()
        return True
    if len(children) != 1 or children[0].name != "catalog.json":
        return False
    try:
        payload = json.loads(children[0].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(payload, dict) or payload.get("projects") != []:
        return False
    categories = payload.get("categories")
    if not isinstance(categories, list) or any(
        not isinstance(category, dict)
        or category.get("category_id") != _KNOWLEDGE_CATEGORY_ID
        for category in categories
    ):
        return False
    children[0].unlink()
    knowledge_root.rmdir()
    return True


def _migrate_catalog(catalog_path: Path) -> None:
    if not catalog_path.is_file():
        return
    try:
        payload = json.loads(catalog_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("旧文献集 catalog.json 无法读取，已停止迁移。") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("旧文献集 catalog.json 格式无效，已停止迁移。")

    changed = False
    categories = payload.get("categories")
    if isinstance(categories, list):
        for category in categories:
            if not isinstance(category, dict):
                continue
            if category.get("category_id") != _LEGACY_CATEGORY_ID:
                continue
            category["category_id"] = _KNOWLEDGE_CATEGORY_ID
            if category.get("name") == "基础文献":
                category["name"] = "基础知识"
            changed = True

    projects = payload.get("projects")
    if isinstance(projects, list):
        for project in projects:
            if not isinstance(project, dict):
                continue
            if project.get("category_id") == _LEGACY_CATEGORY_ID:
                project["category_id"] = _KNOWLEDGE_CATEGORY_ID
                changed = True
            name = project.get("name")
            match = _GENERATED_PROJECT_NAME.fullmatch(name) if isinstance(name, str) else None
            if match is not None:
                project["name"] = f"新建知识{match.group('suffix') or ''}"
                changed = True

    if not changed:
        return
    temporary_path = catalog_path.with_name(f".{catalog_path.name}.{uuid4().hex}.tmp")
    try:
        temporary_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        atomic_replace_path(temporary_path, catalog_path)
    finally:
        with suppress(OSError):
            temporary_path.unlink(missing_ok=True)
