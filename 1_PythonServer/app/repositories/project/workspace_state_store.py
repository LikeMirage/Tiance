from pathlib import Path

from app.repositories.project.conversation_storage import (
    ProjectWorkspaceDirectoryResolver,
    conversation_write_lock,
)
from app.repositories.project.conversation_records import (
    read_workspace_state,
    write_workspace_state,
)


class ProjectWorkspaceStateStore:
    def __init__(self, workspace_resolver: ProjectWorkspaceDirectoryResolver | None = None) -> None:
        self._workspace_resolver = workspace_resolver or ProjectWorkspaceDirectoryResolver()

    def read_state(self, project_root: str) -> dict | None:
        workspace_dir = self._workspace_dir(project_root, for_write=False)
        return read_workspace_state(workspace_dir)

    def write_state(self, project_root: str, payload: dict) -> dict:
        workspace_dir = self._workspace_dir(project_root, for_write=True)
        with conversation_write_lock(workspace_dir):
            write_workspace_state(workspace_dir, payload)
        return payload

    def _workspace_dir(self, project_root: str, *, for_write: bool) -> Path:
        workspace_dir = self._workspace_resolver.resolve_workspace_dir(
            Path(project_root),
            for_write=for_write,
        )
        return workspace_dir
