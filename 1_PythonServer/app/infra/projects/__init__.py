# 项目文件存储模块

from .project_files import ProjectFileStorage, get_project_file_storage
from .project_file_watcher import project_file_change_paths, watch_project_file_changes
from .project_identity import (
    PROJECT_IDENTITY_RELATIVE_PATH,
    ProjectIdentity,
    read_project_identity,
    write_project_identity,
)
from .project_storage import (
    ProjectStorage,
    get_project_storage,
    require_existing_project_root,
)

__all__ = [
    "ProjectFileStorage",
    "ProjectIdentity",
    "ProjectStorage",
    "PROJECT_IDENTITY_RELATIVE_PATH",
    "get_project_file_storage",
    "get_project_storage",
    "project_file_change_paths",
    "read_project_identity",
    "require_existing_project_root",
    "watch_project_file_changes",
    "write_project_identity",
]
