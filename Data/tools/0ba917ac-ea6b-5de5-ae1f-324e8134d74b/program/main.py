from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
from typing import Any

from file_transaction import (
    FileTransactionError,
    PreparedFileChange,
    apply_file_transaction,
)
from tiance_runtime import run_tool


HUNK_RE = re.compile(r"^@@ -(?P<old_start>\d+)(?:,(?P<old_count>\d+))? \+(?P<new_start>\d+)(?:,(?P<new_count>\d+))? @@")


class ToolError(Exception):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


@dataclass
class Hunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: list[tuple[str, str]]


@dataclass
class FilePatch:
    old_path: str | None
    new_path: str | None
    hunks: list[Hunk]


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


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_path_header(line: str, prefix: str, strip_ab: bool) -> str | None:
    raw = line[len(prefix) :].strip()
    if not raw:
        raise ToolError("PATCH_PARSE_ERROR", "文件头路径为空。", {"line": line})
    raw = raw.split("\t", 1)[0]
    if raw == "/dev/null":
        return None
    raw = raw.replace("\\", "/")
    if strip_ab and (raw.startswith("a/") or raw.startswith("b/")):
        raw = raw[2:]
    return raw.strip("/")


def parse_patch(text: str, strip_ab: bool) -> list[FilePatch]:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    patches: list[FilePatch] = []
    i = 0
    while i < len(lines):
        if not lines[i].startswith("--- "):
            i += 1
            continue
        old_path = parse_path_header(lines[i], "--- ", strip_ab)
        i += 1
        if i >= len(lines) or not lines[i].startswith("+++ "):
            raise ToolError("PATCH_PARSE_ERROR", "缺少 +++ 文件头。", {"line_index": i + 1})
        new_path = parse_path_header(lines[i], "+++ ", strip_ab)
        i += 1
        hunks: list[Hunk] = []
        while i < len(lines):
            if lines[i].startswith("--- "):
                break
            match = HUNK_RE.match(lines[i])
            if not match:
                if lines[i] == "":
                    i += 1
                    continue
                raise ToolError("PATCH_PARSE_ERROR", "缺少或无法解析 @@ hunk 头。", {"line": lines[i], "line_index": i + 1})
            hunk = Hunk(
                old_start=int(match.group("old_start")),
                old_count=int(match.group("old_count") or "1"),
                new_start=int(match.group("new_start")),
                new_count=int(match.group("new_count") or "1"),
                lines=[],
            )
            i += 1
            while i < len(lines):
                line = lines[i]
                if line.startswith("--- ") or HUNK_RE.match(line):
                    break
                if line.startswith("\\ No newline"):
                    i += 1
                    continue
                if line == "":
                    i += 1
                    continue
                op = line[0]
                if op not in {" ", "+", "-"}:
                    raise ToolError("PATCH_PARSE_ERROR", "hunk 行必须以空格、+ 或 - 开头。", {"line": line, "line_index": i + 1})
                hunk.lines.append((op, line[1:]))
                i += 1
            hunks.append(hunk)
        if not hunks:
            raise ToolError("PATCH_PARSE_ERROR", "文件补丁没有 hunk。", {"old_path": old_path, "new_path": new_path})
        patches.append(FilePatch(old_path=old_path, new_path=new_path, hunks=hunks))
    if not patches:
        raise ToolError("PATCH_PARSE_ERROR", "没有找到 unified diff 文件补丁。")
    return patches


def resolve_patch_path(root: Path, rel: str) -> Path:
    path = (root / rel).resolve(strict=False)
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ToolError("PATH_OUTSIDE_WORKSPACE", "补丁路径不在工作区内。", {"path": str(path), "workspace_root": str(root)}) from exc
    return path


