from __future__ import annotations

from dataclasses import dataclass, field
import fnmatch
import os
from pathlib import Path
import subprocess
from typing import Any

from tiance_runtime import run_tool


DEFAULT_EXCLUDE_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".next",
    ".turbo",
    "dist",
    "build",
    "coverage",
    "runtime",
    "Data.backup-before-local-rename-20260522084455",
}
TEXT_EXTENSIONS = {
    ".css",
    ".html",
    ".js",
    ".jsx",
    ".json",
    ".md",
    ".mjs",
    ".py",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".vue",
    ".yaml",
    ".yml",
}


class ToolError(Exception):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


@dataclass
class Candidate:
    path: Path
    rel: str
    score: int = 0
    reasons: list[str] = field(default_factory=list)
    excerpts: list[dict[str, Any]] = field(default_factory=list)


def ok(summary: str, data: dict[str, Any], warnings: list[str] | None = None) -> dict[str, Any]:
    return {"ok": True, "summary": summary, "data": data, "warnings": warnings or []}


def fail(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "ok": False,
        "error": f"{code}: {message}",
        "error_info": {"code": code, "message": message, "details": details or {}},
        "warnings": [],
    }


def workspace_root() -> Path:
    raw = os.environ.get("TIANCE_WORKSPACE_ROOT") or os.environ.get("WORKSPACE_ROOT") or os.getcwd()
    return Path(raw).expanduser().resolve(strict=False)


def read_bool(value: Any, default: bool) -> bool:
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


def list_strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip().replace("\\", "/") for item in value if isinstance(item, str) and item.strip()]


def read_keywords(value: Any) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ToolError("INVALID_ARGUMENT", "keywords 必须是非空字符串数组。")
    if len(value) > 24:
        raise ToolError("INVALID_ARGUMENT", "keywords 最多包含 24 个关键词。")

    keywords: list[str] = []
    invalid_indexes: list[int] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            invalid_indexes.append(index)
            continue
        keyword = item.strip().lower()
        if keyword not in keywords:
            keywords.append(keyword)
    if invalid_indexes:
        raise ToolError(
            "INVALID_ARGUMENT",
            "keywords 的每一项都必须是非空字符串。",
            {"invalid_indexes": invalid_indexes},
        )
    return keywords


def resolve_inside_root(value: Any, root: Path, *, default: Path | None = None) -> Path:
    raw = str(value or "").strip()
    path = Path(raw).expanduser() if raw else (default or root)
    if not path.is_absolute():
        path = root / path
    resolved = path.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ToolError("PATH_OUTSIDE_WORKSPACE", "路径不在工作区内。", {"path": str(resolved), "workspace_root": str(root)}) from exc
    return resolved


