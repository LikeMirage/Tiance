from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import ripgrep_runner
from tiance_runtime import run_tool


DEFAULT_EXCLUDE_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    "dist",
    "build",
    ".next",
    ".turbo",
}


class ToolError(Exception):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def ok(summary: str, data: dict[str, Any], warnings: list[str]) -> dict[str, Any]:
    return {"ok": True, "summary": summary, "data": data, "warnings": warnings}


def fail(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "ok": False,
        "error": f"{code}: {message}",
        "error_info": {
            "code": code,
            "message": message,
            "details": details or {},
        },
        "warnings": [],
    }


def workspace_root() -> Path:
    raw = os.environ.get("TIANCE_WORKSPACE_ROOT") or os.environ.get("WORKSPACE_ROOT") or os.getcwd()
    return Path(raw).expanduser().resolve(strict=False)


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
        raise ToolError(
            "PATH_OUTSIDE_WORKSPACE",
            "起点目录不在工作区内。",
            {"base_path": str(resolved)},
        ) from exc
    if not resolved.exists():
        raise ToolError(
            "DIRECTORY_NOT_FOUND",
            "起点目录不存在。",
            {"base_path": str(resolved)},
        )
    if not resolved.is_dir():
        raise ToolError(
            "IS_FILE",
            "起点路径必须是目录。",
            {"base_path": str(resolved)},
        )
    return resolved


def list_strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [
        item.strip().replace("\\", "/")
        for item in value
        if isinstance(item, str) and item.strip()
    ]


def validate_globs(patterns: list[str], *, field: str) -> None:
    for pattern in patterns:
        if "\x00" in pattern or "\r" in pattern or "\n" in pattern:
            raise ToolError("INVALID_ARGUMENT", f"{field} 包含无效路径模式。")
        if field == "include_globs" and pattern.startswith("!"):
            raise ToolError(
                "INVALID_ARGUMENT",
                "include_globs 不能使用 ! 排除语法，请改用 exclude_globs。",
            )


def run(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        query = str(payload.get("query") or "")
        if not query:
            raise ToolError("INVALID_ARGUMENT", "query 不能为空。")
        if "\x00" in query or "\r" in query or "\n" in query:
            raise ToolError("INVALID_ARGUMENT", "query 只能搜索单行文本或正则表达式。")

        root = workspace_root()
        base = resolve_dir(payload.get("base_path"), root)
        include_globs = list_strings(payload.get("include_globs"))
        exclude_globs = list_strings(payload.get("exclude_globs"))
        encoding = str(payload.get("encoding") or "auto")
        validate_globs(include_globs, field="include_globs")
        validate_globs(exclude_globs, field="exclude_globs")
        search = ripgrep_runner.search(
            query=query,
            use_regex=read_bool(payload.get("regex"), False),
            case_sensitive=read_bool(payload.get("case_sensitive"), False),
            include_globs=include_globs,
            exclude_globs=exclude_globs,
            exclude_dirs=(
                DEFAULT_EXCLUDE_DIRS
                | set(list_strings(payload.get("exclude_dirs")))
            ),
            max_file_size=read_int(
                payload.get("max_file_size_bytes"),
                2_000_000,
                1000,
                20_000_000,
            ),
            max_matches=read_int(payload.get("max_matches"), 200, 1, 5000),
            context_lines=read_int(payload.get("context_lines"), 0, 0, 10),
            timeout_seconds=read_int(payload.get("timeout_seconds"), 30, 1, 60),
            encoding=encoding,
            root=root,
            base=base,
        )
        warnings = ["结果达到 max_matches，已截断。"] if search["truncated"] else []
        return ok(
            f"搜索到 {len(search['matches'])} 条匹配。",
            {
                "query": query,
                "regex": read_bool(payload.get("regex"), False),
                "encoding": encoding,
                "engine": "ripgrep",
                "matches": search["matches"],
                "searched_files": search["searched_files"],
                "skipped_files": 0,
                "truncated": search["truncated"],
            },
            warnings,
        )
    except (ToolError, ripgrep_runner.RipgrepError) as exc:
        return fail(exc.code, exc.message, exc.details)


if __name__ == "__main__":
    run_tool(run)
