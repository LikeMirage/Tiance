import asyncio
from functools import lru_cache
import logging
from app.core.shutdown_tasks import finish_commit

from app.domain.llm.generation_params import LlmGenerationParams, LlmReasoningOptions, LlmReasoningMode
from app.services.project.conversation_functional_run import (
    FunctionalConversationRunner, FunctionalConversationScheduler,
    build_functional_conversation_request,
)

from app.repositories.project.conversation_naming_repository import (
    ConversationNamingTaskCreation,
    ProjectConversationNamingRepository,
    get_project_conversation_naming_repository,
)
from app.services.llm.functional_model_settings import (
    LlmFunctionalModelSettingsService,
    get_llm_functional_model_settings_service,
)
from app.services.llm.token_estimation_settings import (
    TokenEstimationSettingsService,
    get_token_estimation_settings_service,
)
from app.services.project.conversation_naming_plan import (
    build_conversation_naming_plan,
)
from app.services.project.conversation_functional_runtime import (
    resolve_functional_conversation_model_target,
)
from app.services.project.conversation_functional_settings import (
    int_setting,
    string_setting,
)
from app.services.project.conversation_run_snapshot import ConversationRunSnapshot
from app.services.project.project_conversations import (
    ProjectConversationService,
    get_project_conversation_service,
)


_DEFAULT_SESSION_TITLE = "新对话"
_DEFAULT_TRIGGER_TOKEN_THRESHOLD = 20_000
logger = logging.getLogger(__name__)