def rel_path(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def is_text_file(path: Path) -> bool:
    if path.suffix.lower() in TEXT_EXTENSIONS:
        return True
    try:
        sample = path.read_bytes()[:2048]
    except OSError:
        return False
    return bool(sample) and b"\x00" not in sample


def matches_globs(rel: str, include_globs: list[str]) -> bool:
    if not include_globs:
        return True
    return any(fnmatch.fnmatchcase(rel, pattern) or fnmatch.fnmatchcase(Path(rel).name, pattern) for pattern in include_globs)


def collect_tree(base: Path, root: Path, max_depth: int, exclude_dirs: set[str], limit: int = 180) -> list[str]:
    lines: list[str] = []
    base_depth = len(base.relative_to(root).parts) if base != root else 0
    for current, dirs, files in os.walk(base):
        current_path = Path(current)
        depth = len(current_path.relative_to(root).parts) - base_depth
        if depth > max_depth:
            dirs[:] = []
            continue
        dirs[:] = sorted(d for d in dirs if d not in exclude_dirs and not d.startswith("."))
        indent = "  " * max(0, depth)
        if current_path != base:
            lines.append(f"{indent}{current_path.name}/")
        if depth < max_depth:
            for name in sorted(files)[:20]:
                if len(lines) >= limit:
                    lines.append("...<tree truncated>")
                    return lines
                lines.append(f"{indent}  {name}")
        if len(lines) >= limit:
            lines.append("...<tree truncated>")
            return lines
    return lines


def git_status(root: Path, max_lines: int = 80) -> list[str]:
    if not (root / ".git").exists():
        return []
    try:
        completed = subprocess.run(
            ["git", "status", "--short"],
            cwd=str(root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=8,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ["<git status unavailable>"]
    lines = (completed.stdout or completed.stderr or "").splitlines()
    if len(lines) > max_lines:
        return [*lines[:max_lines], f"...<truncated {len(lines) - max_lines} lines>"]
    return lines


def add_candidate(candidates: dict[str, Candidate], path: Path, root: Path, score: int, reason: str) -> Candidate:
    rel = rel_path(path, root)
    candidate = candidates.get(rel)
    if candidate is None:
        candidate = Candidate(path=path, rel=rel)
        candidates[rel] = candidate
    candidate.score += score
    if reason not in candidate.reasons:
        candidate.reasons.append(reason)
    return candidate


def read_text(path: Path, max_chars: int) -> tuple[str, bool]:
    text = path.read_text(encoding="utf-8", errors="replace")
    if len(text) <= max_chars:
        return text, False
    return text[:max_chars] + f"\n...<truncated {len(text) - max_chars} chars>", True


def find_excerpts(text: str, keywords: list[str], max_matches: int) -> list[dict[str, Any]]:
    excerpts: list[dict[str, Any]] = []
    lines = text.splitlines()
    for index, line in enumerate(lines, start=1):
        lowered = line.lower()
        matched = [keyword for keyword in keywords if keyword in lowered]
        if not matched:
            continue
        start = max(1, index - 1)
        end = min(len(lines), index + 1)
        snippet = "\n".join(f"{line_no}: {lines[line_no - 1]}" for line_no in range(start, end + 1))
        excerpts.append({"line": index, "matched_terms": matched[:6], "snippet": snippet})
        if len(excerpts) >= max_matches:
            break
    return excerpts


def collect_candidates(
    root: Path,
    base: Path,
    keywords: list[str],
    pinned_paths: list[str],
    include_globs: list[str],
    exclude_dirs: set[str],
    max_matches_per_file: int,
    warnings: list[str],
) -> dict[str, Candidate]:
    candidates: dict[str, Candidate] = {}
    for raw_path in pinned_paths:
        path = resolve_inside_root(raw_path, root)
        if path.is_dir():
            for child in sorted(item for item in path.rglob("*") if item.is_file())[:80]:
                if is_text_file(child):
                    add_candidate(candidates, child, root, 20, "指定目录内文件")
        elif path.is_file():
            add_candidate(candidates, path, root, 30, "指定文件")
        else:
            warnings.append(f"指定路径不存在：{raw_path}")

    scanned = 0
    for current, dirs, files in os.walk(base):
        dirs[:] = sorted(d for d in dirs if d not in exclude_dirs and not d.startswith("."))
        for name in sorted(files):
            path = Path(current) / name
            rel = rel_path(path, root)
            if not matches_globs(rel, include_globs):
                continue
            scanned += 1
            if scanned > 5000:
                warnings.append("扫描文件超过 5000 个，已停止继续扫描。")
                return candidates
            path_score = sum(6 for keyword in keywords if keyword in rel.lower())
            if path_score:
                add_candidate(candidates, path, root, path_score, "路径命中关键词")
            if path.stat().st_size > 1_200_000 or not is_text_file(path):
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            excerpts = find_excerpts(text, keywords, max_matches_per_file)
            if excerpts:
                candidate = add_candidate(candidates, path, root, len(excerpts) * 4, "内容命中关键词")
                candidate.excerpts.extend(excerpts)
    return candidates


def build_context_pack(
    *,
    keywords: list[str],
    root: Path,
    base: Path,
    tree_lines: list[str],
    git_lines: list[str],
    selected: list[Candidate],
    max_file_chars: int,
    max_total_chars: int,
) -> tuple[str, bool]:
    parts: list[str] = [
        "# Project File Search",
        "",
        f"Keywords: {', '.join(keywords)}",
        f"Workspace: {root}",
        f"Base path: {base}",
        "",
        "## Directory Overview",
        *tree_lines[:180],
    ]
    if git_lines:
        parts.extend(["", "## Git Status", *git_lines])
    parts.extend(["", "## Relevant Files"])
    for item in selected:
        parts.append(f"- {item.rel} | score={item.score} | reasons={', '.join(item.reasons)}")

    for item in selected:
        try:
            text, truncated = read_text(item.path, max_file_chars)
        except OSError as exc:
            parts.extend(["", f"## File: {item.rel}", f"<read failed: {exc}>"])
            continue
        parts.extend(["", f"## File: {item.rel}", f"Reasons: {', '.join(item.reasons)}"])
        if item.excerpts:
            parts.append("Excerpts:")
            for excerpt in item.excerpts:
                parts.append(excerpt["snippet"])
                parts.append("")
        parts.append("Content preview:")
        parts.append("```")
        parts.append(text)
        parts.append("```")
        if truncated:
            parts.append("<file preview truncated>")

    pack = "\n".join(parts)
    if len(pack) <= max_total_chars:
        return pack, False
    return pack[:max_total_chars] + f"\n...<context_pack truncated {len(pack) - max_total_chars} chars>", True


def run(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        keywords = read_keywords(payload.get("keywords"))
        root = workspace_root()
        base = resolve_inside_root(payload.get("base_path"), root, default=root)
        if not base.exists() or not base.is_dir():
            raise ToolError("BASE_PATH_INVALID", "base_path 必须是存在的目录。", {"base_path": str(base)})
        max_depth = read_int(payload.get("max_depth"), 2, 0, 6)
        max_files = read_int(payload.get("max_files"), 12, 1, 40)
        max_matches_per_file = read_int(payload.get("max_matches_per_file"), 4, 1, 12)
        max_file_chars = read_int(payload.get("max_file_chars"), 3000, 500, 12000)
        max_total_chars = read_int(payload.get("max_total_chars"), 24000, 4000, 80000)
        include_git = read_bool(payload.get("include_git_status"), True)
        include_globs = list_strings(payload.get("include_globs"))
        pinned_paths = list_strings(payload.get("paths"))
        exclude_dirs = DEFAULT_EXCLUDE_DIRS | set(list_strings(payload.get("exclude_dirs")))
        warnings: list[str] = []
        tree_lines = collect_tree(base, root, max_depth, exclude_dirs)
        git_lines = git_status(root) if include_git else []
        candidates = collect_candidates(
            root,
            base,
            keywords,
            pinned_paths,
            include_globs,
            exclude_dirs,
            max_matches_per_file,
            warnings,
        )
        selected = sorted(candidates.values(), key=lambda item: (-item.score, item.rel))[:max_files]
        pack, truncated = build_context_pack(
            keywords=keywords,
            root=root,
            base=base,
            tree_lines=tree_lines,
            git_lines=git_lines,
            selected=selected,
            max_file_chars=max_file_chars,
            max_total_chars=max_total_chars,
        )
        if truncated:
            warnings.append("context_pack 达到 max_total_chars，已截断。")
        return ok(
            f"已按关键词找到并预览 {len(selected)} 个相关文件。",
            {
                "workspace_root": str(root),
                "base_path": str(base),
                "keywords": keywords,
                "selected_files": [
                    {"path": item.rel, "score": item.score, "reasons": item.reasons}
                    for item in selected
                ],
                "git_status_count": len(git_lines),
                "context_pack": pack,
                "truncated": truncated,
            },
            warnings,
        )
    except ToolError as exc:
        return fail(exc.code, exc.message, exc.details)


if __name__ == "__main__":
    run_tool(run)
