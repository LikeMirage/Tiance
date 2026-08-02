from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from tiance_runtime import run_tool

Payload = dict[str, Any]
ToolResult = dict[str, Any]

SUPPORTED_MODES = {"summary", "tree", "find"}
DEFAULT_EXCLUDE_DIRS = (
    ".git",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".venv",
    "venv",
    "dist",
    "build",
    ".next",
    ".nuxt",
    "site-packages",
)


def run(payload: Payload) -> ToolResult:
    mode = _read_mode(payload)
    root = _resolve_workspace_path(payload)
    max_depth = _read_int(payload.get("max_depth"), default=2, minimum=0, maximum=8)
    max_entries = _read_int(payload.get("max_entries"), default=300, minimum=1, maximum=5000)
    include_hidden = bool(payload.get("include_hidden") or False)
    directories_only = bool(payload.get("directories_only") or False)
    query = str(payload.get("query") or "").strip()
    exclude_dirs = _read_exclude_dirs(payload)

    if mode not in SUPPORTED_MODES:
        return {
            "ok": False,
            "mode": mode,
            "root_path": str(root),
            "error": "不支持的查看模式。",
        }
    if mode == "find" and not query:
        return {
            "ok": False,
            "mode": mode,
            "root_path": str(root),
            "error": "find 模式必须提供 query。",
        }
    if not root.exists():
        return {
            "ok": False,
            "mode": mode,
            "root_path": str(root),
            "error": "工作区路径不存在。",
        }
    if not root.is_dir():
        return {
            "ok": False,
            "mode": mode,
            "root_path": str(root),
            "error": "工作区路径不是目录。",
        }

    scan = _scan_workspace(
        root,
        max_depth=max_depth,
        max_entries=max_entries,
        include_hidden=include_hidden,
        directories_only=directories_only,
        query=query if mode == "find" else "",
        exclude_dirs=exclude_dirs,
    )
    summary = {
        "directory_count": scan["directory_count"],
        "file_count": scan["file_count"],
        "returned_entry_count": len(scan["entries"]) if mode != "summary" else 0,
        "max_depth": max_depth,
        "max_entries": max_entries,
        "truncated": scan["truncated"],
    }

    if mode == "summary":
        return {
            "ok": True,
            "mode": mode,
            "root_path": str(root),
            "content": _summary_content(root, summary),
            "summary": summary,
            "entries": [],
            "warnings": scan["warnings"],
        }

    entries = scan["entries"]
    content = _entries_content(root, entries, truncated=scan["truncated"])
    return {
        "ok": True,
        "mode": mode,
        "root_path": str(root),
        "content": content,
        "summary": summary,
        "entries": entries,
        "warnings": scan["warnings"],
    }


def _resolve_workspace_path(payload: Payload) -> Path:
    raw_path = str(payload.get("workspace_path") or "").strip()
    if not raw_path:
        raw_path = (
            os.environ.get("TIANCE_WORKSPACE_ROOT")
            or os.environ.get("WORKSPACE_ROOT")
            or os.getcwd()
        )
    return Path(raw_path).expanduser().resolve(strict=False)


def _read_mode(payload: Payload) -> str:
    mode = str(payload.get("mode", "summary") or "summary").strip()
    return mode if mode in SUPPORTED_MODES else mode


def _read_int(value: object, *, default: int, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        parsed = int(value if value is not None else default)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def _read_exclude_dirs(payload: Payload) -> set[str]:
    value = payload.get("exclude_dirs")
    if value is None:
        return set(DEFAULT_EXCLUDE_DIRS)
    if not isinstance(value, list):
        return set(DEFAULT_EXCLUDE_DIRS)
    return {str(item).strip() for item in value if str(item).strip()}


def _scan_workspace(
    root: Path,
    *,
    max_depth: int,
    max_entries: int,
    include_hidden: bool,
    directories_only: bool,
    query: str,
    exclude_dirs: set[str],
) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    warnings: list[str] = []
    lowered_query = query.lower()
    counts = {"directory_count": 0, "file_count": 0}
    truncated = False

    def visit(directory: Path, depth: int) -> None:
        nonlocal truncated
        if truncated or depth >= max_depth:
            return

        try:
            children = sorted(
                directory.iterdir(),
                key=lambda item: (not _is_directory(item), item.name.casefold()),
            )
        except OSError as exc:
            warnings.append(f"无法读取目录 {directory}: {exc}")
            return

        for child in children:
            if truncated:
                return
            if _should_skip(child, include_hidden=include_hidden, exclude_dirs=exclude_dirs):
                continue

            child_depth = depth + 1
            is_directory = _is_directory(child)
            if is_directory:
                counts["directory_count"] += 1
            else:
                counts["file_count"] += 1

            if _should_return_entry(
                child,
                is_directory=is_directory,
                directories_only=directories_only,
                lowered_query=lowered_query,
            ):
                if len(entries) >= max_entries:
                    truncated = True
                    return
                entries.append(_entry_payload(root, child, is_directory=is_directory, depth=child_depth))

            if is_directory and child_depth < max_depth:
                visit(child, child_depth)

    visit(root, 0)
    return {
        **counts,
        "entries": entries,
        "warnings": warnings,
        "truncated": truncated,
    }


def _is_directory(path: Path) -> bool:
    try:
        return path.is_dir() and not path.is_symlink()
    except OSError:
        return False


def _should_skip(path: Path, *, include_hidden: bool, exclude_dirs: set[str]) -> bool:
    if not include_hidden and path.name.startswith("."):
        return True
    return path.name in exclude_dirs and _is_directory(path)


def _should_return_entry(
    path: Path,
    *,
    is_directory: bool,
    directories_only: bool,
    lowered_query: str,
) -> bool:
    if directories_only and not is_directory:
        return False
    if lowered_query and lowered_query not in path.name.lower():
        return False
    return True


def _entry_payload(root: Path, path: Path, *, is_directory: bool, depth: int) -> dict[str, Any]:
    try:
        relative_path = path.relative_to(root).as_posix()
    except ValueError:
        relative_path = path.as_posix()
    size_bytes = 0
    if not is_directory:
        try:
            size_bytes = path.stat().st_size
        except OSError:
            size_bytes = 0
    return {
        "path": relative_path,
        "name": path.name,
        "type": "directory" if is_directory else "file",
        "depth": depth,
        "size_bytes": size_bytes,
    }


def _summary_content(root: Path, summary: dict[str, Any]) -> str:
    lines = [
        f"Workspace: {root}",
        f"Directories: {summary['directory_count']}",
        f"Files: {summary['file_count']}",
        f"Max depth: {summary['max_depth']}",
    ]
    if summary["truncated"]:
        lines.append("Result was truncated by max_entries.")
    return "\n".join(lines)


def _entries_content(root: Path, entries: list[dict[str, Any]], *, truncated: bool) -> str:
    lines = [root.name or str(root)]
    for entry in entries:
        marker = "[D]" if entry["type"] == "directory" else "[F]"
        indent = "  " * max(0, int(entry["depth"]) - 1)
        lines.append(f"{indent}{marker} {entry['path']}")
    if truncated:
        lines.append("...[truncated]")
    return "\n".join(lines)


if __name__ == "__main__":
    run_tool(run)
