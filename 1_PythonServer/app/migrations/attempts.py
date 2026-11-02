"""Do not repeat an unchanged, failed project initialization on every UI request."""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


def _signature(path: Path) -> tuple | None:
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None
    return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)


@dataclass(frozen=True)
class _Failure:
    inputs: dict[Path, tuple | None]
    message: str


_failures: dict[Path, _Failure] = {}
_inputs: ContextVar[dict[Path, tuple | None] | None] = ContextVar("migration_inputs", default=None)


def track_input(path: Path) -> None:
    """Include external legacy data (also missing files) in automatic retry decisions."""
    inputs = _inputs.get()
    if inputs is not None and path not in inputs:
        inputs[path] = _signature(path)


@contextmanager
def initialization_attempt(path: Path) -> Iterator[None]:
    """Caller holds the per-database lock; close/rollback its connection inside here.

    Only deterministic validation failures are remembered, never SQLite busy errors,
    IO failures or cancellation. Database/input changes or a process restart retry.
    Keep messages and file metadata only, not exception frames or audit contents.
    """
    previous = _failures.get(path)
    if previous and all(_signature(item) == signature for item, signature in previous.inputs.items()):
        raise RuntimeError(previous.message)
    _failures.pop(path, None)
    inputs: dict[Path, tuple | None] = {}
    token = _inputs.set(inputs)
    try:
        yield
    except (RuntimeError, ValueError) as error:
        # Failed migrations roll back before this fingerprint is captured. WAL and
        # database metadata can change during rollback/connection close.
        try:
            for item in (path, Path(f"{path}-wal")):
                inputs[item] = _signature(item)
            _failures[path] = _Failure(inputs, str(error))
        except OSError:
            pass  # A transient filesystem failure must remain retryable.
        raise
    finally:
        _inputs.reset(token)
