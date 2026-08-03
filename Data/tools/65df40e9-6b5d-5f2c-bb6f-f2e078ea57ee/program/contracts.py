from __future__ import annotations

import os
from pathlib import Path
from typing import Any


DEFAULT_DATABASE_PATH = ".Tiance/cache/text-search/index.sqlite3"


class ToolError(Exception):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def workspace_root() -> Path:
    raw = str(os.environ.get("TIANCE_WORKSPACE_ROOT") or "").strip()
    if not raw:
        raise ToolError("WORKSPACE_REQUIRED", "请先在一个已登记的项目工作区中使用全文检索工具。")
    root = Path(raw).expanduser().resolve(strict=False)
    if not root.is_dir():
        raise ToolError("WORKSPACE_NOT_FOUND", "当前工作区不存在。", {"workspace_root": str(root)})
    return root


def resolve_inside_workspace(value: Any, root: Path, *, field: str, default: str) -> Path:
    raw = str(value or default).strip()
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = root / path
    resolved = path.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ToolError(
            "PATH_OUTSIDE_WORKSPACE",
            f"{field} 必须位于当前工作区内。",
            {field: str(resolved), "workspace_root": str(root)},
        ) from exc
    return resolved


def relative_path(path: Path, root: Path) -> str:
    return path.resolve(strict=False).relative_to(root).as_posix()


def read_bool(value: Any, default: bool = False) -> bool:
    return value if isinstance(value, bool) else default


def read_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def read_string_list(value: Any, *, maximum: int = 100) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    result: list[str] = []
    for item in value[:maximum]:
        text = str(item or "").strip()
        if text and text not in result:
            result.append(text)
    return tuple(result)
