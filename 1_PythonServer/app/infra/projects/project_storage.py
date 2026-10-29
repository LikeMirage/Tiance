# 项目文件存储管理
# 创建项目目录、调用系统回收站、确保路径安全

from functools import lru_cache
from pathlib import Path

from app.core.config import get_settings
from app.core.errors import NotFoundError
from app.domain.project import ProjectKind
from app.infra.system_recycle_bin import recycle_path


class ProjectStorage:
    """项目文件存储：管理项目根目录的创建、导入、校验和系统回收"""

    def __init__(
        self,
        projects_root: Path,
        roles_root: Path | None = None,
        themes_root: Path | None = None,
        tools_root: Path | None = None,
        knowledge_root: Path | None = None,
        experience_root: Path | None = None,
        providers_root: Path | None = None,
    ) -> None:
        self._projects_root = projects_root
        self._roles_root = roles_root
        self._themes_root = themes_root
        self._tools_root = tools_root
        self._knowledge_root = knowledge_root
        self._experience_root = experience_root
        self._providers_root = providers_root

    @property
    def projects_root(self) -> Path:
        return self._projects_root

    # ------------------------------------------------------------------
    # 托管项目（应用内新建）
    # ------------------------------------------------------------------

    def build_project_root(
        self,
        project_id: str,
        *,
        project_kind: ProjectKind = ProjectKind.PROJECT,
    ) -> Path:
        """返回项目 ID 对应的文件系统路径"""
        return self._managed_root_for_kind(project_kind) / project_id

    def ensure_project_root(
        self,
        project_id: str,
        *,
        project_kind: ProjectKind = ProjectKind.PROJECT,
    ) -> Path:
        """确保项目目录存在并返回其路径"""
        managed_root = self._managed_root_for_kind(project_kind)
        project_root = self.build_project_root(project_id, project_kind=project_kind)
        self._assert_inside_managed_root(project_root, managed_root)
        project_root.mkdir(parents=True, exist_ok=True)
        return project_root

    # ------------------------------------------------------------------
    # 外部项目（打开系统上已有的文件夹）
    # ------------------------------------------------------------------

    def resolve_external_project_root(self, root_path: str) -> Path:
        """校验并解析用户选择的真实项目目录"""
        raw_project_root = Path(root_path).expanduser()
        if _is_link_like(raw_project_root):
            raise ValueError("项目路径不能是符号链接或连接点。")
        project_root = raw_project_root.resolve()
        if not project_root.exists():
            raise FileNotFoundError("项目文件夹不存在。")
        if not project_root.is_dir():
            raise NotADirectoryError("项目路径必须是文件夹。")
        return project_root

    def resolve_managed_project_root(
        self,
        root_path: str,
        *,
        project_kind: ProjectKind,
    ) -> Path:
        """校验一个已经存在的目录属于指定类型的托管根目录。"""
        raw_project_root = Path(root_path).expanduser()
        if _is_link_like(raw_project_root):
            raise ValueError("项目路径不能是符号链接或连接点。")
        project_root = raw_project_root.resolve()
        managed_root = self._managed_root_for_kind(project_kind)
        self._assert_inside_managed_root(project_root, managed_root)
        if not project_root.exists():
            raise FileNotFoundError("项目文件夹不存在。")
        if not project_root.is_dir():
            raise NotADirectoryError("项目路径必须是文件夹。")
        return project_root

    def is_managed_project_root(self, project_root: str) -> bool:
        """判断项目目录是否在应用数据目录内（即由应用管理）"""
        try:
            self._managed_root_for_path(Path(project_root))
            return True
        except ValueError:
            return False

    def is_managed_project_root_for_kind(
        self,
        project_root: str,
        *,
        project_kind: ProjectKind,
    ) -> bool:
        """判断项目目录是否严格属于指定类型的托管根目录。"""
        try:
            self._assert_inside_managed_root(
                Path(project_root),
                self._managed_root_for_kind(project_kind),
            )
            return True
        except ValueError:
            return False

    # ------------------------------------------------------------------
    # 系统回收站
    # ------------------------------------------------------------------

    def validate_project_recycle(self, project_root: str, *, external: bool = False) -> Path:
        """Resolve the exact deletion target; never recycle a collection root."""
        raw_path = Path(project_root).expanduser()
        if _is_link_like(raw_path):
            raise ValueError("不能删除符号链接或连接点目录。")
        source = raw_path.resolve()
        if source == source.parent:
            raise ValueError("不能删除磁盘根目录。")
        for managed_root in self._managed_roots():
            managed = managed_root.resolve()
            if source == managed or source in managed.parents:
                raise ValueError("不能删除天策项目集根目录或其上级目录。")
            if external and managed in source.parents:
                raise ValueError("外部项目删除路径不能位于天策项目集目录内。")
        if not external:
            self._managed_root_for_path(source)
        if source.exists() and not source.is_dir():
            raise NotADirectoryError("项目路径必须是文件夹。")
        return source

    def recycle_project_root(self, project_root: str, *, external: bool = False) -> bool:
        """Recycle the directory on this machine; absent folders need only deregistration."""
        source = self.validate_project_recycle(project_root, external=external)
        if not source.exists():
            return False
        recycle_path(source)
        return True

    def remove_empty_project_root(self, project_root: str) -> None:
        """Clean up an empty directory whose initial registration failed, never its contents."""
        source = self.validate_project_recycle(project_root)
        if source.exists():
            source.rmdir()

    # ------------------------------------------------------------------
    # 安全校验
    # ------------------------------------------------------------------

    def _managed_root_for_kind(self, project_kind: ProjectKind) -> Path:
        if project_kind is ProjectKind.PROJECT:
            return self._projects_root
        if project_kind is ProjectKind.KNOWLEDGE and self._knowledge_root is not None:
            return self._knowledge_root
        if project_kind is ProjectKind.EXPERIENCE and self._experience_root is not None:
            return self._experience_root
        if project_kind is ProjectKind.ROLE and self._roles_root is not None:
            return self._roles_root
        if project_kind is ProjectKind.THEME and self._themes_root is not None:
            return self._themes_root
        if project_kind is ProjectKind.TOOL and self._tools_root is not None:
            return self._tools_root
        if project_kind is ProjectKind.PROVIDER and self._providers_root is not None:
            return self._providers_root
        raise RuntimeError(f"未配置 {project_kind.value} 项目存储目录。")

    def _managed_roots(self) -> tuple[Path, ...]:
        return tuple(
            root
            for root in (
                self._projects_root,
                self._roles_root,
                self._themes_root,
                self._tools_root,
                self._knowledge_root,
                self._experience_root,
                self._providers_root,
            )
            if root is not None
        )

    def _managed_root_for_path(self, path: Path) -> Path:
        for managed_root in self._managed_roots():
            try:
                self._assert_inside_managed_root(path, managed_root)
                return managed_root
            except ValueError:
                continue
        raise ValueError("Project path is outside the configured managed directories.")

    @staticmethod
    def _assert_inside_managed_root(path: Path, managed_root: Path) -> None:
        """确保路径位于指定托管目录内，防止目录遍历攻击。"""
        projects_root = managed_root.resolve()
        target_path = path.resolve()
        if target_path == projects_root:
            return
        if projects_root not in target_path.parents:
            raise ValueError("Project path is outside the configured projects directory.")


def require_existing_project_root(project_root: str | Path) -> Path:
    """返回现存项目根；项目被移动或删除时禁止写入链路重建原路径。"""
    resolved_root = Path(project_root).expanduser().resolve(strict=False)
    if not resolved_root.is_dir():
        raise NotFoundError(
            "项目文件夹不存在或已被移动。",
            details={"reason": "project_root_unavailable"},
        )
    return resolved_root


def _is_link_like(path: Path) -> bool:
    is_junction = getattr(path, "is_junction", None)
    return path.is_symlink() or bool(is_junction and is_junction())


@lru_cache
def get_project_storage() -> ProjectStorage:
    """获取 ProjectStorage 单例"""
    settings = get_settings()
    return ProjectStorage(
        projects_root=settings.projects_data_path,
        roles_root=settings.roles_data_path,
        themes_root=settings.themes_data_path,
        tools_root=settings.tools_data_path,
        knowledge_root=settings.knowledge_data_path,
        experience_root=settings.experience_data_path,
        providers_root=settings.providers_data_path,
    )