def apply_hunks(
    old_text: str,
    hunks: list[Hunk],
    rel: str,
    *,
    trailing_newline: bool,
) -> str:
    old_lines = old_text.splitlines()
    result: list[str] = []
    cursor = 0
    for hunk in hunks:
        start = max(hunk.old_start - 1, 0)
        if start < cursor:
            raise ToolError("PATCH_APPLY_FAILED", "hunk 顺序重叠或倒退。", {"file": rel, "old_start": hunk.old_start})
        result.extend(old_lines[cursor:start])
        cursor = start
        for op, line in hunk.lines:
            if op == " ":
                if cursor >= len(old_lines) or old_lines[cursor] != line:
                    got = old_lines[cursor] if cursor < len(old_lines) else "<EOF>"
                    raise ToolError("PATCH_APPLY_FAILED", "上下文行不匹配。", {"file": rel, "expected": line, "actual": got, "line": cursor + 1})
                result.append(old_lines[cursor])
                cursor += 1
            elif op == "-":
                if cursor >= len(old_lines) or old_lines[cursor] != line:
                    got = old_lines[cursor] if cursor < len(old_lines) else "<EOF>"
                    raise ToolError("PATCH_APPLY_FAILED", "删除行不匹配。", {"file": rel, "expected": line, "actual": got, "line": cursor + 1})
                cursor += 1
            elif op == "+":
                result.append(line)
        old_consumed = sum(1 for op, _ in hunk.lines if op in {" ", "-"})
        new_produced = sum(1 for op, _ in hunk.lines if op in {" ", "+"})
        if old_consumed != hunk.old_count:
            raise ToolError("PATCH_APPLY_FAILED", "hunk old_count 与内容不一致。", {"file": rel, "expected": hunk.old_count, "actual": old_consumed})
        if new_produced != hunk.new_count:
            raise ToolError("PATCH_APPLY_FAILED", "hunk new_count 与内容不一致。", {"file": rel, "expected": hunk.new_count, "actual": new_produced})
    result.extend(old_lines[cursor:])
    trailing = "\n" if trailing_newline and result else ""
    return "\n".join(result) + trailing


def decode_source(data: bytes, encoding: str) -> tuple[str, str]:
    effective_encoding = encoding
    if encoding == "utf-8" and data.startswith(b"\xef\xbb\xbf"):
        effective_encoding = "utf-8-sig"
    try:
        return data.decode(effective_encoding), effective_encoding
    except UnicodeDecodeError as exc:
        raise ToolError(
            "ENCODING_ERROR",
            "补丁目标无法按指定编码解码，已拒绝写入。",
            {"encoding": encoding},
        ) from exc


def normalize_newlines(text: str) -> tuple[str, str, bool]:
    has_crlf = "\r\n" in text
    without_crlf = text.replace("\r\n", "")
    has_lf = "\n" in without_crlf
    has_cr = "\r" in without_crlf
    if sum((has_crlf, has_lf, has_cr)) > 1:
        raise ToolError(
            "MIXED_NEWLINES",
            "补丁目标同时使用多种换行符，已拒绝写入以避免全文改写。",
        )
    newline = "\r\n" if has_crlf else ("\r" if has_cr else "\n")
    trailing_newline = text.endswith(("\r\n", "\n", "\r"))
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return normalized, newline, trailing_newline


