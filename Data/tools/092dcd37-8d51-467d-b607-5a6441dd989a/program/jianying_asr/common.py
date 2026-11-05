from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path


class ASRError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def error_details(exc: Exception) -> tuple[str, str]:
    """Keep local and per-part failures on the same sanitized output contract."""
    if isinstance(exc, ModuleNotFoundError):
        return "DEPENDENCY_MISSING", f"缺少依赖 {exc.name}，请安装 program/requirements.txt。"
    code = exc.code if isinstance(exc, ASRError) else "LOCAL_ERROR"
    message = str(exc) if isinstance(exc, (ASRError, OSError)) else f"本地处理失败（{type(exc).__name__}）。"
    return code, message


class Budget:
    """One total budget, read from the tool's standard runtime configuration."""
    def __init__(self, seconds: int):
        if type(seconds) is not int or seconds <= 0:
            raise ASRError("CONFIG_ERROR", "runtime.timeout_seconds 必须是正整数。")
        self.deadline = time.monotonic() + seconds

    def remaining(self) -> float:
        value = self.deadline - time.monotonic()
        if value <= 0:
            raise ASRError("TIMEOUT", "已达到 tool.json 中配置的工具总执行时限。")
        return value

    def sleep(self, seconds: float) -> None:
        time.sleep(min(seconds, self.remaining()))
        self.remaining()


# Windows readers (including indexers/scanners) can temporarily deny deletion of
# an open file. Retry only those replace failures, for at most 0.93 seconds.
# This is local I/O recovery, not a second tool/recognition timeout. Persistent
# access errors still propagate, and an active job's total budget is respected.
_REPLACE_DELAYS = (0.03, 0.06, 0.12, 0.24, 0.48)
_WINDOWS_REPLACE_ERRORS = {5, 32, 33}


def atomic_replace(source: Path, target: Path, *, budget: Budget | None = None) -> None:
    for delay in (*_REPLACE_DELAYS, None):
        if budget is not None:
            budget.remaining()
        try:
            os.replace(source, target)
            return
        except PermissionError as exc:
            if delay is None or getattr(exc, "winerror", None) not in _WINDOWS_REPLACE_ERRORS:
                raise
            if budget is not None:
                budget.sleep(delay)
            else:
                time.sleep(delay)


def write_json(path: Path, value: object, *, budget: Budget | None = None) -> None:
    # A private temporary also prevents another writer from truncating this
    # pending checkpoint while Windows briefly holds the destination open.
    fd, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
        atomic_replace(temporary, path, budget=budget)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            # Never hide the original failure because temporary cleanup failed.
            pass
