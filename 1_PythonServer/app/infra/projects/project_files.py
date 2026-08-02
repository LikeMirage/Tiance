from app.infra.file_workspace import FileWorkspaceStorage, get_file_workspace_storage

ProjectFileStorage = FileWorkspaceStorage
get_project_file_storage = get_file_workspace_storage

__all__ = ["ProjectFileStorage", "get_project_file_storage"]
