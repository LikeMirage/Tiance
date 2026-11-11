"""Coordinate explicit workspace removal with in-flight local data access.

Normal operations remain parallel. Removal fails while data is in use; after
recycling, delayed writes cannot recreate the folder until an explicit import.
This registry is process-local and contains no persisted project facts.
"""
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import RLock

from app.core.errors import ConflictError


@dataclass
class _WorkspaceState:
    users: int = 0
    removing: bool = False
    removed: bool = False


_lock = RLock()
_states: dict[Path, _WorkspaceState] = {}


@contextmanager
def workspace_access(workspace: Path, *, registering: bool = False):
    key = workspace.resolve()
    with _lock:
        state = _states.setdefault(key, _WorkspaceState())
        if state.removing or (state.removed and not registering):
            raise ConflictError("项目天策数据正在清除或已移除，请重新添加项目后再操作。")
        was_removed = state.removed
        if registering:
            state.removed = False
        state.users += 1
    try:
        yield
    except BaseException:
        if registering and was_removed:
            with _lock:
                state.removed = True
        raise
    finally:
        with _lock:
            state.users -= 1
            if not state.users and not state.removed:
                _states.pop(key, None)


@contextmanager
def workspace_removal(workspace: Path):
    key = workspace.resolve()
    with _lock:
        state = _states.setdefault(key, _WorkspaceState())
        if state.users or state.removing:
            raise ConflictError("项目数据正在读写，请稍后重试移除。")
        state.removing = True
    try:
        # The owner sets removed immediately after recycling, even if subsequent
        # catalog removal fails. Retrying removal is still allowed.
        yield state
    finally:
        with _lock:
            state.removing = False
            if not state.removed:
                _states.pop(key, None)


@contextmanager
def workspace_file_access(path: Path):
    workspace = next((parent for parent in (path, *path.parents)
                      if parent.name.lower() == ".tiance"), None)
    if workspace is None:
        yield
    else:
        with workspace_access(workspace):
            yield
