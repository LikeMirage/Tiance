from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from watchfiles import Change, DefaultFilter, awatch

from app.infra.tools.tool_project_config_constants import (
    TOOL_EXAMPLES_FILE,
    TOOL_FOLDER_MANIFEST_FILE,
    TOOL_INPUT_SCHEMA_FILE,
    TOOL_OUTPUT_SCHEMA_FILE,
)
from app.services.tools.tool_registry import ToolRegistryService

logger = logging.getLogger(__name__)

_IGNORED_TOOL_WATCH_DIR_NAMES = frozenset(
    (
        ".git",
        ".hg",
        ".idea",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".svn",
        ".tox",
        ".venv",
        "__pycache__",
        "assets",
        "build",
        "coverage",
        "dependencies",
        "dist",
        "node_modules",
        "program",
        "target",
        "venv",
    )
)

_WATCHED_TOOL_METADATA_FILES = frozenset(
    (
        TOOL_FOLDER_MANIFEST_FILE,
        TOOL_INPUT_SCHEMA_FILE,
        TOOL_OUTPUT_SCHEMA_FILE,
        TOOL_EXAMPLES_FILE,
    )
)


async def watch_tool_metadata_changes(
    tools_root: str | Path,
    registry_service: ToolRegistryService,
) -> None:
    root = Path(tools_root).resolve()
    try:
        async for changes in awatch(
            root,
            watch_filter=DefaultFilter(ignore_dirs=sorted(_IGNORED_TOOL_WATCH_DIR_NAMES)),
            debounce=700,
            step=100,
            ignore_permission_denied=True,
        ):
            paths = tool_metadata_change_paths(root, changes)
            if not paths:
                continue
            try:
                registry_service.rebuild_registry()
            except Exception:
                logger.warning(
                    "Tool metadata cache rebuild failed after external changes: %s",
                    ", ".join(paths),
                    exc_info=True,
                )
            else:
                logger.info("Tool metadata cache rebuilt after external changes: %s", ", ".join(paths))
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.warning("Tool metadata watcher stopped unexpectedly.", exc_info=True)


def tool_metadata_change_paths(
    tools_root: str | Path,
    changes: set[tuple[Change, str]],
) -> tuple[str, ...]:
    root = Path(tools_root).resolve()
    paths: set[str] = set()
    for _change, path in changes:
        try:
            relative = Path(path).resolve().relative_to(root).as_posix()
        except ValueError:
            continue
        if _is_tool_metadata_path(relative):
            paths.add(relative)
    return tuple(sorted(paths))


def _is_tool_metadata_path(relative_path: str) -> bool:
    parts = tuple(part for part in relative_path.strip().replace("\\", "/").split("/") if part)
    if len(parts) < 2:
        return False
    metadata_path = "/".join(parts[-2:])
    return metadata_path in _WATCHED_TOOL_METADATA_FILES
