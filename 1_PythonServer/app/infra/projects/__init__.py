"""Project infrastructure public API.

Keep the package entry lightweight.  Windows file watching runs in a spawned
process, and importing one watcher submodule must not eagerly load unrelated
file-storage and HTTP dependencies.
"""

from importlib import import_module
from typing import Any


_PUBLIC_IMPORTS = {
    "ProjectFileStorage": (".project_files", "ProjectFileStorage"),
    "get_project_file_storage": (".project_files", "get_project_file_storage"),
    "project_file_change_paths": (".project_file_watcher", "project_file_change_paths"),
    "watch_project_file_changes": (".project_file_watcher", "watch_project_file_changes"),
    "PROJECT_IDENTITY_RELATIVE_PATH": (
        ".project_identity",
        "PROJECT_IDENTITY_RELATIVE_PATH",
    ),
    "ProjectIdentity": (".project_identity", "ProjectIdentity"),
    "read_project_identity": (".project_identity", "read_project_identity"),
    "write_project_identity": (".project_identity", "write_project_identity"),
    "ProjectStorage": (".project_storage", "ProjectStorage"),
    "get_project_storage": (".project_storage", "get_project_storage"),
    "require_existing_project_root": (
        ".project_storage",
        "require_existing_project_root",
    ),
}


def __getattr__(name: str) -> Any:
    target = _PUBLIC_IMPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute_name = target
    value = getattr(import_module(module_name, __name__), attribute_name)
    globals()[name] = value
    return value

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
