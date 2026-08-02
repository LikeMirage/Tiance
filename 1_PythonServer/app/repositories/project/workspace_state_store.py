from json import dumps, loads
from pathlib import Path

from app.repositories.project.conversation_storage import (
    ProjectWorkspaceDirectoryResolver,
    atomic_write_text,
)

_STATE_FILE = "state.json"


class ProjectWorkspaceStateStore:
    def __init__(self, workspace_resolver: ProjectWorkspaceDirectoryResolver | None = None) -> None:
        self._workspace_resolver = workspace_resolver or ProjectWorkspaceDirectoryResolver()

    def read_state(self, project_root: str) -> dict | None:
        state_path = self._state_path(project_root, for_write=False)
        if not state_path.is_file():
            return None
        try:
            payload = loads(state_path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return None
        return payload if isinstance(payload, dict) else None

    def write_state(self, project_root: str, payload: dict) -> dict:
        state_path = self._state_path(project_root, for_write=True)
        atomic_write_text(
            state_path,
            dumps(payload, ensure_ascii=False, indent=2),
        )
        return payload

    def _state_path(self, project_root: str, *, for_write: bool) -> Path:
        workspace_dir = self._workspace_resolver.resolve_workspace_dir(
            Path(project_root),
            for_write=for_write,
        )
        return workspace_dir / _STATE_FILE
