from __future__ import annotations

from pathlib import Path
from typing import BinaryIO


BACKEND_LOG_RELATIVE_PATH = Path("Data") / "logs" / "desktop-backend.log"
PREVIOUS_BACKEND_LOG_NAME = "desktop-backend.previous.log"
MAX_BACKEND_LOG_BYTES = 2 * 1024 * 1024


def backend_log_path(project_root: Path) -> Path:
    return project_root / BACKEND_LOG_RELATIVE_PATH


def open_backend_process_log(project_root: Path) -> BinaryIO:
    log_file = backend_log_path(project_root)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    _rotate_oversized_log(log_file)
    return log_file.open("ab", buffering=0)


def _rotate_oversized_log(log_file: Path) -> None:
    try:
        if log_file.stat().st_size <= MAX_BACKEND_LOG_BYTES:
            return
    except FileNotFoundError:
        return

    previous_log = log_file.with_name(PREVIOUS_BACKEND_LOG_NAME)
    previous_log.unlink(missing_ok=True)
    log_file.replace(previous_log)
