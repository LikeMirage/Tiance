from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


class FileExplorerOpenError(RuntimeError):
    pass


def reveal_path_in_file_explorer(path: Path) -> None:
    """在系统文件管理器中定位一个已存在的本地路径。"""
    try:
        target = path.expanduser().resolve(strict=True)
    except OSError as exc:
        raise FileExplorerOpenError("Path does not exist.") from exc

    try:
        if sys.platform == "win32":
            if target.is_file():
                subprocess.Popen(
                    ["explorer", "/select,", str(target)],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            else:
                os.startfile(str(target))  # type: ignore[attr-defined]
            return

        opener = "open" if sys.platform == "darwin" else "xdg-open"
        subprocess.Popen(
            [opener, str(target if target.is_dir() else target.parent)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as exc:
        raise FileExplorerOpenError("Unable to reveal path in file explorer.") from exc


def open_path_with_default_application(path: Path) -> None:
    """使用系统默认应用打开一个已存在的本地路径。"""
    try:
        target = path.expanduser().resolve(strict=True)
    except OSError as exc:
        raise FileExplorerOpenError("Path does not exist.") from exc

    try:
        if sys.platform == "win32":
            os.startfile(str(target))  # type: ignore[attr-defined]
            return

        opener = "open" if sys.platform == "darwin" else "xdg-open"
        subprocess.Popen(
            [opener, str(target)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as exc:
        raise FileExplorerOpenError("Unable to open path with the default application.") from exc


def open_directory_in_file_explorer(directory: Path) -> None:
    try:
        target = directory.resolve(strict=True)
    except OSError as exc:
        raise FileExplorerOpenError("Directory does not exist.") from exc
    if not target.is_dir():
        raise FileExplorerOpenError("Target is not a directory.")

    try:
        if sys.platform == "win32":
            os.startfile(str(target))  # type: ignore[attr-defined]
            return

        opener = "open" if sys.platform == "darwin" else "xdg-open"
        subprocess.run(
            [opener, str(target)],
            check=True,
            stderr=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise FileExplorerOpenError("Unable to open directory in file explorer.") from exc
