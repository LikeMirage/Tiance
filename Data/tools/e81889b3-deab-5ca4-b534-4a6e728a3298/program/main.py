from __future__ import annotations

import fnmatch
import os
from pathlib import Path
from typing import Any

from tiance_runtime import run_tool


DEFAULT_EXCLUDE_DIRS = {".git", ".hg", ".svn", "node_modules", ".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache", "dist", "build", ".next", ".turbo"}


class ToolError(Exception):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def result(ok: bool, summary: str = "", data: dict[str, Any] | None = None, warnings: list[str] | None = None, code: str = "", message: str = "", details: dict[str, Any] | None = None) -> dict[str, Any]:
    if ok:
        return {"ok": True, "summary": summary, "data": data or {}, "warnings": warnings or []}
    return {"ok": False, "error": f"{code}: {message}", "error_info": {"code": code, "message": message, "details": details or {}}, "warnings": warnings or []}


def workspace_root() -> Path:
    return Path(os.environ.get("TIANCE_WORKSPACE_ROOT") or os.environ.get("WORKSPACE_ROOT") or os.getcwd()).expanduser().resolve(strict=False)


def read_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "on"}:
            return True
        if lowered in {"false", "0", "no", "off"}:
            return False
    return default


def read_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def resolve_dir(value: Any, root: Path) -> Path:
    raw = str(value or "").strip()
    path = Path(raw).expanduser() if raw else root
    if not path.is_absolute():
        path = root / path
    resolved = path.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ToolError("PATH_OUTSIDE_WORKSPACE", "起点目录不在工作区内。", {"base_path": str(resolved)}) from exc
    if not resolved.exists():
        raise ToolError("DIRECTORY_NOT_FOUND", "起点目录不存在。", {"base_path": str(resolved)})
    if not resolved.is_dir():
        raise ToolError("IS_FILE", "起点路径必须是目录。", {"base_path": str(resolved)})
    return resolved


def normalize_patterns(value: Any) -> list[str]:
    if isinstance(value, str):
        patterns = [value]
    elif isinstance(value, list):
        patterns = [str(item) for item in value if isinstance(item, str)]
    else:
        patterns = []
    patterns = [item.strip().replace("\\", "/") for item in patterns if item.strip()]
    if not patterns:
        raise ToolError("INVALID_ARGUMENT", "patterns 必须包含至少一个非空模式。")
    return patterns


def is_hidden(rel: str) -> bool:
    return any(part.startswith(".") for part in rel.split("/") if part)


def matches(rel: str, name: str, patterns: list[str]) -> bool:
    for pattern in patterns:
        candidates = [pattern]
        if pattern.startswith("**/"):
            candidates.append(pattern[3:])
        if any(fnmatch.fnmatchcase(rel, item) or fnmatch.fnmatchcase(name, item) for item in candidates):
            return True
    return False


def run(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        root = workspace_root()
        base = resolve_dir(payload.get("base_path"), root)
        patterns = normalize_patterns(payload.get("patterns"))
        include_hidden = read_bool(payload.get("include_hidden"), False)
        match_directories = read_bool(payload.get("match_directories"), False)
        max_results = read_int(payload.get("max_results"), 500, 1, 10_000)
        extra_excludes = payload.get("exclude_dirs") if isinstance(payload.get("exclude_dirs"), list) else []
        exclude_dirs = DEFAULT_EXCLUDE_DIRS | {str(item) for item in extra_excludes if isinstance(item, str) and item}
        found: list[dict[str, Any]] = []
        truncated = False
        for current, dirs, files in os.walk(base):
            dirs[:] = sorted(d for d in dirs if d not in exclude_dirs and (include_hidden or not d.startswith(".")))
            current_path = Path(current)
            entries = files + (dirs if match_directories else [])
            for name in sorted(entries):
                path = current_path / name
                rel = path.relative_to(root).as_posix()
                if not include_hidden and is_hidden(rel):
                    continue
                if not matches(rel, name, patterns):
                    continue
                stat = path.stat()
                found.append({"relative_path": rel, "path": str(path), "type": "directory" if path.is_dir() else "file", "size_bytes": 0 if path.is_dir() else stat.st_size, "modified_time": stat.st_mtime})
                if len(found) >= max_results:
                    truncated = True
                    break
            if truncated:
                break
        warnings = ["结果达到 max_results，已截断。"] if truncated else []
        return result(True, f"匹配到 {len(found)} 个路径。", {"base_path": str(base), "patterns": patterns, "matches": found, "truncated": truncated}, warnings)
    except ToolError as exc:
        return result(False, code=exc.code, message=exc.message, details=exc.details)


if __name__ == "__main__":
    run_tool(run)
