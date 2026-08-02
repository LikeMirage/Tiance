from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

from atomic_file import FileChangedError, replace_bytes_atomically
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


def read_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def resolve_file(value: Any, root: Path) -> Path:
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
    if not resolved.exists():
        raise ToolError("FILE_NOT_FOUND", "文件不存在。", {"file_path": str(resolved)})
    if resolved.is_dir():
        raise ToolError("IS_DIRECTORY", "目标路径是目录。", {"file_path": str(resolved)})
    return resolved


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        root = workspace_root()
        path = resolve_file(payload.get("file_path"), root)
        old_text = payload.get("old_text")
        new_text = payload.get("new_text")
        if not isinstance(old_text, str) or old_text == "":
            raise ToolError("INVALID_ARGUMENT", "old_text 必须是非空字符串。")
        if not isinstance(new_text, str):
            raise ToolError("INVALID_ARGUMENT", "new_text 必须是字符串。")
        if old_text == new_text:
            raise ToolError("INVALID_ARGUMENT", "old_text 和 new_text 相同，没有可替换内容。")
        encoding = str(payload.get("encoding") or "utf-8")
        dry_run = read_bool(payload.get("dry_run"), False)
        backup = read_bool(payload.get("backup"), False)
        replace_all = read_bool(payload.get("replace_all"), False)
        raw = path.read_bytes()
        current_hash = sha256_bytes(raw)
        expected = str(payload.get("expected_sha256") or "").strip()
        if expected and current_hash != expected:
            raise ToolError("WRITE_CONFLICT", "当前文件 sha256 与 expected_sha256 不一致。", {"file_path": str(path), "current_sha256": current_hash, "expected_sha256": expected})
        try:
            text = raw.decode(encoding)
        except UnicodeDecodeError as exc:
            raise ToolError("ENCODING_ERROR", "无法按指定编码读取文件。", {"encoding": encoding}) from exc
        count = text.count(old_text)
        if "expected_count" in payload and payload.get("expected_count") is not None:
            expected_count = read_int(payload.get("expected_count"), -1, 0, 10_000_000)
            if count != expected_count:
                raise ToolError("MATCH_COUNT_MISMATCH", "实际匹配次数与 expected_count 不一致。", {"actual_count": count, "expected_count": expected_count})
        if count == 0:
            raise ToolError("NO_MATCH", "old_text 没有匹配到任何内容。")
        if not replace_all and count > 1:
            raise ToolError("AMBIGUOUS_MATCH", "old_text 匹配多处；请提供更精确文本或设置 replace_all=true。", {"match_count": count})
        new_content = text.replace(old_text, new_text) if replace_all else text.replace(old_text, new_text, 1)
        rel = path.relative_to(root).as_posix()
        backup_path = None
        try:
            after_bytes = new_content.encode(encoding)
        except UnicodeEncodeError as exc:
            raise ToolError(
                "ENCODING_ERROR",
                "替换后的内容无法按指定编码写入。",
                {"encoding": encoding},
            ) from exc
        if not dry_run:
            backup_path = replace_bytes_atomically(
                path,
                after_bytes,
                raw,
                create_backup=backup,
            )
        return ok(
            "替换校验通过，未写入文件。" if dry_run else "文本替换完成。",
            {
                "file_path": str(path),
                "relative_path": rel,
                "dry_run": dry_run,
                "replace_all": replace_all,
                "match_count": count,
                "replaced_count": count if replace_all else 1,
                "backup_path": str(backup_path) if backup_path else None,
                "before_sha256": current_hash,
                "after_sha256": sha256_bytes(after_bytes),
            },
        )
    except LookupError as exc:
        return fail("INVALID_ARGUMENT", "encoding 参数无效。", {"message": str(exc)})
    except FileChangedError as exc:
        return fail(
            "WRITE_CONFLICT",
            str(exc),
            {"file_path": str(path) if "path" in locals() else ""},
        )
    except OSError as exc:
        return fail(
            "WRITE_FAILED",
            "文件写入失败，原文件保持不变。",
            {"message": str(exc)},
        )
    except ToolError as exc:
        return fail(exc.code, exc.message, exc.details)


if __name__ == "__main__":
    run_tool(run)
