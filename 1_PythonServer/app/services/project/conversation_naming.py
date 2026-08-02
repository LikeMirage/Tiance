import asyncio
from functools import lru_cache

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

    async def name_session_if_needed(
        self,
        project_id: str,
        session_id: str,
        *,
        run_snapshot: ConversationRunSnapshot | None = None,
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
