import asyncio
from collections.abc import AsyncIterator
from functools import partial
from pathlib import Path

from watchfiles import Change, awatch

from app.infra.projects.project_file_names import is_internal_write_temp_path

_MAX_DETAILED_CHANGE_PATHS = 256


async def watch_project_file_changes(
    project_root: str,
    *,
    project_id: str,
) -> AsyncIterator[tuple[str, ...]]:
    root = Path(project_root).resolve()
    try:
        async for changes in awatch(
            root,
            watch_filter=partial(_is_external_project_change, root),
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
    ordered_paths = sorted(paths)
    if len(ordered_paths) <= _MAX_DETAILED_CHANGE_PATHS:
        return ordered_paths

    # Bulk operations such as cloning a repository can create tens of thousands
    # of files at once. A directory-level notification is enough for consumers
    # to refresh their visible tree and keeps the SSE payload bounded.
    return sorted({path.split("/", 1)[0] for path in ordered_paths})


def _is_external_project_change(root: Path, _change: Change, path: str) -> bool:
    try:
        relative = Path(path).resolve().relative_to(root).as_posix()
    except ValueError:
        return False
    return bool(relative) and not _is_ignored_project_watch_path(relative)


def _is_ignored_project_watch_path(relative_path: str) -> bool:
    parts = relative_path.split("/")
    return parts[0] == ".Tiance" or is_internal_write_temp_path(relative_path)
