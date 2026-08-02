import os
from pathlib import Path
from time import sleep


_REPLACE_RETRY_DELAYS_SECONDS = (0.03, 0.06, 0.12, 0.24, 0.48)
_WINDOWS_TRANSIENT_REPLACE_ERRORS = {5, 32, 33}


def atomic_replace_path(source_path: Path, target_path: Path) -> None:
    for delay_seconds in (*_REPLACE_RETRY_DELAYS_SECONDS, None):
        try:
            os.replace(source_path, target_path)
            return
        except PermissionError as exc:
            if (
                delay_seconds is None
                or getattr(exc, "winerror", None)
                not in _WINDOWS_TRANSIENT_REPLACE_ERRORS
            ):
                raise
            sleep(delay_seconds)
