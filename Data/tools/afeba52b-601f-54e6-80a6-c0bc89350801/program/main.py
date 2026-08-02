from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any

from tiance_runtime import run_tool


EXCLUDE_DIRS = {
    ".git",
    ".Tiance",
    ".local",
    ".playwright-mcp",
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
    "Data",
    "Data.backup-before-local-rename-20260522084455",
    "5_参考项目",
}
CODE_EXTENSIONS = {".py", ".ts", ".tsx", ".js", ".jsx", ".vue", ".css", ".html"}
DEV_TOOL_NAMES = {
    "@vitejs/plugin-react",
    "eslint",
    "prettier",
    "typescript",
    "vite",
    "vitest",
    "ts-node",
    "tsx",
    "jest",
    "playwright",
}


class ToolError(Exception):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


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


def resolve_root(value: Any) -> Path:
    root = workspace_root()
    raw = str(value or "").strip()
    path = Path(raw).expanduser() if raw else root
    if not path.is_absolute():
        path = root / path
    resolved = path.resolve(strict=False)
    if not resolved.is_dir():
        raise ToolError("ROOT_NOT_FOUND", "项目根目录不存在或不是目录。", {"root_path": str(resolved)})
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ToolError("PATH_OUTSIDE_WORKSPACE", "root_path 不在当前工作区内。", {"root_path": str(resolved)}) from exc
    return resolved


def rel(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def should_skip_dir(path: Path) -> bool:
    return path.name in EXCLUDE_DIRS or path.name.startswith(".cache")


def iter_files(root: Path, *, extensions: set[str] | None = None) -> list[Path]:
    result: list[Path] = []
    for current, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in EXCLUDE_DIRS)
        for name in sorted(files):
            path = Path(current) / name
            if extensions is not None and path.suffix.lower() not in extensions:
                continue
            result.append(path)
    return result


def add_finding(
    findings: list[dict[str, Any]],
    severity: str,
    code: str,
    message: str,
    *,
    path: Path | None = None,
    root: Path | None = None,
    suggestion: str | None = None,
) -> None:
    item: dict[str, Any] = {"severity": severity, "code": code, "message": message}
    if path is not None:
        item["path"] = rel(path, root) if root else str(path)
    if suggestion:
        item["suggestion"] = suggestion
    findings.append(item)


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    return payload if isinstance(payload, dict) else {}


def collect_package_dirs(root: Path) -> list[Path]:
    dirs: list[Path] = []
    for current, subdirs, files in os.walk(root):
        subdirs[:] = sorted(d for d in subdirs if d not in EXCLUDE_DIRS)
        if "package.json" in files:
            dirs.append(Path(current))
            subdirs[:] = [d for d in subdirs if d != "node_modules"]
    return dirs


def check_package_managers(root: Path, package_dirs: list[Path], findings: list[dict[str, Any]]) -> None:
    for package_dir in package_dirs:
        package_path = package_dir / "package.json"
        has_pnpm = (package_dir / "pnpm-lock.yaml").exists()
        wrong_locks = [
            name
            for name in ("package-lock.json", "yarn.lock", "bun.lockb", "bun.lock")
            if (package_dir / name).exists()
        ]
        if has_pnpm and wrong_locks:
            add_finding(
                findings,
                "error",
                "MIXED_PACKAGE_LOCKS",
                "pnpm 项目中出现其他包管理器锁文件。",
                path=package_dir,
                root=root,
                suggestion=f"保留 pnpm-lock.yaml，移除：{', '.join(wrong_locks)}。",
            )
        try:
            package = load_json(package_path)
        except Exception as exc:
            add_finding(findings, "error", "INVALID_PACKAGE_JSON", f"package.json 无法解析：{exc}", path=package_path, root=root)
            continue
        dependencies = package.get("dependencies") if isinstance(package.get("dependencies"), dict) else {}
        misplaced = sorted(name for name in dependencies if name in DEV_TOOL_NAMES or name.startswith("@types/"))
        if misplaced:
            add_finding(
                findings,
                "warning",
                "DEV_TOOLS_IN_DEPENDENCIES",
                "构建、类型或测试工具疑似放在 dependencies。",
                path=package_path,
                root=root,
                suggestion=f"确认这些依赖是否应移动到 devDependencies：{', '.join(misplaced)}。",
            )


