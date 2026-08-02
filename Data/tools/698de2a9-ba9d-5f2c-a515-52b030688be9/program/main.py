from __future__ import annotations

from datetime import datetime
import hashlib
import os
from pathlib import Path
import shutil
from typing import Any

from tiance_runtime import run_tool


class ToolError(Exception):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def ok(summary: str, data: dict[str, Any], warnings: list[str] | None = None) -> dict[str, Any]:
    return {"ok": True, "summary": summary, "data": data, "warnings": warnings or []}


def fail(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"ok": False, "error": f"{code}: {message}", "error_info": {"code": code, "message": message, "details": details or {}}, "warnings": []}


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


def resolve_target(value: Any, root: Path) -> Path:
    raw = str(value or "").strip()
    if not raw:
        raise ToolError("INVALID_ARGUMENT", "file_path 不能为空。")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = root / path
    resolved = path.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ToolError("PATH_OUTSIDE_WORKSPACE", "文件路径不在工作区内。", {"file_path": str(resolved)}) from exc
    if resolved.exists() and resolved.is_dir():
        raise ToolError("IS_DIRECTORY", "目标路径是目录，不能写入文本文件。", {"file_path": str(resolved)})
    return resolved


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def make_backup(path: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    backup_path = path.with_name(f"{path.name}.{stamp}.bak")
    shutil.copy2(path, backup_path)
    return backup_path


def run(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        root = workspace_root()
        path = resolve_target(payload.get("file_path"), root)
        content = payload.get("content")
        if not isinstance(content, str):
            raise ToolError("INVALID_ARGUMENT", "content 必须是字符串。")
        operation = str(payload.get("operation") or "create").strip().lower()
        if operation not in {"create", "overwrite", "append"}:
            raise ToolError("INVALID_ARGUMENT", "operation 必须是 create、overwrite 或 append。", {"operation": operation})
        encoding = str(payload.get("encoding") or "utf-8")
        dry_run = read_bool(payload.get("dry_run"), False)
        backup = read_bool(payload.get("backup"), False)
        create_parent_dirs = read_bool(payload.get("create_parent_dirs"), True)
        exists = path.exists()
        if operation == "create" and exists:
            raise ToolError("OVERWRITE_DENIED", "文件已存在，create 模式不会覆盖。", {"file_path": str(path)})
        if operation in {"overwrite", "append"} and not exists and operation == "append":
            old_bytes = b""
            old_text = ""
        elif exists:
            old_bytes = path.read_bytes()
            old_text = old_bytes.decode(encoding, errors="replace")
        else:
            old_bytes = b""
            old_text = ""
        expected = str(payload.get("expected_sha256") or "").strip()
        if expected and exists and sha256_bytes(old_bytes) != expected:
            raise ToolError("WRITE_CONFLICT", "当前文件 sha256 与 expected_sha256 不一致。", {"file_path": str(path), "current_sha256": sha256_bytes(old_bytes), "expected_sha256": expected})
        new_text = old_text + content if operation == "append" else content
        rel = path.relative_to(root).as_posix()
        backup_path = None
        after_bytes = new_text.encode(encoding)
        if not dry_run:
            if not path.parent.exists():
                if create_parent_dirs:
                    path.parent.mkdir(parents=True, exist_ok=True)
                else:
                    raise ToolError("DIRECTORY_NOT_FOUND", "父目录不存在。", {"parent": str(path.parent)})
            if backup and exists:
                backup_path = make_backup(path)
            path.write_bytes(after_bytes)
        return ok(
            "写入校验通过，未写入文件。" if dry_run else "文件写入完成。",
            {
                "file_path": str(path),
                "relative_path": rel,
                "operation": operation,
                "dry_run": dry_run,
                "existed": exists,
                "backup_path": str(backup_path) if backup_path else None,
                "before_sha256": sha256_bytes(old_bytes) if exists else None,
                "after_sha256": sha256_bytes(after_bytes),
                "before_size_bytes": len(old_bytes),
                "after_size_bytes": len(after_bytes),
            },
        )
    except UnicodeEncodeError as exc:
        return fail("ENCODING_ERROR", "内容无法按指定编码写入。", {"message": str(exc)})
    except LookupError as exc:
        return fail("INVALID_ARGUMENT", "encoding 参数无效。", {"message": str(exc)})
    except ToolError as exc:
        return fail(exc.code, exc.message, exc.details)


if __name__ == "__main__":
    run_tool(run)
