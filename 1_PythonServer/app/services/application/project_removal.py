"""Optional workspace-data cleanup when deregistering an external project."""
from functools import lru_cache

from app.core.errors import BadRequestError, ConflictError, NotFoundError
from app.core.shutdown_tasks import finish_thread, shutdown_tasks
from app.domain.project import ProjectKind
from app.infra.projects import get_project_storage
from app.infra.projects.workspace_lifecycle import workspace_removal
from app.services.project.projects import get_project_service
from app.services.project.conversation_run_manager import get_conversation_run_manager
from app.services.project.conversation_background_tasks import get_conversation_background_task_registry
from app.services.project.conversation_audit import get_conversation_audit_service


class ProjectRemovalApplicationService:
    def __init__(self, projects, storage, runs, background, audit):
        self._projects = projects
        self._storage = storage
        self._activity_owners = (runs, background, audit)

    @shutdown_tasks.request
    async def remove_with_data(self, project_id: str) -> None:
        project = await finish_thread(self._projects.get_project, project_id)
        if project is None:
            raise NotFoundError("项目不存在。")
        if project.project_kind is ProjectKind.PROVIDER or self._projects.is_managed_project(project):
            raise BadRequestError("清除天策数据选项仅用于移除外部项目。")
        try:
            workspace = self._storage.validate_project_data_recycle(project.root_path)
        except (OSError, ValueError) as exc:
            raise BadRequestError(str(exc)) from exc
        # Reserve the workspace before checking producers, on the event loop.
        # New requests cannot create data after the idle check.
        with workspace_removal(workspace) as state:
            if any(owner.has_project_activity(project.project_id) for owner in self._activity_owners):
                raise ConflictError("该项目仍有会话或后台任务正在运行、收尾或等待保存，请完成后再清除天策数据。")
            shutdown_tasks.commit_started()
            await finish_thread(self._remove, project, state)

    def _remove(self, project, state) -> None:
        try:
            self._storage.recycle_project_data(project.root_path)
        except (OSError, ValueError) as exc:
            raise BadRequestError(f"天策数据未能移入系统回收站，项目登记已保留：{exc}") from exc
        state.removed = True
        try:
            self._projects.remove_external_project_registration(project)
        except Exception as exc:
            raise BadRequestError(
                "天策数据已清除，但项目登记移除失败。可重试移除登记；工作文件未删除。",
                details={"reason": "project_deregistration_failed", "tiance_data_cleared": True,
                         "project_id": project.project_id},
            ) from exc


@lru_cache
def get_project_removal_application_service() -> ProjectRemovalApplicationService:
    return ProjectRemovalApplicationService(
        get_project_service(), get_project_storage(), get_conversation_run_manager(),
        get_conversation_background_task_registry(), get_conversation_audit_service(),
    )