def check_env_examples(root: Path, package_dirs: list[Path], findings: list[dict[str, Any]]) -> None:
    env_ref_re = re.compile(r"\b(?:import\.meta\.env\.|process\.env\.)([A-Z][A-Z0-9_]+)\b")
    for package_dir in package_dirs:
        src_dir = package_dir / "src"
        if not src_dir.is_dir():
            continue
        refs: set[str] = set()
        for file_path in iter_files(src_dir, extensions={".ts", ".tsx", ".js", ".jsx", ".vue"}):
            try:
                text = file_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            refs.update(match.group(1) for match in env_ref_re.finditer(text))
        refs = {name for name in refs if name.startswith(("VITE_", "REACT_APP_", "NEXT_PUBLIC_"))}
        if not refs:
            continue
        example_path = package_dir / ".env.example"
        if not example_path.exists():
            add_finding(
                findings,
                "warning",
                "MISSING_ENV_EXAMPLE",
                "前端代码读取了环境变量，但缺少 .env.example。",
                path=package_dir,
                root=root,
                suggestion=f"补充变量：{', '.join(sorted(refs))}。",
            )
            continue
        content = example_path.read_text(encoding="utf-8", errors="replace")
        missing = sorted(name for name in refs if f"{name}=" not in content)
        if missing:
            add_finding(
                findings,
                "warning",
                "ENV_EXAMPLE_MISSING_KEYS",
                ".env.example 缺少代码实际读取的环境变量。",
                path=example_path,
                root=root,
                suggestion=f"补充：{', '.join(missing)}。",
            )


def check_local_urls(root: Path, findings: list[dict[str, Any]], max_hits: int = 40) -> None:
    url_re = re.compile(r"(localhost|127\.0\.0\.1|http://)", re.IGNORECASE)
    hits = 0
    for file_path in iter_files(root, extensions=CODE_EXTENSIONS):
        if hits >= max_hits:
            add_finding(findings, "info", "LOCAL_URL_SCAN_TRUNCATED", "本地地址扫描命中较多，已截断。", root=root)
            return
        try:
            lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line_no, line in enumerate(lines, start=1):
            if not url_re.search(line):
                continue
            add_finding(
                findings,
                "info",
                "LOCAL_OR_HTTP_URL_REVIEW",
                f"发现本地地址或 HTTP 明文地址，需确认是否仅用于开发环境。第 {line_no} 行。",
                path=file_path,
                root=root,
            )
            hits += 1
            if hits >= max_hits:
                break


def check_temp_files(root: Path, findings: list[dict[str, Any]]) -> None:
    temp_names = {"debug.log", "npm-debug.log", "yarn-error.log"}
    temp_suffixes = (".tmp", ".bak", ".backup", ".orig", ".rej")
    for file_path in iter_files(root):
        if file_path.name in temp_names or file_path.name.lower().endswith(temp_suffixes):
            add_finding(
                findings,
                "warning",
                "TEMP_OR_BACKUP_FILE",
                "发现疑似临时、备份或冲突残留文件。",
                path=file_path,
                root=root,
                suggestion="确认是否真实需要；不需要应删除。",
            )


def check_empty_dirs(root: Path, findings: list[dict[str, Any]], max_hits: int = 60) -> None:
    hits = 0
    for current, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in EXCLUDE_DIRS)
        path = Path(current)
        if path == root or should_skip_dir(path):
            continue
        if dirs or files:
            continue
        add_finding(findings, "info", "EMPTY_DIRECTORY_REVIEW", "发现空目录，确认是否有真实用途。", path=path, root=root)
        hits += 1
        if hits >= max_hits:
            add_finding(findings, "info", "EMPTY_DIR_SCAN_TRUNCATED", "空目录扫描命中较多，已截断。", root=root)
            return


