# 项目领域模型
# 代表一个工作区项目，包含文件系统路径和排序信息

from dataclasses import dataclass
from enum import StrEnum


class ProjectKind(StrEnum):
    """项目工作区类型。"""

    PROJECT = "project"
    KNOWLEDGE = "knowledge"
    EXPERIENCE = "experience"
    ROLE = "role"
    THEME = "theme"
    TOOL = "tool"
    PROVIDER = "provider"


@dataclass(frozen=True, slots=True)
class Project:
    """项目：包含唯一标识、名称、根目录路径、类型、分类、默认标记和排序"""

    project_id: str
    name: str
    root_path: str
    is_default: bool
    sort_order: int
    created_at: str
    updated_at: str
    category_id: str = ""
    project_kind: ProjectKind = ProjectKind.PROJECT


@dataclass(frozen=True, slots=True)
class ProjectCategory:
    """项目分类：天策内部的项目管理视图，不对应真实文件夹"""

    category_id: str
    name: str
    is_default: bool
    sort_order: int
    created_at: str
    updated_at: str
    category_kind: ProjectKind = ProjectKind.PROJECT
