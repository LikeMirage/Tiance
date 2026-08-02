from __future__ import annotations

from base64 import b64decode
import json
import os
from pathlib import Path
import subprocess
from threading import Event, Thread, Timer
from typing import Any, TextIO


RG_BINARY = Path(__file__).resolve().parent / "bin" / "windows-x64" / "rg.exe"


class RipgrepError(Exception):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def search(
    *,
    query: str,
    use_regex: bool,
    case_sensitive: bool,
    include_globs: list[str],
    exclude_globs: list[str],
    exclude_dirs: set[str],
    max_file_size: int,
    max_matches: int,
    context_lines: int,
    timeout_seconds: int,
    encoding: str,
    root: Path,
    base: Path,
) -> dict[str, Any]:
    if not RG_BINARY.is_file():
        raise RipgrepError(
            "DEPENDENCY_MISSING",
            "workspace_grep 缺少内置 rg.exe。",
            {"expected_path": str(RG_BINARY)},
        )
    result = _execute(
        _build_command(
            query=query,
            use_regex=use_regex,
            case_sensitive=case_sensitive,
            include_globs=include_globs,
            exclude_globs=exclude_globs,
            exclude_dirs=exclude_dirs,
            max_file_size=max_file_size,
            encoding=encoding,
        ),
        root=root,
        base=base,
        max_matches=max_matches,
        timeout_seconds=timeout_seconds,
    )
    if context_lines:
        _attach_context(result["matches"], context_lines, encoding)
    return result


def _build_command(
    *,
    query: str,
    use_regex: bool,
    case_sensitive: bool,
    include_globs: list[str],
    exclude_globs: list[str],
    exclude_dirs: set[str],
    max_file_size: int,
    encoding: str,
) -> list[str]:
    command = [
        str(RG_BINARY),
        "--json",
        "--stats",
        "--line-number",
        "--column",
        "--color",
        "never",
        "--no-config",
        "--max-filesize",
        str(max_file_size),
        "--encoding",
        encoding,
        "--case-sensitive" if case_sensitive else "--ignore-case",
        "--pcre2" if use_regex else "--fixed-strings",
    ]
    for pattern in include_globs:
        command.extend(("--glob", pattern))
    for pattern in exclude_globs:
        command.extend(("--glob", f"!{pattern.lstrip('!')}"))
    for directory in sorted(exclude_dirs):
        normalized = directory.strip().strip("/\\")
        if normalized:
            command.extend(("--glob", f"!**/{normalized}/**"))
    command.extend(("--", query, "."))
    return command


def _execute(
    command: list[str],
    *,
    root: Path,
    base: Path,
    max_matches: int,
    timeout_seconds: int,
) -> dict[str, Any]:
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        process = subprocess.Popen(
            command,
            cwd=str(base),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=creationflags,
        )
    except OSError as exc:
        raise RipgrepError(
            "DEPENDENCY_UNAVAILABLE",
            "无法启动内置 rg.exe。",
            {"message": str(exc)},
        ) from exc

    timed_out = Event()
    stderr_parts: list[str] = []
    stderr_thread = Thread(
        target=_read_stderr,
        args=(process.stderr, stderr_parts),
        daemon=True,
    )
    stderr_thread.start()

    def kill_on_timeout() -> None:
        if process.poll() is None:
            timed_out.set()
            process.kill()

    timer = Timer(timeout_seconds, kill_on_timeout)
    timer.daemon = True
    timer.start()
    matches: list[dict[str, Any]] = []
    searched_files = 0
    truncated = False
    try:
        if process.stdout is None:
            raise RipgrepError("SEARCH_FAILED", "无法读取 rg.exe 输出。")
        for raw_line in process.stdout:
            event = _parse_json_line(raw_line)
            if event is None:
                continue
            event_type = event.get("type")
            data = event.get("data")
            if not isinstance(data, dict):
                continue
            if event_type == "match":
                match = _match_from_event(data, root=root, base=base)
                if match is not None:
                    matches.append(match)
                if len(matches) >= max_matches:
                    truncated = True
                    process.terminate()
                    break
            elif event_type == "end":
                searched_files += _stats_searches(data.get("stats"))
            elif event_type == "summary":
                searched_files = _stats_searches(data.get("stats"))
    finally:
        timer.cancel()
        if process.stdout is not None:
            process.stdout.close()

    try:
        return_code = process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()
        return_code = process.wait(timeout=2)
    stderr_thread.join(timeout=1)
    stderr = "".join(stderr_parts).strip()

    if timed_out.is_set():
        raise RipgrepError(
            "SEARCH_TIMEOUT",
            f"搜索在 {timeout_seconds} 秒后超时。",
            {"timeout_seconds": timeout_seconds},
        )
    if not truncated and return_code not in {0, 1}:
        code = "INVALID_REGEX" if _looks_like_regex_error(stderr) else "SEARCH_FAILED"
        message = "正则表达式无效。" if code == "INVALID_REGEX" else "ripgrep 搜索失败。"
        raise RipgrepError(code, message, {"stderr": stderr, "return_code": return_code})
    return {
        "matches": matches,
        "searched_files": searched_files,
        "truncated": truncated,
    }


