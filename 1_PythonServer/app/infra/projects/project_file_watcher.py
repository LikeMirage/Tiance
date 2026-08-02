import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

from watchfiles import Change, DefaultFilter, awatch

from app.infra.projects.project_file_names import is_internal_write_temp_path

_IGNORED_PROJECT_WATCH_DIR_NAMES = frozenset(
    (
        ".git",
        ".hg",
        ".hypothesis",
        ".idea",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".svn",
        ".tox",
        ".venv",
        "__pycache__",
        "build",
        "coverage",
        "dist",
        "node_modules",
        "target",
        "venv",
    )
)


async def watch_project_file_changes(
    project_root: str,
    *,
    project_id: str,
) -> AsyncIterator[tuple[str, ...]]:
    root = Path(project_root).resolve()
    try:
        async for changes in awatch(
            root,
            watch_filter=DefaultFilter(ignore_dirs=sorted(_IGNORED_PROJECT_WATCH_DIR_NAMES)),
            debounce=500,
            step=100,
            ignore_permission_denied=True,
        ):
            paths = project_file_change_paths(root, changes)
            if paths:
                yield tuple(paths)
    except asyncio.CancelledError:
        raise


def project_file_change_paths(
    project_root: str | Path,
    changes: set[tuple[Change, str]],
) -> list[str]:
    root = Path(project_root).resolve()
    paths: set[str] = set()
    for _change, path in changes:
        try:
            relative = Path(path).resolve().relative_to(root).as_posix()
        except ValueError:
            continue
        if not relative:
            continue
        if is_internal_write_temp_path(relative):
            continue
        if _is_ignored_project_watch_path(relative):
            continue
        paths.add(relative)
    return sorted(paths)


def _is_ignored_project_watch_path(relative_path: str) -> bool:
    return any(part in _IGNORED_PROJECT_WATCH_DIR_NAMES for part in relative_path.split("/"))
