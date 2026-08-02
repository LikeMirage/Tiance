from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from functools import lru_cache
from threading import Lock
from uuid import uuid4

from app.core.errors import AppError, NotFoundError
from app.domain.tools import ToolDependencyInstallTask
from app.services.tools.tool_dependencies import (
    ToolDependencyService,
    get_tool_dependency_service,
)


class ToolDependencyTaskService:
    def __init__(
        self,
        dependency_service: ToolDependencyService,
        *,
        max_workers: int = 2,
    ) -> None:
        self._dependency_service = dependency_service
        self._executor = ThreadPoolExecutor(
            max_workers=max(1, max_workers),
            thread_name_prefix="tool-dependency-install",
        )
        self._lock = Lock()
        self._tasks: dict[str, ToolDependencyInstallTask] = {}

    def start_install_task(
        self,
        category_id: str,
        project_id: str,
        *,
        requirement: str | None = None,
        index_url: str | None = None,
    ) -> ToolDependencyInstallTask:
        now = _utc_now()
        task = ToolDependencyInstallTask(
            task_id=f"dep_install_{uuid4().hex[:16]}",
            category_id=category_id,
            project_id=project_id,
            requirement=requirement,
            status="queued",
            message="等待安装。",
            error=None,
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            self._tasks[task.task_id] = task
        self._executor.submit(
            self._run_install_task,
            task.task_id,
            requirement,
            index_url,
        )
        return task

    def get_task(self, task_id: str) -> ToolDependencyInstallTask:
        with self._lock:
            task = self._tasks.get(task_id)
        if task is None:
            raise NotFoundError(f"工具依赖安装任务 '{task_id}' 不存在。")
        return task

    def _run_install_task(
        self,
        task_id: str,
        requirement: str | None,
        index_url: str | None,
    ) -> None:
        task = self._update_task(
            task_id,
            status="running",
            message="正在安装依赖。",
            error=None,
        )
        try:
            result = self._dependency_service.install_dependencies(
                task.category_id,
                task.project_id,
                requirement=requirement,
                index_url=index_url,
            )
        except Exception as exc:
            self._update_task(
                task_id,
                status="error",
                message="依赖安装失败。",
                error=_error_message(exc),
                completed_at=_utc_now(),
            )
            return

        self._update_task(
            task_id,
            status="done",
            message=result.message,
            error=None,
            completed_at=_utc_now(),
            result=result,
        )

    def _update_task(
        self,
        task_id: str,
        **changes,
    ) -> ToolDependencyInstallTask:
        with self._lock:
            current = self._tasks[task_id]
            updated = replace(
                current,
                updated_at=_utc_now(),
                **changes,
            )
            self._tasks[task_id] = updated
            return updated


def _error_message(error: Exception) -> str:
    if isinstance(error, AppError):
        return error.message
    return str(error) or type(error).__name__


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


@lru_cache
def get_tool_dependency_task_service() -> ToolDependencyTaskService:
    return ToolDependencyTaskService(get_tool_dependency_service())