def expected_hash_for(expected_map: dict[str, Any], rels: list[str]) -> str:
    for rel in rels:
        value = expected_map.get(rel)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def run(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        patch_text = payload.get("patch_text")
        if not isinstance(patch_text, str) or not patch_text.strip():
            raise ToolError("INVALID_ARGUMENT", "patch_text 必须是非空字符串。")
        root = workspace_root()
        dry_run = read_bool(payload.get("dry_run"), False)
        backup = read_bool(payload.get("backup"), False)
        create_parent_dirs = read_bool(payload.get("create_parent_dirs"), True)
        strip_ab = read_bool(payload.get("strip_ab_prefix"), True)
        encoding = str(payload.get("encoding") or "utf-8")
        expected_map = payload.get("expected_sha256_map") if isinstance(payload.get("expected_sha256_map"), dict) else {}
        patches = parse_patch(patch_text, strip_ab)
        changes: list[dict[str, Any]] = []
        transaction_changes: list[PreparedFileChange] = []
        seen_targets: set[Path] = set()
        for patch in patches:
            target_rel = patch.new_path if patch.new_path is not None else patch.old_path
            if target_rel is None:
                raise ToolError("PATCH_PARSE_ERROR", "old_path 和 new_path 不能同时为 /dev/null。")
            target = resolve_patch_path(root, target_rel)
            old_rel = patch.old_path or target_rel
            old_path = resolve_patch_path(root, old_rel) if patch.old_path else target
            is_add = patch.old_path is None
            is_delete = patch.new_path is None
            if patch.old_path and patch.new_path and old_path != target:
                raise ToolError(
                    "RENAME_UNSUPPORTED",
                    "safe_patch 不支持在单个文件补丁中同时改名；请分成新建和删除。",
                    {"old_path": old_rel, "new_path": target_rel},
                )
            if target in seen_targets:
                raise ToolError(
                    "DUPLICATE_TARGET",
                    "同一补丁中的多个文件块指向了同一目标。",
                    {"file": target_rel},
                )
            seen_targets.add(target)
            if is_add:
                if target.exists():
                    raise ToolError("OVERWRITE_DENIED", "新增文件已存在，拒绝覆盖。", {"file": target_rel})
                old_text = ""
                old_bytes = b""
                effective_encoding = encoding
                newline = "\n"
                trailing_newline = True
            else:
                if not old_path.exists():
                    raise ToolError("FILE_NOT_FOUND", "补丁目标文件不存在。", {"file": old_rel})
                if old_path.is_dir():
                    raise ToolError("IS_DIRECTORY", "补丁目标是目录。", {"file": old_rel})
                old_bytes = old_path.read_bytes()
                decoded_text, effective_encoding = decode_source(old_bytes, encoding)
                old_text, newline, trailing_newline = normalize_newlines(decoded_text)
            expected = expected_hash_for(expected_map, [old_rel, target_rel])
            if expected and sha256_bytes(old_bytes) != expected:
                raise ToolError("WRITE_CONFLICT", "文件 sha256 与 expected_sha256_map 不一致。", {"file": old_rel, "current_sha256": sha256_bytes(old_bytes), "expected_sha256": expected})
            new_text = apply_hunks(
                old_text,
                patch.hunks,
                target_rel,
                trailing_newline=trailing_newline,
            )
            rendered_text = new_text.replace("\n", newline)
            try:
                new_bytes = (
                    None if is_delete else rendered_text.encode(effective_encoding)
                )
            except UnicodeEncodeError as exc:
                raise ToolError(
                    "ENCODING_ERROR",
                    "补丁后的内容无法按指定编码写入。",
                    {"file": target_rel, "encoding": effective_encoding},
                ) from exc
            additions = sum(1 for hunk in patch.hunks for op, _ in hunk.lines if op == "+")
            deletions = sum(1 for hunk in patch.hunks for op, _ in hunk.lines if op == "-")
            changes.append(
                {
                    "type": "delete" if is_delete else ("add" if is_add else "update"),
                    "target": target,
                    "relative_path": target_rel,
                    "old_path": old_path,
                    "old_sha256": sha256_bytes(old_bytes) if not is_add else None,
                    "new_sha256": sha256_bytes(new_bytes) if new_bytes is not None else None,
                    "additions": additions,
                    "deletions": deletions,
                    "backup_path": None,
                }
            )
            transaction_changes.append(
                PreparedFileChange(
                    target=target,
                    original_exists=not is_add,
                    original_bytes=old_bytes,
                    original_stat=target.stat() if not is_add else None,
                    new_bytes=new_bytes,
                )
            )
        if not dry_run:
            for transaction_change in transaction_changes:
                if (
                    transaction_change.new_bytes is not None
                    and not transaction_change.target.parent.exists()
                    and not create_parent_dirs
                ):
                    raise ToolError(
                        "DIRECTORY_NOT_FOUND",
                        "父目录不存在。",
                        {"parent": str(transaction_change.target.parent)},
                    )
            backup_paths = apply_file_transaction(
                transaction_changes,
                create_backups=backup,
            )
            for change in changes:
                backup_path = backup_paths.get(change["target"])
                change["backup_path"] = str(backup_path) if backup_path else None
        files = [
            {
                "type": item["type"],
                "relative_path": item["relative_path"],
                "additions": item["additions"],
                "deletions": item["deletions"],
                "old_sha256": item["old_sha256"],
                "new_sha256": item["new_sha256"],
                "backup_path": item["backup_path"],
            }
            for item in changes
        ]
        total_additions = sum(item["additions"] for item in changes)
        total_deletions = sum(item["deletions"] for item in changes)
        return ok(
            "补丁验证通过，未写入。" if dry_run else "补丁应用完成。",
            {
                "dry_run": dry_run,
                "file_count": len(files),
                "additions": total_additions,
                "deletions": total_deletions,
                "files": files,
            },
        )
    except LookupError as exc:
        return fail("INVALID_ARGUMENT", "encoding 参数无效。", {"message": str(exc)})
    except FileTransactionError as exc:
        return fail(exc.code, exc.message, exc.details)
    except ToolError as exc:
        return fail(exc.code, exc.message, exc.details)
    except OSError as exc:
        return fail(
            "FILE_ACCESS_FAILED",
            "补丁目标读取或校验失败，未开始写入。",
            {"message": str(exc)},
        )


if __name__ == "__main__":
    run_tool(run)