def _read_stderr(stream: TextIO | None, parts: list[str]) -> None:
    if stream is None:
        return
    remaining = 20_000
    try:
        for chunk in iter(lambda: stream.read(4096), ""):
            if remaining <= 0:
                continue
            parts.append(chunk[:remaining])
            remaining -= len(chunk)
    finally:
        stream.close()


def _parse_json_line(raw_line: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(raw_line)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _match_from_event(
    data: dict[str, Any],
    *,
    root: Path,
    base: Path,
) -> dict[str, Any] | None:
    path_text = _json_text(data.get("path"))
    line_bytes = _json_bytes(data.get("lines"))
    line_number = data.get("line_number")
    if not path_text or not isinstance(line_number, int) or line_number < 1:
        return None

    path = Path(path_text)
    if not path.is_absolute():
        path = base / path
    resolved = path.resolve(strict=False)
    try:
        relative_path = resolved.relative_to(root).as_posix()
    except ValueError:
        return None

    submatches = data.get("submatches")
    start_byte = 0
    if isinstance(submatches, list) and submatches and isinstance(submatches[0], dict):
        raw_start = submatches[0].get("start")
        if isinstance(raw_start, int) and raw_start >= 0:
            start_byte = raw_start
    return {
        "file": relative_path,
        "path": str(resolved),
        "line": line_number,
        "column": len(line_bytes[:start_byte].decode("utf-8", errors="replace")) + 1,
        "text": line_bytes.decode("utf-8", errors="replace").rstrip("\r\n"),
        "before": [],
        "after": [],
    }


def _json_text(value: object) -> str:
    return _json_bytes(value).decode("utf-8", errors="replace")


def _json_bytes(value: object) -> bytes:
    if not isinstance(value, dict):
        return b""
    text = value.get("text")
    if isinstance(text, str):
        return text.encode("utf-8")
    encoded = value.get("bytes")
    if isinstance(encoded, str):
        try:
            return b64decode(encoded)
        except ValueError:
            return b""
    return b""


def _stats_searches(value: object) -> int:
    if not isinstance(value, dict):
        return 0
    searches = value.get("searches")
    return searches if isinstance(searches, int) and searches >= 0 else 0


def _attach_context(
    matches: list[dict[str, Any]],
    context_lines: int,
    encoding: str,
) -> None:
    file_cache: dict[str, list[str]] = {}
    for match in matches:
        path = str(match["path"])
        lines = file_cache.get(path)
        if lines is None:
            try:
                raw = Path(path).read_bytes()
                lines = _decode_context(raw, encoding).splitlines()
            except (OSError, UnicodeError, LookupError):
                lines = []
            file_cache[path] = lines
        index = int(match["line"]) - 1
        match["before"] = lines[max(0, index - context_lines) : index]
        match["after"] = lines[index + 1 : index + 1 + context_lines]


def _decode_context(data: bytes, encoding: str) -> str:
    if encoding != "auto":
        return data.decode(encoding)
    if data.startswith(b"\xef\xbb\xbf"):
        return data.decode("utf-8-sig")
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")
    return data.decode("utf-8")


def _looks_like_regex_error(stderr: str) -> bool:
    lowered = stderr.lower()
    return "regex parse error" in lowered or "pcre2" in lowered
