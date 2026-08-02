from __future__ import annotations

from contextlib import suppress
from json import dumps, loads
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import RLock

from app.core.atomic_replace import atomic_replace_path
from app.domain.project import Project, ProjectCategory, ProjectKind


CATALOG_FILE_NAME = "catalog.json"
CATALOG_SCHEMA_VERSION = 1


class FileProjectCatalog:
    """文件式项目集目录；分类是逻辑记录，项目目录始终直接位于集合根目录。"""

    def __init__(
        self,
        root_path: Path,
        *,
        project_kind: ProjectKind,
        allow_external_roots: bool = False,
    ) -> None:
        self._root_path = root_path.resolve()
        self._project_kind = project_kind
        self._allow_external_roots = allow_external_roots
        self._catalog_path = self._root_path / CATALOG_FILE_NAME
        self._write_lock = RLock()

    @property
    def root_path(self) -> Path:
        return self._root_path

    @property
    def project_kind(self) -> ProjectKind:
        return self._project_kind

    @property
    def catalog_path(self) -> Path:
        return self._catalog_path

    def exists(self) -> bool:
        return self._catalog_path.is_file()

    def list_projects(self) -> tuple[Project, ...]:
        payload = self._read_payload()
        projects = tuple(self._project_from_payload(item) for item in payload["projects"])
        category_ids = {
            self._category_from_payload(item).category_id
            for item in payload["categories"]
        }
        for project in projects:
            if project.category_id not in category_ids:
                raise ValueError(
                    f"项目 '{project.project_id}' 指向不存在的分类 '{project.category_id}'。"
                )
        return tuple(sorted(projects, key=_project_sort_key))

    def get_project(self, project_id: str) -> Project | None:
        normalized = project_id.strip()
        return next(
            (item for item in self.list_projects() if item.project_id == normalized),
            None,
        )

    def get_project_by_root_path(self, root_path: str) -> Project | None:
        normalized = Path(root_path).resolve()
        return next(
            (
                item
                for item in self.list_projects()
                if Path(item.root_path).resolve() == normalized
            ),
            None,
        )

    def save_project(self, project: Project) -> Project:
        self._require_project_kind(project.project_kind)
        self._require_safe_identifier(project.project_id, label="项目")
        self._validate_project_root(project)
        with self._write_lock:
            payload = self._read_payload()
            category_ids = {
                self._category_from_payload(item).category_id
                for item in payload["categories"]
            }
            if project.category_id not in category_ids:
                raise ValueError(f"项目分类 '{project.category_id}' 不存在。")
            projects = [
                self._project_from_payload(item)
                for item in payload["projects"]
                if self._project_from_payload(item).project_id != project.project_id
            ]
            projects.append(project)
            payload["projects"] = [
                self._project_to_payload(item)
                for item in sorted(projects, key=_project_sort_key)
            ]
            self._write_payload(payload)
        return project

    def delete_project(self, project_id: str) -> None:
        normalized = project_id.strip()
        with self._write_lock:
            payload = self._read_payload()
            payload["projects"] = [
                item
                for item in payload["projects"]
                if self._project_from_payload(item).project_id != normalized
            ]
            self._write_payload(payload)

    def list_project_categories(self) -> tuple[ProjectCategory, ...]:
        payload = self._read_payload()
        categories = tuple(
            self._category_from_payload(item)
            for item in payload["categories"]
        )
        default_count = sum(1 for item in categories if item.is_default)
        if default_count > 1:
            raise ValueError("文件式项目集只能有一个默认分类。")
        return tuple(sorted(categories, key=_category_sort_key))

    def get_project_category(self, category_id: str) -> ProjectCategory | None:
        normalized = category_id.strip()
        return next(
            (
                item
                for item in self.list_project_categories()
                if item.category_id == normalized
            ),
            None,
        )

    def get_project_category_by_name(self, name: str) -> ProjectCategory | None:
        normalized = name.strip().casefold()
        return next(
            (
                item
                for item in self.list_project_categories()
                if item.name.casefold() == normalized
            ),
            None,
        )

    def save_project_category(self, category: ProjectCategory) -> ProjectCategory:
        self._require_project_kind(category.category_kind)
        self._require_safe_identifier(category.category_id, label="项目分类")
        with self._write_lock:
            payload = self._read_payload()
            categories = [
                self._category_from_payload(item)
                for item in payload["categories"]
                if self._category_from_payload(item).category_id != category.category_id
            ]
            if category.is_default and any(item.is_default for item in categories):
                raise ValueError("文件式项目集只能有一个默认分类。")
            categories.append(category)
            payload["categories"] = [
                self._category_to_payload(item)
                for item in sorted(categories, key=_category_sort_key)
            ]
            self._write_payload(payload)
        return category

    def delete_project_category(self, category_id: str) -> None:
        normalized = category_id.strip()
        with self._write_lock:
            payload = self._read_payload()
            if any(
                self._project_from_payload(item).category_id == normalized
                for item in payload["projects"]
            ):
                raise ValueError("仍有项目属于此分类，不能直接删除。")
            payload["categories"] = [
                item
                for item in payload["categories"]
                if self._category_from_payload(item).category_id != normalized
            ]
            self._write_payload(payload)

    def delete_project_category_with_projects(self, category_id: str) -> None:
        """一次写入同时移除分类及其项目索引，避免留下悬空记录。"""
        normalized = category_id.strip()
        with self._write_lock:
            payload = self._read_payload()
            payload["projects"] = [
                item
                for item in payload["projects"]
                if self._project_from_payload(item).category_id != normalized
            ]
            payload["categories"] = [
                item
                for item in payload["categories"]
                if self._category_from_payload(item).category_id != normalized
            ]
            self._write_payload(payload)

    def move_projects_to_category(
        self,
        *,
        source_category_id: str,
        target_category_id: str,
        updated_at: str,
    ) -> None:
        with self._write_lock:
            payload = self._read_payload()
            if not any(
                self._category_from_payload(item).category_id == target_category_id
                for item in payload["categories"]
            ):
                raise ValueError(f"目标项目分类 '{target_category_id}' 不存在。")
            payload["projects"] = [
                self._project_to_payload(
                    _move_project_category(
                        self._project_from_payload(item),
                        source_category_id=source_category_id,
                        target_category_id=target_category_id,
                        updated_at=updated_at,
                    )
                )
                for item in payload["projects"]
            ]
            self._write_payload(payload)

    def next_project_category_sort_order(self) -> int:
        values = [item.sort_order for item in self.list_project_categories()]
        return max(values, default=-1) + 1

    def save_category_order(self, category_ids: tuple[str, ...]) -> tuple[str, ...]:
        with self._write_lock:
            payload = self._read_payload()
            categories = [
                self._category_from_payload(item)
                for item in payload["categories"]
            ]
            rank = {category_id: index for index, category_id in enumerate(category_ids)}
            categories.sort(key=lambda category: (
                rank.get(category.category_id, len(rank) + category.sort_order),
                category.sort_order,
                category.created_at,
                category.category_id,
            ))
            normalized = [
                _replace_category_sort_order(category, sort_order=sort_order)
                for sort_order, category in enumerate(categories)
            ]
            payload["categories"] = [
                self._category_to_payload(category)
                for category in normalized
            ]
            self._write_payload(payload)
        return tuple(category.category_id for category in normalized)

    def next_project_sort_order(self) -> int:
        values = [item.sort_order for item in self.list_projects()]
        return max(values, default=-1) + 1

    def get_metadata_value(self, key: str) -> str | None:
        value = self._read_payload()["metadata"].get(key)
        return value if isinstance(value, str) else None

    def set_metadata_value(self, *, key: str, value: str) -> None:
        with self._write_lock:
            payload = self._read_payload()
            payload["metadata"][key] = value
            self._write_payload(payload)

    def save_project_order(self, project_ids: tuple[str, ...]) -> tuple[str, ...]:
        """按分类保存项目顺序；调用方可以传入包含其他项目集 ID 的总顺序。"""
        with self._write_lock:
            payload = self._read_payload()
            projects = [self._project_from_payload(item) for item in payload["projects"]]
            rank = {project_id: index for index, project_id in enumerate(project_ids)}
            ordered_projects: list[Project] = []
            ordered_ids: list[str] = []
            categories = [
                self._category_from_payload(item)
                for item in payload["categories"]
            ]
            for category in sorted(categories, key=_category_sort_key):
                category_projects = sorted(
                    (
                        project
                        for project in projects
                        if project.category_id == category.category_id
                    ),
                    key=lambda project: (
                        rank.get(project.project_id, len(rank) + project.sort_order),
                        project.sort_order,
                        project.created_at,
                        project.project_id,
                    ),
                )
                for sort_order, project in enumerate(category_projects):
                    ordered_projects.append(
                        _replace_project_sort_order(project, sort_order=sort_order)
                    )
                    ordered_ids.append(project.project_id)
            payload["projects"] = [
                self._project_to_payload(item)
                for item in sorted(ordered_projects, key=_project_sort_key)
            ]
            self._write_payload(payload)
        return tuple(ordered_ids)

    def _read_payload(self) -> dict:
        if not self._catalog_path.is_file():
            return {
                "schema_version": CATALOG_SCHEMA_VERSION,
                "metadata": {},
                "categories": [],
                "projects": [],
            }
        raw = loads(self._catalog_path.read_text(encoding="utf-8-sig"))
        if not isinstance(raw, dict):
            raise ValueError("项目集 catalog.json 必须是 JSON 对象。")
        if raw.get("schema_version") != CATALOG_SCHEMA_VERSION:
            raise ValueError("项目集 catalog.json 版本不受支持。")
        categories = raw.get("categories")
        projects = raw.get("projects")
        metadata = raw.get("metadata")
        if not isinstance(metadata, dict) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in metadata.items()
        ):
            raise ValueError("项目集 metadata 必须是字符串键值对象。")
        if not isinstance(categories, list) or not all(
            isinstance(item, dict) for item in categories
        ):
            raise ValueError("项目集 categories 必须是对象数组。")
        if not isinstance(projects, list) or not all(
            isinstance(item, dict) for item in projects
        ):
            raise ValueError("项目集 projects 必须是对象数组。")
        return {
            "schema_version": CATALOG_SCHEMA_VERSION,
            "metadata": metadata,
            "categories": categories,
            "projects": projects,
        }

    def _write_payload(self, payload: dict[str, object]) -> None:
        self._root_path.mkdir(parents=True, exist_ok=True)
        text = dumps(payload, ensure_ascii=False, indent=2) + "\n"
        temporary_path: Path | None = None
        try:
            with NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=self._root_path,
                delete=False,
                prefix=".catalog.",
                suffix=".tmp",
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                temporary_file.write(text)
            atomic_replace_path(temporary_path, self._catalog_path)
        except Exception:
            if temporary_path is not None:
                with suppress(OSError):
                    temporary_path.unlink()
            raise

    def _project_from_payload(self, payload: dict[str, object]) -> Project:
        project_id = _required_string(payload, "project_id")
        self._require_safe_identifier(project_id, label="项目")
        external_root_path = _optional_string(payload, "root_path")
        if external_root_path is not None:
            if not self._allow_external_roots:
                raise ValueError("当前项目集不允许登记外部项目目录。")
            root_path = Path(external_root_path).expanduser().resolve()
        else:
            root_name = _optional_string(payload, "root_name") or project_id
            self._require_safe_identifier(root_name, label="项目目录")
            root_path = self._project_root(project_id, root_name=root_name)
        return Project(
            project_id=project_id,
            name=_required_string(payload, "name"),
            root_path=str(root_path),
            category_id=_required_string(payload, "category_id"),
            project_kind=self._project_kind,
            is_default=_required_bool(payload, "is_default"),
            sort_order=_required_int(payload, "sort_order"),
            created_at=_required_string(payload, "created_at"),
            updated_at=_required_string(payload, "updated_at"),
        )

    def _category_from_payload(self, payload: dict[str, object]) -> ProjectCategory:
        category_id = _required_string(payload, "category_id")
        self._require_safe_identifier(category_id, label="项目分类")
        return ProjectCategory(
            category_id=category_id,
            name=_required_string(payload, "name"),
            category_kind=self._project_kind,
            is_default=_required_bool(payload, "is_default"),
            sort_order=_required_int(payload, "sort_order"),
            created_at=_required_string(payload, "created_at"),
            updated_at=_required_string(payload, "updated_at"),
        )

    def _project_to_payload(self, project: Project) -> dict[str, object]:
        payload: dict[str, object] = {
            "project_id": project.project_id,
            "name": project.name,
            "category_id": project.category_id,
            "is_default": project.is_default,
            "sort_order": project.sort_order,
            "created_at": project.created_at,
            "updated_at": project.updated_at,
        }
        root_name = self._managed_project_root_name(project)
        if root_name is None:
            payload["root_path"] = str(Path(project.root_path).expanduser().resolve())
        elif root_name != project.project_id:
            payload["root_name"] = root_name
        return payload

    @staticmethod
    def _category_to_payload(category: ProjectCategory) -> dict[str, object]:
        return {
            "category_id": category.category_id,
            "name": category.name,
            "is_default": category.is_default,
            "sort_order": category.sort_order,
            "created_at": category.created_at,
            "updated_at": category.updated_at,
        }

    def _project_root(self, project_id: str, *, root_name: str | None = None) -> Path:
        return (self._root_path / (root_name or project_id)).resolve()

    def _managed_project_root_name(self, project: Project) -> str | None:
        root_path = Path(project.root_path).resolve()
        try:
            relative_path = root_path.relative_to(self._root_path)
        except ValueError:
            return None
        if len(relative_path.parts) != 1:
            raise ValueError("文件式项目根目录必须是项目集根目录的直接子目录。")
        root_name = relative_path.name
        self._require_safe_identifier(root_name, label="项目目录")
        return root_name

    def _validate_project_root(self, project: Project) -> None:
        root_name = self._managed_project_root_name(project)
        if root_name is not None:
            return
        if not self._allow_external_roots:
            raise ValueError(
                f"文件式项目根目录必须位于 '{self._root_path}'。"
            )

    def _require_project_kind(self, project_kind: ProjectKind) -> None:
        if project_kind is not self._project_kind:
            raise ValueError(
                f"项目类型必须是 '{self._project_kind.value}'。"
            )

    @staticmethod
    def _require_safe_identifier(value: str, *, label: str) -> None:
        if not value or value in {".", ".."} or any(char in value for char in "\\/"):
            raise ValueError(f"{label} ID 无效。")


