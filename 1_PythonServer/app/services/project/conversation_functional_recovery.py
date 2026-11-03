"""Resume committed but unstarted functional tasks without loading message history."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from app.repositories.project.project_repository import get_project_repository
from app.repositories.project.conversation_naming_repository import get_project_conversation_naming_repository
from app.services.project.conversation_background_tasks import get_conversation_background_task_registry
from app.services.project.conversation_naming import get_project_conversation_naming_service

logger = logging.getLogger(__name__)


async def resume_pending_functional_tasks() -> None:
    # Constructing the stream service binds the same ordinary runner to all policies.
    from app.services.project.conversation_stream import get_project_conversation_stream_service
    try:
        get_project_conversation_stream_service()
        naming = get_project_conversation_naming_service()
        registry = get_conversation_background_task_registry()
        repository = get_project_conversation_naming_repository()
        projects = await asyncio.to_thread(get_project_repository().list_projects)
    except Exception:
        logger.exception("Could not initialize pending functional task recovery")
        return
    for project in projects:
        if not (Path(project.root_path) / ".Tiance" / "tiance.db").is_file():
            continue

        try:
            tasks = await asyncio.to_thread(repository.list_pending_tasks, project.project_id)
        except Exception:
            logger.exception("Could not read pending functional tasks for project %s", project.project_id)
            continue
        for task in tasks:
            async def resume(project_id=project.project_id, task=task):
                try:
                    await naming.resume_task(project_id, task["source_session_id"], task["function_session_id"])
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("Could not resume functional task %s", task["task_id"])

            # Source deletion and application shutdown own cancellation, just as
            # they do for tasks triggered after a normal response.
            registry.create_task(project.project_id, task["source_session_id"], resume(), name="functional-task-recovery")
