from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


class FileExplorerOpenError(RuntimeError):
    pass


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
