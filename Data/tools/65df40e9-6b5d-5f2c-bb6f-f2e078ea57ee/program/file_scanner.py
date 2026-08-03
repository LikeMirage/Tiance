from __future__ import annotations

from dataclasses import dataclass
import fnmatch
import os
from pathlib import Path
from typing import Iterable


DEFAULT_EXCLUDED_DIRECTORIES = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".tiance",
        ".market-cache",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "__pycache__",
        "node_modules",
        "dependencies",
        "dist",
        "build",
        "coverage",
        ".coverage",
        ".venv",
        "venv",
        "env",
    }
)

SENSITIVE_FILE_NAMES = frozenset(
    {
        ".env",
        "credentials.json",
        "id_rsa",
        "id_ed25519",
        "known_hosts",
    }
)

SENSITIVE_SUFFIXES = (
    ".pem",
    ".key",
    ".pfx",
    ".p12",
    ".jks",
    ".keystore",
)

BINARY_SUFFIXES = frozenset(
    {
        ".7z",
        ".avi",
        ".bmp",
        ".class",
        ".db",
        ".dll",
        ".doc",
        ".docx",
        ".dylib",
        ".exe",
        ".gif",
        ".gz",
        ".ico",
        ".jar",
        ".jpeg",
        ".jpg",
        ".mov",
        ".mp3",
        ".mp4",
        ".o",
        ".obj",
        ".pdf",
        ".png",
        ".ppt",
        ".pptx",
        ".pyc",
        ".pyd",
        ".so",
        ".sqlite",
        ".sqlite3",
        ".tar",
        ".tif",
        ".tiff",
        ".wav",
        ".webp",
        ".woff",
        ".woff2",
        ".xls",
        ".xlsx",
        ".zip",
    }
)


@dataclass(frozen=True)
class ScanConfig:
    source_path: str = "."
    max_file_bytes: int = 5 * 1024 * 1024
    include_globs: tuple[str, ...] = ()
    exclude_globs: tuple[str, ...] = ()


@dataclass(frozen=True)
class FileCandidate:
    absolute_path: Path
    relative_path: str
    size: int
    modified_ns: int


@dataclass(frozen=True)
class ScanIssue:
    path: str
    reason: str


@dataclass(frozen=True)
class DecodedText:
    content: str
    encoding: str


def scan_files(
    workspace_root: Path,
    source_root: Path,
    database_path: Path,
    config: ScanConfig,
) -> tuple[list[FileCandidate], list[ScanIssue], list[dict[str, object]]]:
    candidates: list[FileCandidate] = []
    issues: list[ScanIssue] = []
    skipped: list[dict[str, object]] = []

    def on_walk_error(error: OSError) -> None:
        path = str(getattr(error, "filename", "") or source_root)
        issues.append(ScanIssue(_safe_relative(Path(path), workspace_root), str(error)))

    paths: Iterable[Path]
    if source_root.is_file():
        paths = (source_root,)
    else:
        discovered: list[Path] = []
        for current, directories, files in os.walk(source_root, topdown=True, followlinks=False, onerror=on_walk_error):
            current_path = Path(current)
            directories[:] = [
                name
                for name in directories
                if not _excluded_directory(current_path / name, workspace_root, config)
            ]
            discovered.extend(current_path / name for name in files)
        paths = discovered

    database_family = {
        database_path.resolve(strict=False),
        Path(f"{database_path}-wal").resolve(strict=False),
        Path(f"{database_path}-shm").resolve(strict=False),
    }
    for path in paths:
        resolved = path.resolve(strict=False)
        relative = _safe_relative(resolved, workspace_root)
        if resolved in database_family or path.is_symlink():
            continue
        reason = _excluded_file_reason(path, relative, config)
        if reason:
            skipped.append({"path": relative, "reason": reason})
            continue
        try:
            stat = path.stat()
        except OSError as exc:
            issues.append(ScanIssue(relative, str(exc)))
            continue
        if stat.st_size > config.max_file_bytes:
            skipped.append({"path": relative, "reason": "文件超过索引大小限制", "size": stat.st_size})
            continue
        candidates.append(
            FileCandidate(
                absolute_path=resolved,
                relative_path=relative,
                size=stat.st_size,
                modified_ns=stat.st_mtime_ns,
            )
        )

    candidates.sort(key=lambda item: item.relative_path.casefold())
    return candidates, issues, skipped


def read_text_file(candidate: FileCandidate) -> DecodedText:
    raw = candidate.absolute_path.read_bytes()
    if b"\x00" in raw[:8192] and not raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        raise ValueError("检测到二进制内容")

    attempts: list[tuple[str, bytes]] = []
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        attempts.append(("utf-16", raw))
    attempts.extend((("utf-8-sig", raw), ("gb18030", raw), ("cp1252", raw)))
    last_error: UnicodeError | None = None
    for encoding, content in attempts:
        try:
            text = content.decode(encoding)
        except UnicodeError as exc:
            last_error = exc
            continue
        if _control_character_ratio(text) > 0.02:
            raise ValueError("控制字符比例过高，疑似二进制文件")
        return DecodedText(content=text, encoding=encoding)
    raise ValueError(f"无法识别文本编码：{last_error}")


def _excluded_directory(path: Path, workspace_root: Path, config: ScanConfig) -> bool:
    if path.name.casefold() in DEFAULT_EXCLUDED_DIRECTORIES:
        return True
    relative = _safe_relative(path, workspace_root)
    return _matches_any(relative, config.exclude_globs)


def _excluded_file_reason(path: Path, relative: str, config: ScanConfig) -> str | None:
    name = path.name.casefold()
    if name in SENSITIVE_FILE_NAMES or name.startswith(".env.") or name.endswith(SENSITIVE_SUFFIXES):
        return "敏感凭据文件"
    if path.suffix.casefold() in BINARY_SUFFIXES:
        return "已知二进制文件"
    if config.include_globs and not _matches_any(relative, config.include_globs):
        return "不符合包含规则"
    if _matches_any(relative, config.exclude_globs):
        return "符合排除规则"
    return None


def _matches_any(relative: str, patterns: tuple[str, ...]) -> bool:
    normalized = relative.replace("\\", "/")
    return any(fnmatch.fnmatchcase(normalized, pattern.replace("\\", "/")) for pattern in patterns)


def _safe_relative(path: Path, root: Path) -> str:
    try:
        return path.resolve(strict=False).relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _control_character_ratio(text: str) -> float:
    if not text:
        return 0.0
    controls = sum(1 for char in text[:100_000] if ord(char) < 32 and char not in "\n\r\t\f")
    return controls / min(len(text), 100_000)
