from functools import lru_cache
from json import loads

from app.core.errors import BadRequestError, ConflictError, NotFoundError
from app.domain.file_workspace import FileEntryKind, FileEntryNode, FileEntryTree
from app.infra.file_workspace import FileWorkspaceStorage, get_file_workspace_storage
from app.infra.tools import ToolProjectConfigStorage, get_tool_project_config_storage
from app.infra.tools.tool_project_config_constants import (
    TOOL_EXAMPLES_FILE,
    TOOL_FOLDER_MANIFEST_FILE,
    TOOL_INPUT_SCHEMA_FILE,
    TOOL_OUTPUT_SCHEMA_FILE,
)
from app.services.tools.tool_registry import ToolRegistryService, get_tool_registry_service
from app.services.tools.tool_projects import ToolProjectService, get_tool_project_service


class ToolFolderFileService:
    def __init__(
        self,
        config_storage: ToolProjectConfigStorage,
        file_storage: FileWorkspaceStorage,
        registry_service: ToolRegistryService | None = None,
        tool_project_service: ToolProjectService | None = None,
    ) -> None:
        self._config_storage = config_storage
        self._file_storage = file_storage
        self._registry_service = registry_service
        self._tool_projects = tool_project_service

    def list_tree(
        self,
        category_id: str,
        project_id: str,
        *,
        query: str | None = None,
        parent_path: str | None = None,
    ) -> tuple[FileEntryNode, ...]:
        return self.list_tree_result(
            category_id,
            project_id,
            query=query,
            parent_path=parent_path,
        ).items

    def list_tree_result(
        self,
        category_id: str,
        project_id: str,
        *,
        query: str | None = None,
        parent_path: str | None = None,
    ) -> FileEntryTree:
        folder_root = self._require_project_root(category_id, project_id)
        try:
            return self._file_storage.list_tree_result(
                folder_root,
                query=query,
                parent_path=parent_path,
            )
        except FileNotFoundError as exc:
            raise BadRequestError(str(exc)) from exc
        except ValueError as exc:
            raise BadRequestError(str(exc)) from exc

    def create_entry(
        self,
        category_id: str,
        project_id: str,
        *,
        parent_path: str | None,
        kind: FileEntryKind,
        name: str | None,
    ) -> FileEntryNode:
        folder_root = self._require_writable_project_root(category_id, project_id)
        try:
            return self._file_storage.create_entry(
                folder_root,
                parent_path=parent_path,
                kind=kind,
                name=name,
            )
        except FileExistsError as exc:
            raise BadRequestError("同名文件或文件夹已存在。") from exc
        except ValueError as exc:
            raise BadRequestError(str(exc)) from exc

    def rename_entry(
        self,
        category_id: str,
        project_id: str,
        *,
        target_path: str,
        name: str,
    ) -> FileEntryNode:
        folder_root = self._require_writable_project_root(category_id, project_id)
        try:
            node = self._file_storage.rename_entry(
                folder_root,
                target_path=target_path,
                name=name,
            )
        except FileNotFoundError as exc:
            raise BadRequestError(str(exc)) from exc
        except ValueError as exc:
            raise BadRequestError(str(exc)) from exc
        if _is_tool_standard_file_path(target_path):
            self._rebuild_registry()
        return node

    def read_text_file(
        self,
        category_id: str,
        project_id: str,
        target_path: str,
    ) -> tuple[str, int]:
        folder_root = self._require_project_root(category_id, project_id)
        try:
            return self._file_storage.read_text_file(folder_root, target_path)
        except FileNotFoundError as exc:
            raise NotFoundError(str(exc)) from exc
        except ValueError as exc:
            raise BadRequestError(str(exc)) from exc

    def get_file_path(
        self,
        category_id: str,
        project_id: str,
        target_path: str,
    ):
        folder_root = self._require_project_root(category_id, project_id)
        try:
            return self._file_storage.resolve_file_path(folder_root, target_path)
        except FileNotFoundError as exc:
            raise NotFoundError(str(exc)) from exc
        except ValueError as exc:
            raise BadRequestError(str(exc)) from exc

    def write_text_file(
        self,
        category_id: str,
        project_id: str,
        target_path: str,
        content: str,
        *,
        expected_mtime_ms: int | None = None,
    ) -> FileEntryNode:
        folder_root = self._require_writable_project_root(category_id, project_id)
        if _is_tool_standard_file_path(target_path):
            content = self._config_storage.normalize_standard_file_content(
                target_path,
                content,
            )
            if _is_tool_manifest_file_path(target_path):
                self._ensure_manifest_identity_available(project_id, content)
        try:
            node = self._file_storage.write_text_file(
                folder_root,
                target_path,
                content,
                expected_mtime_ms=expected_mtime_ms,
            )
        except ValueError as exc:
            raise BadRequestError(str(exc)) from exc
        if _is_tool_standard_file_path(target_path):
            self._rebuild_registry()
        return node

    def delete_entry(self, category_id: str, project_id: str, target_path: str) -> None:
        folder_root = self._require_writable_project_root(category_id, project_id)
        try:
            self._file_storage.delete_entry(folder_root, target_path)
        except ValueError as exc:
            raise BadRequestError(str(exc)) from exc
        if _is_tool_standard_file_path(target_path):
            self._rebuild_registry()

    def move_entry(
        self,
        category_id: str,
        project_id: str,
        *,
        target_path: str,
        target_parent_path: str | None,
    ) -> FileEntryNode:
        folder_root = self._require_writable_project_root(category_id, project_id)
        try:
            node = self._file_storage.move_entry(
                folder_root,
                target_path=target_path,
                target_parent_path=target_parent_path,
            )
        except FileNotFoundError as exc:
            raise BadRequestError(str(exc)) from exc
        except ValueError as exc:
            raise BadRequestError(str(exc)) from exc
        if _is_tool_standard_file_path(target_path):
            self._rebuild_registry()
        return node

    def copy_entry(
        self,
        category_id: str,
        project_id: str,
        *,
        target_path: str,
        target_parent_path: str | None,
    ) -> FileEntryNode:
        folder_root = self._require_writable_project_root(category_id, project_id)
        try:
            node = self._file_storage.copy_entry(
                folder_root,
                target_path=target_path,
                target_parent_path=target_parent_path,
            )
        except FileNotFoundError as exc:
            raise BadRequestError(str(exc)) from exc
        except ValueError as exc:
            raise BadRequestError(str(exc)) from exc
        if _is_tool_standard_file_path(target_path):
            self._rebuild_registry()
        return node

    def reveal_entry(self, category_id: str, project_id: str, target_path: str) -> None:
        folder_root = self._require_project_root(category_id, project_id)
        try:
            self._file_storage.reveal_entry(folder_root, target_path)
        except FileNotFoundError as exc:
            raise BadRequestError(str(exc)) from exc
        except ValueError as exc:
            raise BadRequestError(str(exc)) from exc

    def open_entry_external(self, category_id: str, project_id: str, target_path: str):
        folder_root = self._require_project_root(category_id, project_id)
        try:
            return self._file_storage.open_entry_external(folder_root, target_path)
        except FileNotFoundError as exc:
            raise BadRequestError(str(exc)) from exc
        except ValueError as exc:
            raise BadRequestError(str(exc)) from exc

    def _require_project_root(self, category_id: str, project_id: str) -> str:
        if self._tool_projects is None:
            raise RuntimeError("工具项目服务未配置。")
        return self._tool_projects.require_tool_project(category_id, project_id).root_path

    def _require_writable_project_root(self, category_id: str, project_id: str) -> str:
        return self._require_project_root(category_id, project_id)

    def _rebuild_registry(self) -> None:
        if self._registry_service is not None:
            self._registry_service.rebuild_registry()

    def _ensure_manifest_identity_available(self, project_id: str, content: str) -> None:
        if self._registry_service is None:
            return
        payload = loads(content)
        call_name = payload.get("name")
        for entry in self._registry_service.list_entries(enabled_only=False):
            if entry.project_id == project_id:
                continue
            if entry.tool_name == call_name:
                raise ConflictError("同名工具调用名称已存在。")


def _is_tool_standard_file_path(target_path: str) -> bool:
    normalized = target_path.strip().replace("\\", "/").strip("/")
    return normalized in {
        TOOL_FOLDER_MANIFEST_FILE,
        TOOL_INPUT_SCHEMA_FILE,
        TOOL_OUTPUT_SCHEMA_FILE,
        TOOL_EXAMPLES_FILE,
    }


def _is_tool_manifest_file_path(target_path: str) -> bool:
    return target_path.strip().replace("\\", "/").strip("/") == TOOL_FOLDER_MANIFEST_FILE


@lru_cache
def get_tool_folder_file_service() -> ToolFolderFileService:
    return ToolFolderFileService(
        get_tool_project_config_storage(),
        get_file_workspace_storage(),
        get_tool_registry_service(),
        get_tool_project_service(),
    )
