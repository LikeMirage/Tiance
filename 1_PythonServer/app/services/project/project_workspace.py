# 项目工作区状态服务
# 保存和恢复项目的展开路径、打开文件等 UI 状态到项目目录下

from functools import lru_cache
from pathlib import PurePosixPath
from threading import RLock

from app.core.errors import BadRequestError, NotFoundError
from app.repositories.project.workspace_state_store import ProjectWorkspaceStateStore
from app.repositories.project import ProjectRepository, get_project_repository


class ProjectWorkspaceService:
    def __init__(
        self,
        repository: ProjectRepository,
        state_store: ProjectWorkspaceStateStore | None = None,
    ) -> None:
        self._repository = repository
        self._state_store = state_store or ProjectWorkspaceStateStore()
        self._state_lock = RLock()

    def get_state(
        self,
        project_id: str,
    ) -> dict | None:
        with self._state_lock:
            project = self._require_project(project_id)
            return self._state_store.read_state(project.root_path)

    def save_state(
        self,
        project_id: str,
        *,
        expanded_paths: list[str],
        open_file_paths: list[str],
        active_file_path: str | None,
        active_dashboard: str | None = None,
    ) -> dict:
        with self._state_lock:
            project = self._require_project(project_id)
            payload = {
                "expanded_paths": expanded_paths,
                "open_file_paths": open_file_paths,
                "active_file_path": active_file_path,
                "active_dashboard": active_dashboard,
            }
            return self._state_store.write_state(project.root_path, payload)

    def patch_state(
        self,
        project_id: str,
        *,
        expanded_paths: list[str] | None = None,
        should_update_expanded_paths: bool = False,
        open_file_paths: list[str] | None = None,
        should_update_open_file_paths: bool = False,
        active_file_path: str | None = None,
        should_update_active_file_path: bool = False,
        active_dashboard: str | None = None,
        should_update_active_dashboard: bool = False,
    ) -> dict:
        with self._state_lock:
            current = self.get_state(project_id) or {}
            next_state = {
                "expanded_paths": current.get("expanded_paths", []),
                "open_file_paths": current.get("open_file_paths", []),
                "active_file_path": current.get("active_file_path"),
                "active_dashboard": current.get("active_dashboard"),
            }

            if should_update_expanded_paths:
                next_state["expanded_paths"] = expanded_paths or []
            if should_update_open_file_paths:
                next_state["open_file_paths"] = open_file_paths or []
            if should_update_active_file_path:
                next_state["active_file_path"] = active_file_path
            if should_update_active_dashboard:
                next_state["active_dashboard"] = active_dashboard

            return self.save_state(
                project_id,
                expanded_paths=next_state["expanded_paths"],
                open_file_paths=next_state["open_file_paths"],
                active_file_path=next_state["active_file_path"],
                active_dashboard=next_state["active_dashboard"],
            )

    def apply_editor_tabs_action(
        self,
        project_id: str,
        *,
        action: str,
        path: str | None = None,
        paths: list[str] | None = None,
    ) -> dict:
        with self._state_lock:
            current = self.get_state(project_id) or {}
            open_file_paths = _normalize_workspace_paths(current.get("open_file_paths", []))
            active_file_path = _normalize_optional_workspace_path(
                current.get("active_file_path"),
            )
            if active_file_path not in open_file_paths:
                active_file_path = open_file_paths[0] if open_file_paths else None

            target_path = _normalize_optional_workspace_path(path)
            requested_paths = _normalize_workspace_paths(paths or [])
            closed_file_paths: list[str] = []

            if action == "list_tabs":
                return _editor_tabs_action_result(
                    current,
                    action=action,
                    open_file_paths=open_file_paths,
                    active_file_path=active_file_path,
                    closed_file_paths=closed_file_paths,
                )

            if action == "open_file":
                if not target_path:
                    raise BadRequestError("open_file 需要 path 参数。")
                if target_path not in open_file_paths:
                    open_file_paths.append(target_path)
                active_file_path = target_path
                current["active_dashboard"] = None
            elif action == "focus_file":
                if not target_path:
                    raise BadRequestError("focus_file 需要 path 参数。")
                if target_path not in open_file_paths:
                    raise BadRequestError("目标文件当前没有打开。")
                active_file_path = target_path
                current["active_dashboard"] = None
            elif action == "close_clean_tabs":
                target_paths = set(requested_paths or open_file_paths)
                closed_file_paths = [
                    file_path for file_path in open_file_paths if file_path in target_paths
                ]
                active_index = (
                    open_file_paths.index(active_file_path)
                    if active_file_path in open_file_paths
                    else 0
                )
                open_file_paths = [
                    file_path for file_path in open_file_paths if file_path not in target_paths
                ]
                if active_file_path in closed_file_paths:
                    active_file_path = (
                        open_file_paths[min(active_index, len(open_file_paths) - 1)]
                        if open_file_paths
                        else None
                    )
            elif action == "close_others_clean":
                keep_path = target_path or active_file_path
                if not keep_path or keep_path not in open_file_paths:
                    raise BadRequestError("没有找到需要保留的当前项目标签页。")
                closed_file_paths = [
                    file_path for file_path in open_file_paths if file_path != keep_path
                ]
                open_file_paths = [keep_path]
                active_file_path = keep_path
            else:
                raise BadRequestError(f"不支持的标签页操作：{action}")

            next_state = self.save_state(
                project_id,
                expanded_paths=list(current.get("expanded_paths", [])),
                open_file_paths=open_file_paths,
                active_file_path=active_file_path,
                active_dashboard=current.get("active_dashboard"),
            )
            return _editor_tabs_action_result(
                next_state,
                action=action,
                open_file_paths=open_file_paths,
                active_file_path=active_file_path,
                closed_file_paths=closed_file_paths,
            )

    def _require_project(self, project_id: str):
        project = self._repository.get_project(project_id)
        if project is None:
            raise NotFoundError(f"项目 '{project_id}' 不存在。")
        return project


def _normalize_workspace_paths(values: list[object]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        path = _normalize_optional_workspace_path(value)
        if not path or path in seen:
            continue
        seen.add(path)
        normalized.append(path)
    return normalized


def _normalize_optional_workspace_path(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw_path = value.strip().replace("\\", "/")
    parsed = PurePosixPath(raw_path)
    if parsed.is_absolute() or ".." in parsed.parts:
        raise BadRequestError("文件路径必须位于项目目录内。")
    normalized = "/".join(part for part in parsed.parts if part not in {"", "."})
    if not normalized or ":" in parsed.parts[0]:
        raise BadRequestError("文件路径无效。")
    return normalized


def _editor_tabs_action_result(
    state: dict,
    *,
    action: str,
    open_file_paths: list[str],
    active_file_path: str | None,
    closed_file_paths: list[str],
) -> dict:
    return {
        "action": action,
        "expanded_paths": list(state.get("expanded_paths", [])),
        "open_file_paths": open_file_paths,
        "active_file_path": active_file_path,
        "active_dashboard": state.get("active_dashboard"),
        "closed_file_paths": closed_file_paths,
    }


@lru_cache
def get_project_workspace_service() -> ProjectWorkspaceService:
    return ProjectWorkspaceService(get_project_repository())