def _required_string(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"项目集字段 '{key}' 必须是非空字符串。")
    return value.strip()


def _required_bool(payload: dict[str, object], key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise ValueError(f"项目集字段 '{key}' 必须是布尔值。")
    return value


def _optional_string(payload: dict[str, object], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"项目集字段 '{key}' 必须是非空字符串。")
    return value.strip()


def _required_int(payload: dict[str, object], key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"项目集字段 '{key}' 必须是整数。")
    return value


def _project_sort_key(project: Project) -> tuple[int, str, str]:
    return project.sort_order, project.created_at, project.project_id


def _category_sort_key(category: ProjectCategory) -> tuple[int, str, str]:
    return category.sort_order, category.created_at, category.category_id


def _move_project_category(
    project: Project,
    *,
    source_category_id: str,
    target_category_id: str,
    updated_at: str,
) -> Project:
    if project.category_id != source_category_id:
        return project
    return Project(
        project_id=project.project_id,
        name=project.name,
        root_path=project.root_path,
        category_id=target_category_id,
        project_kind=project.project_kind,
        is_default=project.is_default,
        sort_order=project.sort_order,
        created_at=project.created_at,
        updated_at=updated_at,
    )


def _replace_project_sort_order(project: Project, *, sort_order: int) -> Project:
    return Project(
        project_id=project.project_id,
        name=project.name,
        root_path=project.root_path,
        category_id=project.category_id,
        project_kind=project.project_kind,
        is_default=project.is_default,
        sort_order=sort_order,
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


def _replace_category_sort_order(
    category: ProjectCategory,
    *,
    sort_order: int,
) -> ProjectCategory:
    return ProjectCategory(
        category_id=category.category_id,
        name=category.name,
        category_kind=category.category_kind,
        is_default=category.is_default,
        sort_order=sort_order,
        created_at=category.created_at,
        updated_at=category.updated_at,
    )
