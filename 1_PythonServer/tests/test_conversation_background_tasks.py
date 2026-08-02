import asyncio
from unittest.mock import patch

from app.api.routes.project import conversations as conversation_routes
from app.services.project.conversation_background_tasks import (
    ConversationBackgroundTaskRegistry,
)


def test_cancel_session_only_stops_tasks_owned_by_that_session():
    async def run_test():
        registry = ConversationBackgroundTaskRegistry()
        first_started = asyncio.Event()
        first_finished = asyncio.Event()
        second_started = asyncio.Event()
        release_second = asyncio.Event()

        async def first_task():
            first_started.set()
            try:
                await asyncio.Event().wait()
            finally:
                first_finished.set()

        async def second_task():
            second_started.set()
            await release_second.wait()

        first = registry.create_task(
            "project-1",
            "session-1",
            first_task(),
            name="first-session-task",
        )
        second = registry.create_task(
            "project-1",
            "session-2",
            second_task(),
            name="second-session-task",
        )
        await asyncio.gather(first_started.wait(), second_started.wait())

        await registry.cancel_session("project-1", "session-1")

        assert first.cancelled()
        assert first_finished.is_set()
        assert not second.done()

        release_second.set()
        await second
        await registry.close()

    asyncio.run(run_test())


def test_delete_stops_main_run_and_background_tasks_before_removing_session():
    calls: list[str] = []

    class RunManager:
        async def stop(self, project_id: str, session_id: str) -> bool:
            calls.append(f"stop:{project_id}:{session_id}")
            return True

    class BackgroundTasks:
        async def cancel_session(self, project_id: str, session_id: str) -> None:
            calls.append(f"cancel:{project_id}:{session_id}")

    class ConversationService:
        def delete_session(self, project_id: str, session_id: str) -> None:
            calls.append(f"delete:{project_id}:{session_id}")

    with (
        patch.object(conversation_routes, "get_conversation_run_manager", return_value=RunManager()),
        patch.object(
            conversation_routes,
            "get_conversation_background_task_registry",
            return_value=BackgroundTasks(),
        ),
        patch.object(
            conversation_routes,
            "get_project_conversation_service",
            return_value=ConversationService(),
        ),
    ):
        asyncio.run(conversation_routes.delete_project_conversation("project-1", "session-1"))

    assert calls == [
        "stop:project-1:session-1",
        "cancel:project-1:session-1",
        "delete:project-1:session-1",
    ]
