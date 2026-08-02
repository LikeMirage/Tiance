from __future__ import annotations

import os
import subprocess
from pathlib import Path

from package_environment import RuntimePaths


def install_packages(
    runtime_paths: RuntimePaths,
    target_directory: Path,
    packages: tuple[str, ...],
    *,
    index_url: str,
    timeout_seconds: int,
) -> subprocess.CompletedProcess[str]:
    command = [
        str(runtime_paths.python_executable),
        str(runtime_paths.pip_runner),
        "--isolated",
        "install",
        "--disable-pip-version-check",
        "--no-input",
        "--no-warn-script-location",
        "--upgrade",
        "--target",
        str(target_directory),
        "--index-url",
        index_url,
        *packages,
    ]
    env = {
        key: value
        for key in (
            "COMSPEC",
            "PATH",
            "PATHEXT",
            "SystemRoot",
            "TEMP",
            "TMP",
            "WINDIR",
        )
        if (value := os.environ.get(key))
    }
    env["PYTHONNOUSERSITE"] = "1"
    try:
        return subprocess.run(
            command,
            cwd=str(target_directory.parent),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(
            command,
            returncode=124,
            stdout=exc.stdout or "",
            stderr=f"依赖安装超过 {timeout_seconds} 秒，已停止。",
        )
