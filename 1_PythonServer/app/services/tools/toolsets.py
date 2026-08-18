from dataclasses import dataclass
from functools import lru_cache
import json
from pathlib import Path
from uuid import uuid4

from app.core.atomic_replace import atomic_replace_path
from app.core.errors import BadRequestError
from app.domain.tools import ToolFolder, Toolset
from app.infra.tools.tool_project_config_constants import (
    TOOL_FOLDER_MANIFEST_FILE,
)
from app.services.tools.tool_projects import ToolProjectService, get_tool_project_service
from app.services.tools.tool_registry import ToolRegistryService, get_tool_registry_service


@dataclass(frozen=True)
class ToolFolderRuntimeSettingsResult:
    folder: ToolFolder
    enabled: bool
    dynamic: bool
    parallel: bool


class ToolsetService:
    def __init__(
        self,
        project_service: ToolProjectService,
        registry_service: ToolRegistryService | None = None,
    ) -> None:
        self._projects = project_service
        self._registry_service = registry_service

    def ensure_default_toolsets(self) -> None:
        self._projects.ensure_default_category()
        self._rebuild_registry()

    def list_toolsets(self) -> tuple[Toolset, ...]:
        return self._projects.list_toolsets()

    def create_toolset(self, *, name: str | None = None) -> Toolset:
        return self._projects.create_toolset(name=name)

    def rename_toolset(self, category_id: str, *, name: str) -> Toolset:
        toolset = self._projects.rename_toolset(category_id, name=name)
        self._rebuild_registry()
        return toolset

    def delete_toolset(self, category_id: str) -> None:
        self._projects.delete_toolset(category_id)

    def list_tool_folders(self, category_id: str) -> tuple[ToolFolder, ...]:
        return self._projects.list_tool_folders(category_id)

    def create_tool_folder(self, category_id: str, *, name: str | None = None) -> ToolFolder:
        return self._projects.create_tool_folder(category_id, name=name)

    def rename_tool_folder(self, category_id: str, project_id: str, *, name: str) -> ToolFolder:
        folder = self._projects.rename_tool_folder(category_id, project_id, name=name)
        self._rebuild_registry()
        return folder

    def delete_tool_folder(self, category_id: str, project_id: str) -> None:
        self._projects.delete_tool_folder(category_id, project_id)
        self._rebuild_registry()

    def move_tool_folder(
        self,
        category_id: str,
        project_id: str,
        *,
        target_category_id: str,
    ) -> ToolFolder:
        folder = self._projects.move_tool_folder(
            category_id,
            project_id,
            target_category_id=target_category_id,
        )
        self._rebuild_registry()
        return folder

    def set_tool_folder_runtime_settings(
        self,
        category_id: str,
        project_id: str,
        *,
        enabled: bool | None,
        dynamic: bool | None,
        parallel: bool | None,
    ) -> ToolFolderRuntimeSettingsResult:
        if enabled is None and dynamic is None and parallel is None:
            raise BadRequestError("至少需要修改一项工具运行设置。")
        project = self._projects.require_tool_project(category_id, project_id)
        manifest_path = Path(project.root_path) / TOOL_FOLDER_MANIFEST_FILE
        if not manifest_path.is_file():
            raise BadRequestError("当前工具项目尚未配置 tool.json。")
        payload = _read_object(manifest_path)

        state = payload.get("state")
        if not isinstance(state, dict):
            state = {"enabled": True}
            payload["state"] = state
        current_enabled = state.get("enabled")
        if not isinstance(current_enabled, bool):
            current_enabled = True
            state["enabled"] = current_enabled
        if enabled is not None:
            current_enabled = enabled
            state["enabled"] = enabled

        loading = payload.get("loading")
        if not isinstance(loading, dict):
            loading = {"dynamic": True}
            payload["loading"] = loading
        current_dynamic = loading.get("dynamic")
        if not isinstance(current_dynamic, bool):
            current_dynamic = True
            loading["dynamic"] = current_dynamic
        if dynamic is not None:
            current_dynamic = dynamic
            loading["dynamic"] = dynamic

        execution = payload.get("execution")
        if not isinstance(execution, dict) or not isinstance(execution.get("parallel"), bool):
            raise BadRequestError("tool.json 缺少有效的 execution.parallel。")
        current_parallel = execution["parallel"]
        if parallel is not None:
            current_parallel = parallel
            execution["parallel"] = parallel

        _write_object(manifest_path, payload)
        self._rebuild_registry()
        updated = self._projects.require_tool_project(category_id, project_id)
        return ToolFolderRuntimeSettingsResult(
            folder=self._projects.folder_for_project(updated),
            enabled=current_enabled,
            dynamic=current_dynamic,
            parallel=current_parallel,
        )

    def reveal_tool_folder(self, category_id: str, project_id: str) -> None:
        self._projects.reveal_tool_folder(category_id, project_id)

    def _rebuild_registry(self) -> None:
        if self._registry_service is not None:
            self._registry_service.rebuild_registry()


def _read_object(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BadRequestError("tool.json 不是合法 JSON。") from exc
    if not isinstance(payload, dict):
        raise BadRequestError("tool.json 必须是 JSON 对象。")
    return payload


def _write_object(path: Path, payload: dict[str, object]) -> None:
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    atomic_replace_path(temporary, path)


@lru_cache
def get_toolset_service() -> ToolsetService:
    return ToolsetService(
        get_tool_project_service(),
        get_tool_registry_service(),
    )