def check_deep_relative_imports(root: Path, findings: list[dict[str, Any]], max_hits: int = 40) -> None:
    src_dirs = [path for path in (root / "2_ReactWeb" / "src", root / "src") if path.is_dir()]
    hits = 0
    for src_dir in src_dirs:
        for file_path in iter_files(src_dir, extensions={".ts", ".tsx", ".js", ".jsx"}):
            if hits >= max_hits:
                add_finding(findings, "info", "DEEP_IMPORT_SCAN_TRUNCATED", "深层相对路径扫描命中较多，已截断。", root=root)
                return
            text = file_path.read_text(encoding="utf-8", errors="replace")
            if "../../../" in text or "..\\..\\..\\" in text:
                add_finding(
                    findings,
                    "info",
                    "DEEP_RELATIVE_IMPORT_REVIEW",
                    "发现较深相对路径，后续可考虑路径别名或就近整理。",
                    path=file_path,
                    root=root,
                )
                hits += 1


def git_status(root: Path) -> list[str]:
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
    return (completed.stdout or completed.stderr or "").splitlines()[:120]


def recommended_commands(root: Path, package_dirs: list[Path]) -> list[str]:
    commands: list[str] = []
    for package_dir in package_dirs:
        package_path = package_dir / "package.json"
        try:
            package = load_json(package_path)
        except Exception:
            continue
        scripts = package.get("scripts") if isinstance(package.get("scripts"), dict) else {}
        prefix = rel(package_dir, root)
        runner = "pnpm" if (package_dir / "pnpm-lock.yaml").exists() else "npm"
        for script in ("check", "typecheck", "lint", "test", "build"):
            if script in scripts:
                commands.append(f"cd {prefix} && {runner} {script}")
    if (root / "1_PythonServer" / "pyproject.toml").exists():
        commands.append("cd 1_PythonServer && python -m pytest")
    return commands


def run(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        root = resolve_root(payload.get("root_path"))
        max_findings = read_int(payload.get("max_findings"), 200, 1, 1000)
        include_git = read_bool(payload.get("include_git_status"), True)
        scan_local_urls = read_bool(payload.get("scan_local_urls"), True)
        scan_empty_dirs = read_bool(payload.get("scan_empty_dirs"), False)
        findings: list[dict[str, Any]] = []
        package_dirs = collect_package_dirs(root)
        check_package_managers(root, package_dirs, findings)
        check_env_examples(root, package_dirs, findings)
        if scan_local_urls:
            check_local_urls(root, findings)
        check_temp_files(root, findings)
        check_deep_relative_imports(root, findings)
        if scan_empty_dirs:
            check_empty_dirs(root, findings)
        git_lines = git_status(root) if include_git else []
        error_count = sum(1 for item in findings if item["severity"] == "error")
        warning_count = sum(1 for item in findings if item["severity"] == "warning")
        info_count = sum(1 for item in findings if item["severity"] == "info")
        status = "fail" if error_count else "warning" if warning_count else "pass"
        shown_findings = findings[:max_findings]
        summary = f"收尾检查完成：{error_count} 个错误，{warning_count} 个警告，{info_count} 个提示。"
        return ok(summary, {
            "status": status,
            "root_path": str(root),
            "package_dirs": [rel(path, root) for path in package_dirs],
            "error_count": error_count,
            "warning_count": warning_count,
            "info_count": info_count,
            "finding_count": len(findings),
            "findings": shown_findings,
            "truncated": len(findings) > len(shown_findings),
            "git_status": git_lines,
            "recommended_commands": recommended_commands(root, package_dirs),
        })
    except ToolError as exc:
        return fail(exc.code, exc.message, exc.details)


if __name__ == "__main__":
    run_tool(run)
