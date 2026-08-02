from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

from tiance_runtime import run_tool


class ToolError(Exception):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def success(summary: str, data: dict[str, Any], warnings: list[str]) -> dict[str, Any]:
    return {"ok": True, "summary": summary, "data": data, "warnings": warnings}


def failure(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"ok": False, "error": f"{code}: {message}", "error_info": {"code": code, "message": message, "details": details or {}}, "warnings": []}


def workspace_root() -> Path:
    return Path(os.environ.get("TIANCE_WORKSPACE_ROOT") or os.environ.get("WORKSPACE_ROOT") or os.getcwd()).expanduser().resolve(strict=False)


def read_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


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


def resolve_file(raw: Any, root: Path) -> Path:
    text = str(raw or "").strip()
    if not text:
        raise ToolError("INVALID_ARGUMENT", "文件路径不能为空。")
    path = Path(text).expanduser()
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
        raise ToolError("IS_DIRECTORY", "期望读取文件，但路径是目录。", {"file_path": str(resolved)})
    return resolved


def decode_text(data: bytes, encoding: str) -> tuple[str, str]:
    candidates = ["utf-8-sig", "utf-8", "gb18030"] if (encoding or "auto").lower() == "auto" else [encoding]
    for item in candidates:
        try:
            return data.decode(item), item
        except UnicodeDecodeError:
            continue
        except LookupError as exc:
            raise ToolError("INVALID_ARGUMENT", "encoding 参数无效。", {"encoding": encoding}) from exc
    raise ToolError("ENCODING_ERROR", "无法解码文件。", {"encoding": encoding})


def looks_binary(data: bytes) -> bool:
    sample = data[:4096]
    return b"\x00" in sample if sample else False


def normalize_request(item: Any, default_max_lines: int) -> dict[str, Any]:
    if isinstance(item, str):
        return {"file_path": item, "start_line": 1, "max_lines": default_max_lines}
    if isinstance(item, dict):
        allowed_fields = {"file_path", "start_line", "max_lines"}
        unknown_fields = sorted(set(item) - allowed_fields)
        if unknown_fields:
            raise ToolError(
                "INVALID_ARGUMENT",
                "files 对象元素包含不支持的字段。",
                {"fields": unknown_fields},
            )
        file_path = item.get("file_path")
        if not isinstance(file_path, str) or not file_path.strip():
            raise ToolError(
                "INVALID_ARGUMENT",
                "files 对象元素必须提供非空 file_path。",
            )
        return {
            "file_path": file_path,
            "start_line": read_int(item.get("start_line"), 1, 1, 10_000_000),
            "max_lines": read_int(item.get("max_lines"), default_max_lines, 1, 20_000),
        }
    raise ToolError("INVALID_ARGUMENT", "files 中的元素必须是路径字符串或对象。", {"item": repr(item)})


def render_lines(lines: list[str], start_line: int, include_numbers: bool) -> str:
    if not include_numbers:
        return "\n".join(lines)
    width = len(str(start_line + len(lines) - 1))
    return "\n".join(f"{line_no:>{width}} | {line}" for line_no, line in enumerate(lines, start=start_line))


def budget_skipped_entry(index: int, item: Any) -> dict[str, Any]:
    requested_path = item if isinstance(item, str) else (
        item.get("file_path") if isinstance(item, dict) else None
    )
    message = "总字符预算已用尽，该文件未读取。"
    return {
        "ok": False,
        "index": index,
        "requested_path": requested_path,
        "error": f"TOTAL_BUDGET_EXHAUSTED: {message}",
        "error_info": {
            "code": "TOTAL_BUDGET_EXHAUSTED",
            "message": message,
            "details": {},
        },
    }


def run(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        items = payload.get("files")
        if not isinstance(items, list) or not items:
            raise ToolError("INVALID_ARGUMENT", "files 必须是非空数组。")
        root = workspace_root()
        max_chars_per_file = read_int(payload.get("max_chars_per_file"), 30_000, 1000, 500_000)
        total_max_chars = read_int(payload.get("total_max_chars"), 100_000, 1000, 2_000_000)
        default_max_lines = read_int(payload.get("default_max_lines"), 1000, 1, 20_000)
        include_numbers = read_bool(payload.get("include_line_numbers"), False)
        encoding = str(payload.get("encoding") or "auto")
        files: list[dict[str, Any]] = []
        warnings: list[str] = []
        used_chars = 0
        for index, item in enumerate(items):
            if used_chars >= total_max_chars:
                files.extend(
                    budget_skipped_entry(remaining_index, remaining_item)
                    for remaining_index, remaining_item in enumerate(
                        items[index:],
                        start=index,
                    )
                )
                warnings.append("总字符预算已用尽，后续文件未读取。")
                break
            request = normalize_request(item, default_max_lines)
            try:
                path = resolve_file(request["file_path"], root)
                raw = path.read_bytes()
                if looks_binary(raw):
                    raise ToolError("BINARY_FILE", "文件疑似二进制。", {"file_path": str(path)})
                text, used_encoding = decode_text(raw, encoding)
                lines = text.splitlines()
                start = int(request["start_line"])
                max_lines = int(request["max_lines"])
                begin = min(start - 1, len(lines))
                selected = lines[begin : begin + max_lines]
                content = render_lines(selected, start, include_numbers)
                selected_line_count = len(selected)
                truncation_reasons: list[str] = []
                if begin + max_lines < len(lines):
                    truncation_reasons.append("line_limit")
                if len(content) > max_chars_per_file:
                    content = content[:max_chars_per_file]
                    truncation_reasons.append("file_char_limit")
                remaining = total_max_chars - used_chars
                if len(content) > remaining:
                    content = content[:remaining]
                    truncation_reasons.append("total_char_limit")
                used_chars += len(content)
                rel = path.relative_to(root).as_posix()
                if truncation_reasons:
                    warnings.append(
                        f"{rel} 已截断：{', '.join(truncation_reasons)}。"
                    )
                files.append(
                    {
                        "ok": True,
                        "file_path": str(path),
                        "relative_path": rel,
                        "encoding": used_encoding,
                        "sha256": hashlib.sha256(raw).hexdigest(),
                        "size_bytes": len(raw),
                        "total_lines": len(lines),
                        "start_line": start,
                        "line_count": len(content.splitlines()) if content else 0,
                        "selected_line_count": selected_line_count,
                        "content": content,
                        "truncated": bool(truncation_reasons),
                        "truncation_reasons": truncation_reasons,
                    }
                )
            except ToolError as exc:
                files.append({"ok": False, "index": index, "error": f"{exc.code}: {exc.message}", "error_info": {"code": exc.code, "message": exc.message, "details": exc.details}})
                warnings.append(f"第 {index + 1} 个文件读取失败：{exc.code}。")
        return success(f"完成批量读取：成功 {sum(1 for item in files if item.get('ok'))} 个，失败 {sum(1 for item in files if not item.get('ok'))} 个。", {"files": files, "total_chars": used_chars}, warnings)
    except ToolError as exc:
        return failure(exc.code, exc.message, exc.details)


if __name__ == "__main__":
    run_tool(run)