class ProjectConversationNamingService:
    def __init__(
        self,
        conversation_service: ProjectConversationService,
        functional_model_settings_service: LlmFunctionalModelSettingsService,
        naming_repository: ProjectConversationNamingRepository,
        token_estimation_settings_service: TokenEstimationSettingsService,
    ) -> None:
        self._conversation_service = conversation_service
        self._functional_model_settings_service = functional_model_settings_service
        self._naming_repository = naming_repository
        self._token_estimation_settings_service = (
            token_estimation_settings_service
        )
        self._scheduler = FunctionalConversationScheduler()

    def set_functional_conversation_runner(self, runner: FunctionalConversationRunner) -> None:
        self._scheduler.bind(runner)

    async def name_session_if_needed(
        self,
        project_id: str,
        session_id: str,
        *,
        run_snapshot: ConversationRunSnapshot | None = None,
    ) -> ConversationNamingTaskCreation | None:
        if not self._scheduler.ready:
            return None
        async with self._scheduler.serialize(project_id, session_id, "automatic_naming"):
            pending = await asyncio.to_thread(self._naming_repository.list_pending_tasks, project_id)
            for task in pending:
                if task.get("source_session_id") == session_id:
                    await self._run_pending_task(project_id, task["function_session_id"])
                    return None
            creation = None
            async def prepare():
                nonlocal creation
                creation = await self._prepare_task_if_needed(project_id, session_id, run_snapshot=run_snapshot)
            try:
                await finish_commit(prepare())
            except asyncio.CancelledError:
                if creation is not None:
                    await finish_commit(asyncio.to_thread(
                        self._naming_repository.settle_task, project_id, creation.session.session_id, outcome="cancelled",
                    ))
                raise
            if creation is not None:
                await self._run_pending_task(project_id, creation.session.session_id)
            return creation

    async def _prepare_task_if_needed(
        self, project_id: str, session_id: str, *, run_snapshot: ConversationRunSnapshot | None = None,
    ) -> ConversationNamingTaskCreation | None:
        if run_snapshot is None:
            return None
        session = await asyncio.to_thread(
            self._conversation_service.get_session,
            project_id,
            session_id,
        )
        if (
            session is None
            or not session.settings.automatic_naming_enabled
            or session.title != _DEFAULT_SESSION_TITLE
            or session.manual_title
        ):
            return None

        profile = await asyncio.to_thread(
            self._functional_model_settings_service.get_profile_settings,
            "naming",
        )
        settings = profile.settings if profile is not None else {}
        trigger_token_threshold = int_setting(
            settings,
            "triggerTokenThreshold",
            default_value=_DEFAULT_TRIGGER_TOKEN_THRESHOLD,
            minimum=1,
        )
        token_estimation_settings = await asyncio.to_thread(
            self._token_estimation_settings_service.get_settings
        )
        plan = build_conversation_naming_plan(
            run_snapshot,
            trigger_token_threshold=trigger_token_threshold,
            token_estimation_settings=token_estimation_settings,
        )
        if plan is None:
            return None

        configured_prompt = string_setting(settings, "prompt")
        if not configured_prompt:
            return None
        task_prompt = configured_prompt
        target = resolve_functional_conversation_model_target(
            settings,
            source_session=session,
            run_snapshot=run_snapshot,
            task_prompt=task_prompt,
        )

        if target is None:
            return None
        return await asyncio.to_thread(
            self._naming_repository.create_task,
            project_id,
            session_id,
            snapshot_boundary_message_id=plan.snapshot_boundary_message_id,
            target_provider_id=target.provider_id,
            target_model_id=target.model_id,
            target_reasoning_mode=target.reasoning_mode,
            target_settings=target.session_settings,
            mode=target.mode,
            trigger={
                "trigger_type": "automatic_threshold",
                "trigger_token_threshold": trigger_token_threshold,
                "context_token_count": plan.trigger_context_token_count,
                "context_token_source": plan.trigger_context_token_source,
                "selected_context_token_count": (
                    plan.selected_context_token_count
                ),
            },
            task_prompt=task_prompt,
        )

    async def _run_pending_task(self, project_id: str, function_session_id: str) -> None:
        # The claim commits before calling the model, so competing triggers cannot
        # execute the same task. Failed/completed work is never retried here.
        claimed = None
        async def claim():
            nonlocal claimed
            claimed = await asyncio.to_thread(self._naming_repository.claim_task, project_id, function_session_id)
        outcome = "error"
        try:
            await finish_commit(claim())
            if claimed is None:
                return
            session = claimed.session
            request = build_functional_conversation_request(
                project_id=project_id, session=session, prompt=claimed.prompt,
                generation=LlmGenerationParams(
                    max_output_tokens=session.settings.max_output_tokens,
                    temperature=session.settings.temperature, top_p=session.settings.top_p,
                    reasoning=LlmReasoningOptions(mode=LlmReasoningMode(session.reasoning_mode))
                    if session.reasoning_mode else None,
                ),
                feature_key="automatic_naming", task_id=claimed.task["task_id"],
            )
            await self._scheduler.run(request)
            outcome = "done"
        except asyncio.CancelledError:
            outcome = "cancelled"
            raise
        except Exception:
            logger.exception("Automatic naming run failed: %s/%s", project_id, function_session_id)
        finally:
            if claimed is not None:
                await finish_commit(asyncio.to_thread(
                    self._naming_repository.settle_task, project_id, function_session_id, outcome=outcome,
                ))

    async def resume_task(self, project_id: str, source_session_id: str, function_session_id: str) -> None:
        if not self._scheduler.ready:
            return
        async with self._scheduler.serialize(project_id, source_session_id, "automatic_naming"):
            await self._run_pending_task(project_id, function_session_id)

    async def resume_pending_tasks(self, project_id: str) -> None:
        if not self._scheduler.ready:
            return
        tasks = await asyncio.to_thread(self._naming_repository.list_pending_tasks, project_id)
        for task in tasks:
            await self.resume_task(project_id, task["source_session_id"], task["function_session_id"])

    def name_parent_session(
        self,
        project_id: str,
        function_session_id: str,
        *,
        title: str,
    ) -> dict:
        return self._naming_repository.apply_title(
            project_id,
            function_session_id,
            title=title,
        )

    def settle_automatic_naming(
        self,
        project_id: str,
        function_session_id: str,
        *,
        outcome: str,
    ) -> dict:
        return self._naming_repository.settle_task(
            project_id,
            function_session_id,
            outcome=outcome,
        )


@lru_cache
def get_project_conversation_naming_service() -> ProjectConversationNamingService:
    return ProjectConversationNamingService(
        get_project_conversation_service(),
        get_llm_functional_model_settings_service(),
        get_project_conversation_naming_repository(),
        get_token_estimation_settings_service(),
    )
