# 项目管理服务
# 创建/删除项目、惰性引导默认项目、自动命名、文件系统目录管理

from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from uuid import uuid4

from json import dumps, loads
import logging

from app.core.errors import BadRequestError, ConflictError, NotFoundError
from app.domain.project import Project, ProjectCategory, ProjectKind
from app.infra.projects import ProjectStorage, get_project_storage
from app.repositories.project import ProjectRepository, get_project_repository
from app.services.project.project_ids import normalize_project_id

logger = logging.getLogger(__name__)

DEFAULT_PROJECT_ID = "00000000-0000-0000-0000-000000000001"
DEFAULT_PROJECT_NAME = "默认项目"
DEFAULT_PROJECT_CATEGORY_ID = "daily-project"
DEFAULT_PROJECT_CATEGORY_NAME = "日常项目"
DEFAULT_ROLE_PROJECT_CATEGORY_ID = "default-role-category"
DEFAULT_ROLE_PROJECT_CATEGORY_NAME = "基础角色"
DEFAULT_THEME_PROJECT_CATEGORY_ID = "default-theme-category"
DEFAULT_THEME_PROJECT_CATEGORY_NAME = "基础主题"
DEFAULT_TOOL_PROJECT_CATEGORY_ID = "default-tool-category"
DEFAULT_TOOL_PROJECT_CATEGORY_NAME = "未分类工具"
DEFAULT_KNOWLEDGE_PROJECT_CATEGORY_ID = "default-knowledge-category"
DEFAULT_KNOWLEDGE_PROJECT_CATEGORY_NAME = "基础知识"
DEFAULT_EXPERIENCE_PROJECT_CATEGORY_ID = "default-experience-category"
DEFAULT_EXPERIENCE_PROJECT_CATEGORY_NAME = "基础经验"
DEFAULT_PROVIDER_PROJECT_CATEGORY_ID = "default-provider-category"
DEFAULT_PROVIDER_PROJECT_CATEGORY_NAME = "模型供应商"
DEFAULT_PROJECT_BOOTSTRAPPED_KEY = "projects.default_project_bootstrapped"
BUILTIN_CATEGORIES_BOOTSTRAPPED_KEY = "categories.builtin_bootstrapped"


