from __future__ import annotations

import json
from pathlib import Path
import subprocess
from typing import Callable

from app.core.errors import BadRequestError

CommandRunner = Callable[[list[str], int], subprocess.CompletedProcess[str]]


def resolve_tool_site_packages(tool_root: Path) -> Path:
    dependencies_root = tool_root / "dependencies" / "py313"
    legacy_site_packages = dependencies_root / "site-packages"
    pointer_file = dependencies_root / "active.json"
    if not pointer_file.is_file():
        return legacy_site_packages
    try:
        payload = json.loads(pointer_file.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return legacy_site_packages
    relative_value = payload.get("site_packages") if isinstance(payload, dict) else None
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != 1
        or not isinstance(relative_value, str)
        or not relative_value.strip()
    ):
        return legacy_site_packages
    relative_path = Path(relative_value)
    resolved_root = dependencies_root.resolve(strict=False)
    resolved_target = (resolved_root / relative_path).resolve(strict=False)
    try:
        resolved_target.relative_to(resolved_root)
    except ValueError:
        return legacy_site_packages
    if relative_path.is_absolute() or not resolved_target.is_dir():
        return legacy_site_packages
    return resolved_target


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
