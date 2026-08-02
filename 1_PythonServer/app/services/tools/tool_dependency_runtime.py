from __future__ import annotations

import subprocess
from typing import Callable

from app.core.errors import BadRequestError

CommandRunner = Callable[[list[str], int], subprocess.CompletedProcess[str]]


def normalize_index_url(index_url: str) -> str:
    normalized = index_url.strip()
    if not normalized.startswith(("http://", "https://")):
        raise BadRequestError("镜像源地址必须以 http:// 或 https:// 开头。")
    return normalized


def run_command(command: list[str], timeout_seconds: int) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(
            command,
            returncode=1,
            stdout=exc.stdout or "",
            stderr="安装依赖超时。",
        )
