from pathlib import Path

from app.repositories.project.conversation_storage import (
    ProjectWorkspaceDirectoryResolver,
)
from app.repositories.project.conversation_database import (
    read_meta,
    write_meta,
)


class ProjectWorkspaceStateStore:
    def __init__(self, workspace_resolver: ProjectWorkspaceDirectoryResolver | None = None) -> None:
        self._workspace_resolver = workspace_resolver or ProjectWorkspaceDirectoryResolver()

    def read_state(self, project_root: str) -> dict | None:
        workspace_dir = self._workspace_dir(project_root, for_write=False)
        payload = read_meta(workspace_dir / "conversations", "workspace_state")
        return payload if isinstance(payload, dict) else None

    def write_state(self, project_root: str, payload: dict) -> dict:
        workspace_dir = self._workspace_dir(project_root, for_write=True)
        write_meta(workspace_dir / "conversations", "workspace_state", payload)
        return payload

    def _workspace_dir(self, project_root: str, *, for_write: bool) -> Path:
        workspace_dir = self._workspace_resolver.resolve_workspace_dir(
            Path(project_root),
            for_write=for_write,
        )
        return workspace_dir