class ProjectService:
    def __init__(
        self,
        repository: ProjectRepository,
        storage: ProjectStorage,
    ) -> None:
        self._repository = repository
        self._storage = storage

    def list_projects(self) -> tuple[Project, ...]:
        """列出所有项目，首次访问时引导创建默认项目"""
        self.ensure_builtin_project_categories()
        projects = self._repository.list_projects()
        if any(project.project_kind is ProjectKind.PROJECT for project in projects):
            self._mark_default_project_bootstrapped()
            return projects

        if self._is_default_project_bootstrapped():
            return projects

        default_project = self.ensure_default_project()
        self._mark_default_project_bootstrapped()
        return (*projects, default_project)

    def get_project(self, project_id: str) -> Project | None:
        normalized_project_id = normalize_project_id(project_id)
        return self._repository.get_project(normalized_project_id)

    def get_project_category(self, category_id: str) -> ProjectCategory | None:
        normalized_category_id = _normalize_project_category_id(category_id)
        return self._repository.get_project_category(normalized_category_id)

    def create_role_project(
        self,
        *,
        name: str | None,
        category_id: str | None = None,
    ) -> Project:
        """保留角色调用入口，实际使用统一项目生命周期。"""
        return self.create_project(
            name=name,
            category_id=category_id,
            project_kind=ProjectKind.ROLE,
        )

    def create_project(
        self,
        *,
        name: str | None,
        root_path: str | None = None,
        category_id: str | None = None,
        project_kind: ProjectKind = ProjectKind.PROJECT,
    ) -> Project:
        """创建新项目；有 root_path 时导入外部文件夹，否则在应用数据目录下新建"""
        if project_kind is ProjectKind.PROVIDER:
            raise BadRequestError("供应商项目只能通过模型集创建。")
        category = self._require_project_category(category_id, project_kind=project_kind)
        normalized_path = _normalize_project_path(root_path)
        if normalized_path:
            return self._create_project_from_existing_folder(
                name=name,
                root_path=normalized_path,
                category_id=category.category_id,
                project_kind=project_kind,
            )
        return self._create_managed_project(
            name=name,
            category_id=category.category_id,
            project_kind=project_kind,
        )

    def install_managed_project_snapshot(
        self,
        *,
        staged_root: Path,
        project_id: str,
        name: str,
        category_id: str,
        project_kind: ProjectKind,
    ) -> Project:
        """把已校验的项目快照原子移入托管目录并登记到统一项目目录。"""
        normalized_project_id = normalize_project_id(project_id)
        normalized_name = _normalize_project_name(name)
        if not normalized_name:
            raise BadRequestError("项目名称不能为空。")
        category = self._require_project_category(
            category_id,
            project_kind=project_kind,
        )
        source = staged_root.resolve()
        if not source.is_dir() or source.is_symlink():
            raise BadRequestError("待安装项目目录无效。")
        if self._repository.get_project(normalized_project_id) is not None:
            raise ConflictError("新项目身份已被占用，请重试。")

        target = self._storage.build_project_root(
            normalized_project_id,
            project_kind=project_kind,
        ).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            raise ConflictError("新项目目录已存在，请重试。")

        now = _utc_now()
        project = Project(
            project_id=normalized_project_id,
            name=normalized_name,
            root_path=str(target),
            category_id=category.category_id,
            project_kind=project_kind,
            is_default=False,
            sort_order=self._repository.next_sort_order(
                project_kind=project_kind,
            ),
            created_at=now,
            updated_at=now,
        )
        try:
            source.replace(target)
            saved_project = self._repository.save_project(project)
            self._mark_default_project_bootstrapped()
            return saved_project
        except Exception:
            if target.exists() and not source.exists():
                target.replace(source)
            raise

    def rollback_managed_project_snapshot(
        self,
        project_id: str,
        *,
        staged_root: Path,
        project_kind: ProjectKind,
    ) -> None:
        """安装后的初始化失败时撤销登记并把目录移回临时区。"""
        normalized_project_id = normalize_project_id(project_id)
        project = self._repository.get_project(normalized_project_id)
        if project is None:
            return
        if project.project_kind is not project_kind:
            raise BadRequestError("只能回滚预期类型的托管项目。")
        target = Path(project.root_path).resolve()
        source = staged_root.resolve()
        if not self._storage.is_managed_project_root_for_kind(
            str(target),
            project_kind=project_kind,
        ):
            raise BadRequestError("只能回滚预期类型的托管项目。")
        if source.exists():
            raise ConflictError("项目安装临时目录已被占用。")

        self._repository.delete_project(normalized_project_id)
        try:
            target.replace(source)
        except Exception:
            self._repository.save_project(project)
            raise

    def list_project_categories(self) -> tuple[ProjectCategory, ...]:
        """列出项目分类，首次访问时引导默认分类"""
        self.ensure_builtin_project_categories()
        return self._repository.list_project_categories()

    def create_project_category(
        self,
        *,
        name: str | None,
        category_kind: ProjectKind = ProjectKind.PROJECT,
    ) -> ProjectCategory:
        """在指定项目集类型中创建分类。"""
        normalized_name = (
            _normalize_project_category_name(name)
            or self._create_default_new_category_name(category_kind)
        )
        self._ensure_category_name_available(
            normalized_name,
            category_kind=category_kind,
        )
        now = _utc_now()
        category = ProjectCategory(
            category_id=str(uuid4()),
            name=normalized_name,
            category_kind=category_kind,
            is_default=False,
            sort_order=self._repository.next_project_category_sort_order(
                category_kind=category_kind,
            ),
            created_at=now,
            updated_at=now,
        )
        return self._repository.save_project_category(category)

    def rename_project_category(self, category_id: str, *, name: str) -> ProjectCategory:
        """重命名项目分类"""
        normalized_category_id = _normalize_project_category_id(category_id)
        normalized_name = _normalize_project_category_name(name)
        if not normalized_name:
            raise BadRequestError("项目分类名称不能为空。")
        category = self._repository.get_project_category(normalized_category_id)
        if category is None:
            raise NotFoundError(f"项目分类 '{normalized_category_id}' 不存在。")
        self._ensure_category_name_available(
            normalized_name,
            category_kind=category.category_kind,
            current_category_id=category.category_id,
        )
        updated = ProjectCategory(
            category_id=category.category_id,
            name=normalized_name,
            category_kind=category.category_kind,
            is_default=category.is_default,
            sort_order=category.sort_order,
            created_at=category.created_at,
            updated_at=_utc_now(),
        )
        return self._repository.save_project_category(updated)

    def delete_project_category(self, category_id: str) -> None:
        """逐项回收到系统回收站并移除登记；发生失败保留未完成项和分类。"""
        normalized_category_id = _normalize_project_category_id(category_id)
        category = self._repository.get_project_category(normalized_category_id)
        if category is None:
            raise NotFoundError(f"项目分类 '{normalized_category_id}' 不存在。")
        projects = tuple(
            project
            for project in self._repository.list_projects()
            if project.category_id == category.category_id
        )
        if category.category_kind is ProjectKind.PROVIDER and projects:
            raise BadRequestError("模型分类需要先通过供应商删除流程清理模型供应商。")

        # Check all roots before recycling the first item. Shell deletion is not
        # a database transaction and must never be described as rolled back.
        try:
            for project in projects:
                self._storage.validate_project_recycle(
                    project.root_path,
                    external=not self._storage.is_managed_project_root(project.root_path),
                )
        except (OSError, ValueError) as exc:
            raise BadRequestError(str(exc)) from exc
        completed: list[str] = []
        for project in projects:
            try:
                self.delete_project(project.project_id, delete_files=True)
                completed.append(project.project_id)
            except Exception as exc:
                raise BadRequestError(
                    f"分类删除未完成：{exc}",
                    details={"reason": "category_delete_incomplete",
                        "completed_project_ids": completed, "failed_project_id": project.project_id,
                        "cause": getattr(exc, "details", None)},
                ) from exc
        try:
            # This rejects new projects concurrently added to the category.
            self._repository.delete_project_category(category.category_id)
        except Exception as exc:
            raise BadRequestError(
                f"项目已处理，但分类登记移除失败：{exc}",
                details={"reason": "category_delete_incomplete", "completed_project_ids": completed},
            ) from exc

    def move_project_to_category(self, project_id: str, *, category_id: str) -> Project:
        """把项目移动到另一个分类"""
        normalized_project_id = normalize_project_id(project_id)
        project = self._repository.get_project(normalized_project_id)
        if project is None:
            raise NotFoundError(f"项目 '{normalized_project_id}' 不存在。")
        category = self._require_existing_project_category(category_id)
        if project.project_kind is not category.category_kind:
            raise BadRequestError("项目类型与目标分类不匹配。")
        if project.category_id == category.category_id:
            return project
        updated = Project(
            project_id=project.project_id,
            name=project.name,
            root_path=project.root_path,
            category_id=category.category_id,
            project_kind=project.project_kind,
            is_default=project.is_default,
            sort_order=project.sort_order,
            created_at=project.created_at,
            updated_at=_utc_now(),
        )
        return self._repository.save_project(updated)

    def rename_project(self, project_id: str, *, name: str) -> Project:
        """重命名项目"""
        normalized_project_id = normalize_project_id(project_id)
        normalized_name = _normalize_project_name(name)
        if not normalized_name:
            raise BadRequestError("项目名称不能为空。")
        project = self._repository.get_project(normalized_project_id)
        if project is None:
            raise NotFoundError(f"项目 '{normalized_project_id}' 不存在。")
        if project.project_kind is ProjectKind.PROVIDER:
            raise BadRequestError("请在模型集里重命名供应商。")
        now = _utc_now()
        updated = Project(
            project_id=project.project_id,
            name=normalized_name,
            root_path=project.root_path,
            category_id=project.category_id,
            project_kind=project.project_kind,
            is_default=project.is_default,
            sort_order=project.sort_order,
            created_at=project.created_at,
            updated_at=now,
        )
        return self._repository.save_project(updated)

    def delete_project(self, project_id: str, *, delete_files: bool = False) -> None:
        """外部项目默认仅移除登记；明确删除文件时使用系统回收站。"""
        normalized_project_id = normalize_project_id(project_id)
        project = self._repository.get_project(normalized_project_id)
        if project is None:
            raise NotFoundError(f"项目 '{normalized_project_id}' 不存在。")
        if project.project_kind is ProjectKind.PROVIDER:
            raise BadRequestError("请在模型集里删除供应商。")

        recycled = False
        is_managed_project = self._storage.is_managed_project_root(project.root_path)
        if is_managed_project or delete_files:
            try:
                recycled = self._storage.recycle_project_root(project.root_path, external=not is_managed_project)
            except (OSError, ValueError) as exc:
                raise BadRequestError(f"文件夹未能移入系统回收站，项目登记已保留：{exc}") from exc
        try:
            self._repository.delete_project(project.project_id)
        except Exception as exc:
            if recycled:
                raise BadRequestError(
                    "文件夹已移入系统回收站，但项目登记移除失败。可重试移除登记，或从系统回收站恢复文件。",
                    details={"reason": "project_deregistration_failed", "files_recycled": True,
                        "project_id": project.project_id, "root_path": project.root_path},
                ) from exc
            raise

    def is_managed_project(self, project: Project) -> bool:
        """判断项目是否为天策内部托管目录。"""
        return self._storage.is_managed_project_root(project.root_path)

    def get_project_order(self) -> tuple[str, ...]:
        """获取项目排序"""
        project_catalog = self._repository.get_file_catalog(ProjectKind.PROJECT)
        if project_catalog is not None:
            return tuple(
                project.project_id
                for project in project_catalog.list_projects()
            )
        return ()

    def save_project_order(self, project_ids: tuple[str, ...]) -> tuple[str, ...]:
        """保存项目排序（校验 ID 合法并补全遗漏项）"""
        existing_projects = self._repository.list_projects()
        existing = {project.project_id for project in existing_projects}
        seen: set[str] = set()
        validated: list[str] = []
        for pid in project_ids:
            if pid not in existing:
                continue
            if pid in seen:
                continue
            seen.add(pid)
            validated.append(pid)
        for project in existing_projects:
            if project.project_id not in seen:
                validated.append(project.project_id)
        self._repository.save_file_project_order(tuple(validated))
        return tuple(validated)

    def ensure_default_project(self) -> Project:
        """确保默认项目存在（创建时同时创建文件系统目录）"""
        default_category = self.ensure_default_project_category()
        current_default_project = self._repository.get_default_project()
        if current_default_project is not None:
            self._storage.ensure_project_root(current_default_project.project_id)
            return current_default_project

        now = _utc_now()
        root_path = self._storage.ensure_project_root(DEFAULT_PROJECT_ID)
        default_project = Project(
            project_id=DEFAULT_PROJECT_ID,
            name=DEFAULT_PROJECT_NAME,
            root_path=str(root_path),
            category_id=default_category.category_id,
            project_kind=ProjectKind.PROJECT,
            is_default=True,
            sort_order=0,
            created_at=now,
            updated_at=now,
        )
        return self._repository.save_project(default_project)

    def ensure_default_project_category(self) -> ProjectCategory:
        """确保默认项目分类存在"""
        current = self._repository.get_project_category(DEFAULT_PROJECT_CATEGORY_ID)
        if current is not None:
            return current

        now = _utc_now()
        category = ProjectCategory(
            category_id=DEFAULT_PROJECT_CATEGORY_ID,
            name=DEFAULT_PROJECT_CATEGORY_NAME,
            category_kind=ProjectKind.PROJECT,
            is_default=True,
            sort_order=0,
            created_at=now,
            updated_at=now,
        )
        return self._repository.save_project_category(category)

    def ensure_default_role_project_category(self) -> ProjectCategory:
        """确保默认角色分类存在。"""
        current = self._repository.get_project_category(
            DEFAULT_ROLE_PROJECT_CATEGORY_ID,
        )
        if current is not None:
            if current.category_kind is not ProjectKind.ROLE:
                raise RuntimeError("默认角色分类类型不正确。")
            return current

        now = _utc_now()
        category = ProjectCategory(
            category_id=DEFAULT_ROLE_PROJECT_CATEGORY_ID,
            name=DEFAULT_ROLE_PROJECT_CATEGORY_NAME,
            category_kind=ProjectKind.ROLE,
            is_default=True,
            sort_order=0,
            created_at=now,
            updated_at=now,
        )
        return self._repository.save_project_category(category)

    def ensure_default_theme_project_category(self) -> ProjectCategory:
        """确保默认主题分类存在。"""
        current = self._repository.get_project_category(
            DEFAULT_THEME_PROJECT_CATEGORY_ID,
        )
        if current is not None:
            if current.category_kind is not ProjectKind.THEME:
                raise RuntimeError("默认主题分类类型不正确。")
            return current

        now = _utc_now()
        category = ProjectCategory(
            category_id=DEFAULT_THEME_PROJECT_CATEGORY_ID,
            name=DEFAULT_THEME_PROJECT_CATEGORY_NAME,
            category_kind=ProjectKind.THEME,
            is_default=True,
            sort_order=0,
            created_at=now,
            updated_at=now,
        )
        return self._repository.save_project_category(category)

    def ensure_default_tool_project_category(self) -> ProjectCategory:
        existing_categories = tuple(
            category
            for category in self._repository.list_project_categories()
            if category.category_kind is ProjectKind.TOOL
        )
        if existing_categories:
            return min(
                existing_categories,
                key=lambda category: (category.sort_order, category.created_at),
            )
        return self._ensure_builtin_category(
            category_id=DEFAULT_TOOL_PROJECT_CATEGORY_ID,
            name=DEFAULT_TOOL_PROJECT_CATEGORY_NAME,
            category_kind=ProjectKind.TOOL,
        )

    def ensure_default_knowledge_project_category(self) -> ProjectCategory:
        return self._ensure_builtin_category(
            category_id=DEFAULT_KNOWLEDGE_PROJECT_CATEGORY_ID,
            name=DEFAULT_KNOWLEDGE_PROJECT_CATEGORY_NAME,
            category_kind=ProjectKind.KNOWLEDGE,
        )

    def ensure_default_experience_project_category(self) -> ProjectCategory:
        return self._ensure_builtin_category(
            category_id=DEFAULT_EXPERIENCE_PROJECT_CATEGORY_ID,
            name=DEFAULT_EXPERIENCE_PROJECT_CATEGORY_NAME,
            category_kind=ProjectKind.EXPERIENCE,
        )

    def ensure_default_provider_project_category(self) -> ProjectCategory:
        return self._ensure_builtin_category(
            category_id=DEFAULT_PROVIDER_PROJECT_CATEGORY_ID,
            name=DEFAULT_PROVIDER_PROJECT_CATEGORY_NAME,
            category_kind=ProjectKind.PROVIDER,
        )

    def ensure_builtin_project_categories(self) -> None:
        ensure_by_kind = {
            ProjectKind.PROJECT: self.ensure_default_project_category,
            ProjectKind.KNOWLEDGE: self.ensure_default_knowledge_project_category,
            ProjectKind.EXPERIENCE: self.ensure_default_experience_project_category,
            ProjectKind.ROLE: self.ensure_default_role_project_category,
            ProjectKind.THEME: self.ensure_default_theme_project_category,
            ProjectKind.TOOL: self.ensure_default_tool_project_category,
            ProjectKind.PROVIDER: self.ensure_default_provider_project_category,
        }
        for project_kind, ensure_category in ensure_by_kind.items():
            if self._repository.get_catalog_metadata_value(project_kind, BUILTIN_CATEGORIES_BOOTSTRAPPED_KEY) == "1":
                continue
            ensure_category()
            self._repository.set_catalog_metadata_value(
                project_kind, key=BUILTIN_CATEGORIES_BOOTSTRAPPED_KEY, value="1",
            )

    # ------------------------------------------------------------------
    # 私有：托管项目
    # ------------------------------------------------------------------

    def _create_managed_project(
        self,
        *,
        name: str | None,
        category_id: str,
        project_kind: ProjectKind,
    ) -> Project:
        """在应用数据目录下创建 UUID 目录的托管项目"""
        normalized_name = (
            _normalize_project_name(name)
            or self._create_default_new_project_name(project_kind)
        )
        project_id = str(uuid4())
        now = _utc_now()
        root_path = self._storage.ensure_project_root(project_id, project_kind=project_kind)
        project = Project(
            project_id=project_id,
            name=normalized_name,
            root_path=str(root_path),
            category_id=category_id,
            project_kind=project_kind,
            is_default=False,
            sort_order=self._repository.next_sort_order(project_kind=project_kind),
            created_at=now,
            updated_at=now,
        )
        try:
            saved_project = self._repository.save_project(project)
        except Exception:
            try:
                self._storage.remove_empty_project_root(str(root_path))
            except (OSError, ValueError):
                logger.warning("未能清理登记失败的空项目目录：%s", root_path, exc_info=True)
            raise
        if project_kind is ProjectKind.PROJECT:
            self._mark_default_project_bootstrapped()
        return saved_project

    # ------------------------------------------------------------------
    # 私有：外部导入
    # ------------------------------------------------------------------

    def _create_project_from_existing_folder(
        self,
        *,
        name: str | None,
        root_path: str,
        category_id: str,
        project_kind: ProjectKind,
    ) -> Project:
        """导入用户本地文件夹为项目"""
        try:
            external_root = self._storage.resolve_external_project_root(root_path)
        except FileNotFoundError as exc:
            raise BadRequestError(str(exc)) from exc
        except NotADirectoryError as exc:
            raise BadRequestError(str(exc)) from exc
        except ValueError as exc:
            raise BadRequestError(str(exc)) from exc
        normalized_root_path = str(external_root)
        existing_project = self._repository.get_project_by_root_path(normalized_root_path)
        if existing_project is not None:
            self._raise_duplicate_import_conflict(existing_project)
        normalized_name = _normalize_project_name(name) or external_root.name
        project_id = str(uuid4())
        now = _utc_now()
        project = Project(
            project_id=project_id,
            name=normalized_name,
            root_path=normalized_root_path,
            category_id=category_id,
            project_kind=project_kind,
            is_default=False,
            sort_order=self._repository.next_sort_order(project_kind=project_kind),
            created_at=now,
            updated_at=now,
        )
        try:
            saved_project = self._repository.save_project(project)
        except ConflictError:
            existing_project = self._repository.get_project_by_root_path(normalized_root_path)
            if existing_project is not None:
                self._raise_duplicate_import_conflict(existing_project)
            raise
        if project_kind is ProjectKind.PROJECT:
            self._mark_default_project_bootstrapped()
        return saved_project

    def _raise_duplicate_import_conflict(self, existing_project: Project) -> None:
        category = self._repository.get_project_category(existing_project.category_id)
        category_name = category.name if category is not None else DEFAULT_PROJECT_CATEGORY_NAME
        raise ConflictError(
            f"此项目已存在于“{category_name}”分类中。",
            details={
                "kind": "project_already_imported",
                "project_id": existing_project.project_id,
                "project_name": existing_project.name,
                "root_path": existing_project.root_path,
                "category_id": existing_project.category_id,
                "category_name": category_name,
            },
        )

    def _create_default_new_project_name(self, project_kind: ProjectKind) -> str:
        """生成自增的新建项目名称（"新建项目" / "新建项目 2" / "新建项目 3"...）"""
        existing_names = {
            project.name
            for project in self._repository.list_projects()
            if project.project_kind is project_kind
        }
        base_name = {
            ProjectKind.PROJECT: "新建项目",
            ProjectKind.KNOWLEDGE: "新建知识",
            ProjectKind.EXPERIENCE: "新建经验",
            ProjectKind.ROLE: "新建角色",
            ProjectKind.THEME: "新建主题",
            ProjectKind.TOOL: "新建工具",
            ProjectKind.PROVIDER: "新建供应商",
        }[project_kind]
        if base_name not in existing_names:
            return base_name

        index = 2
        while f"{base_name} {index}" in existing_names:
            index += 1
        return f"{base_name} {index}"

    def _create_default_new_category_name(
        self,
        category_kind: ProjectKind,
    ) -> str:
        """生成自增的新建分类名称（"新建分类" / "新建分类 2" / "新建分类 3"...）"""
        existing_names = {
            category.name
            for category in self._repository.list_project_categories()
            if category.category_kind is category_kind
        }
        base_name = "新建分类"
        if base_name not in existing_names:
            return base_name

        index = 2
        while f"{base_name} {index}" in existing_names:
            index += 1
        return f"{base_name} {index}"

    def _require_project_category(
        self,
        category_id: str | None,
        *,
        project_kind: ProjectKind,
    ) -> ProjectCategory:
        self.ensure_builtin_project_categories()
        if category_id is None or not category_id.strip():
            existing = next(
                (
                    category
                    for category in self._repository.list_project_categories()
                    if category.category_kind is project_kind
                ),
                None,
            )
            if existing is not None:
                return existing
            return self.create_project_category(name=None, category_kind=project_kind)
        category = self._require_existing_project_category(category_id)
        if category.category_kind is not project_kind:
            raise BadRequestError("项目只能创建在同类型的项目分类中。")
        return category

    def _ensure_default_category(
        self,
        category_kind: ProjectKind,
    ) -> ProjectCategory:
        if category_kind is ProjectKind.ROLE:
            return self.ensure_default_role_project_category()
        if category_kind is ProjectKind.THEME:
            return self.ensure_default_theme_project_category()
        if category_kind is ProjectKind.KNOWLEDGE:
            return self.ensure_default_knowledge_project_category()
        if category_kind is ProjectKind.EXPERIENCE:
            return self.ensure_default_experience_project_category()
        if category_kind is ProjectKind.TOOL:
            return self.ensure_default_tool_project_category()
        if category_kind is ProjectKind.PROVIDER:
            return self.ensure_default_provider_project_category()
        return self.ensure_default_project_category()

    def _ensure_builtin_category(
        self,
        *,
        category_id: str,
        name: str,
        category_kind: ProjectKind,
    ) -> ProjectCategory:
        current = self._repository.get_project_category(category_id)
        if current is not None:
            if current.category_kind is not category_kind:
                raise RuntimeError(f"默认 {category_kind.value} 分类类型不正确。")
            return current
        now = _utc_now()
        return self._repository.save_project_category(ProjectCategory(
            category_id=category_id,
            name=name,
            category_kind=category_kind,
            is_default=True,
            sort_order=0,
            created_at=now,
            updated_at=now,
        ))

    def _require_existing_project_category(self, category_id: str) -> ProjectCategory:
        normalized_category_id = _normalize_project_category_id(category_id)
        category = self._repository.get_project_category(normalized_category_id)
        if category is None:
            raise NotFoundError(f"项目分类 '{normalized_category_id}' 不存在。")
        return category

    def _ensure_category_name_available(
        self,
        name: str,
        *,
        category_kind: ProjectKind,
        current_category_id: str | None = None,
    ) -> None:
        existing = self._repository.get_project_category_by_name(
            name,
            category_kind=category_kind,
        )
        if existing is None:
            return
        if current_category_id is not None and existing.category_id == current_category_id:
            return
        raise BadRequestError("项目分类名称已存在。")

    def _is_default_project_bootstrapped(self) -> bool:
        return self._repository.get_catalog_metadata_value(
            ProjectKind.PROJECT, DEFAULT_PROJECT_BOOTSTRAPPED_KEY,
        ) == "1"

    def _mark_default_project_bootstrapped(self) -> None:
        if not self._is_default_project_bootstrapped():
            self._repository.set_catalog_metadata_value(
                ProjectKind.PROJECT, key=DEFAULT_PROJECT_BOOTSTRAPPED_KEY, value="1",
            )


def _normalize_project_name(name: str | None) -> str:
    return (name or "").strip()


def _normalize_project_category_id(category_id: str) -> str:
    normalized_category_id = category_id.strip()
    if not normalized_category_id:
        raise BadRequestError("项目分类 ID 不能为空。")
    return normalized_category_id


def _normalize_project_category_name(name: str | None) -> str:
    return (name or "").strip()


def _normalize_project_path(root_path: str | None) -> str:
    return (root_path or "").strip()


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


@lru_cache
def get_project_service() -> ProjectService:
    return ProjectService(
        get_project_repository(),
        get_project_storage(),
    )
