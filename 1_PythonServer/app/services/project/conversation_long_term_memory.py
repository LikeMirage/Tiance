from __future__ import annotations

import asyncio
from dataclasses import dataclass
from functools import lru_cache
from uuid import uuid4

from app.core.errors import ConflictError
from app.domain.llm.chat import (
    ChatCompletionRequest,
    ChatMessage,
    ChatMessageRole,
)
from app.domain.project.project_conversation import ProjectConversationSession
from app.repositories.project.conversation_long_term_memory_repository import (
    GLOBAL_MEMORY_REPOSITORY_DEFINITION,
    PROJECT_MEMORY_REPOSITORY_DEFINITION,
    LongTermMemoryRepositoryDefinition,
    ProjectConversationLongTermMemoryRepository,
    get_project_conversation_long_term_memory_repository,
)
from app.services.llm.functional_model_settings import (
    LlmFunctionalModelSettingsService,
    get_llm_functional_model_settings_service,
)
from app.services.llm.token_estimation_settings import (
    TokenEstimationSettingsService,
    get_token_estimation_settings_service,
)
from app.services.project.conversation_functional_run import (
    TRANSIENT_FUNCTION_ERROR_CODES,
    FunctionalConversationRunError,
    FunctionalConversationRunner,
)
from app.services.project.conversation_functional_runtime import (
    resolve_functional_conversation_model_target,
)
from app.services.project.conversation_functional_settings import (
    bool_setting,
    int_setting,
    string_setting,
)
from app.services.project.conversation_long_term_memory_plan import (
    build_long_term_memory_management_plan,
)
from app.services.project.conversation_run_snapshot import ConversationRunSnapshot
from app.services.project.project_conversations import (
    ProjectConversationService,
    get_project_conversation_service,
)


DEFAULT_FAILURE_RETRY_COUNT = 3
MAX_FAILURE_RETRY_COUNT = 10


@dataclass(frozen=True, slots=True)
class MemoryManagementProfileDefinition:
    default_trigger_token_threshold: int
    extraction_setting_name: str
    profile_key: str
    repository: LongTermMemoryRepositoryDefinition
    task_id_prefix: str
    usage_feature_key: str


PROJECT_MEMORY_PROFILE = MemoryManagementProfileDefinition(
    default_trigger_token_threshold=20_000,
    extraction_setting_name="project_memory_extraction_enabled",
    profile_key="projectMemoryManagement",
    repository=PROJECT_MEMORY_REPOSITORY_DEFINITION,
    task_id_prefix="pmem",
    usage_feature_key="project_memory_management",
)
GLOBAL_MEMORY_PROFILE = MemoryManagementProfileDefinition(
    default_trigger_token_threshold=100_000,
    extraction_setting_name="global_memory_extraction_enabled",
    profile_key="globalMemoryManagement",
    repository=GLOBAL_MEMORY_REPOSITORY_DEFINITION,
    task_id_prefix="gmem",
    usage_feature_key="global_memory_management",
)
MEMORY_MANAGEMENT_PROFILES = (
    PROJECT_MEMORY_PROFILE,
    GLOBAL_MEMORY_PROFILE,
)


class MissingMemoryManagementToolCallError(RuntimeError):
    pass


class ProjectConversationLongTermMemoryService:
    def __init__(
        self,
        conversation_service: ProjectConversationService,
        functional_model_settings_service: LlmFunctionalModelSettingsService,
        repositories: tuple[ProjectConversationLongTermMemoryRepository, ...],
        token_estimation_settings_service: TokenEstimationSettingsService,
    ) -> None:
        self._conversation_service = conversation_service
        self._functional_model_settings_service = (
            functional_model_settings_service
        )
        self._repositories = {
            repository.definition.scope: repository
            for repository in repositories
        }
        if set(self._repositories) != {"project", "global"}:
            raise ValueError(
                "Project and global memory management repositories are required."
            )
        self._token_estimation_settings_service = (
            token_estimation_settings_service
        )
        self._functional_conversation_runner: FunctionalConversationRunner | None = None
        self._locks: dict[tuple[str, str, str], asyncio.Lock] = {}

    def set_functional_conversation_runner(
        self,
        runner: FunctionalConversationRunner,
    ) -> None:
        self._functional_conversation_runner = runner

    async def manage_context_if_enabled(
        self,
        project_id: str,
        session_id: str,
        *,
        blocking: bool | None = None,
        session_snapshot: ProjectConversationSession | None = None,
        run_snapshot: ConversationRunSnapshot | None = None,
    ) -> None:
        if run_snapshot is None or self._functional_conversation_runner is None:
            return
        for profile_definition in MEMORY_MANAGEMENT_PROFILES:
            lock = self._locks.setdefault(
                (profile_definition.repository.scope, project_id, session_id),
                asyncio.Lock(),
            )
            async with lock:
                await self._manage_context_once(
                    profile_definition,
                    project_id,
                    session_id,
                    blocking=blocking,
                    session_snapshot=session_snapshot,
                    run_snapshot=run_snapshot,
                )

    async def manage_request_if_enabled(
        self,
        project_id: str,
        session_id: str,
        *,
        blocking: bool | None = None,
        model_request: ChatCompletionRequest,
        session_snapshot: ProjectConversationSession | None = None,
    ) -> None:
        await self.manage_context_if_enabled(
            project_id,
            session_id,
            blocking=blocking,
            session_snapshot=session_snapshot,
            run_snapshot=ConversationRunSnapshot(
                model_request=model_request,
                assistant_response=ChatMessage(
                    role=ChatMessageRole.ASSISTANT,
                    content="",
                ),
                context_tokens=None,
                context_tokens_estimated=False,
            ),
        )

    async def _manage_context_once(
        self,
        profile_definition: MemoryManagementProfileDefinition,
        project_id: str,
        session_id: str,
        *,
        blocking: bool | None,
        session_snapshot: ProjectConversationSession | None,
        run_snapshot: ConversationRunSnapshot,
    ) -> None:
        repository = self._repositories[profile_definition.repository.scope]
        if await asyncio.to_thread(
            repository.is_long_term_memory_function_session,
            project_id,
            session_id,
        ):
            return
        session = session_snapshot or await asyncio.to_thread(
            self._conversation_service.get_session,
            project_id,
            session_id,
        )
        if session is None:
            return
        if not getattr(
            session.settings,
            profile_definition.extraction_setting_name,
        ):
            return

        profile = await asyncio.to_thread(
            self._functional_model_settings_service.get_profile_settings,
            profile_definition.profile_key,
        )
        settings = profile.settings if profile is not None else {}
        prompt = string_setting(settings, "prompt")
        if not prompt:
            return
        threshold = int_setting(
            settings,
            "triggerTokenThreshold",
            default_value=(
                profile_definition.default_trigger_token_threshold
            ),
            minimum=1,
        )
        state = await asyncio.to_thread(
            repository.read_state,
            project_id,
            session_id,
        )
        previous_boundary = (
            state.get("last_completed_boundary_message_id")
            if state is not None
            else None
        )
        messages = await asyncio.to_thread(
            self._conversation_service.list_messages,
            project_id,
            session_id,
        )
        token_estimation_settings = await asyncio.to_thread(
            self._token_estimation_settings_service.get_settings
        )
        plan = build_long_term_memory_management_plan(
            messages,
            session.settings,
            previous_boundary_message_id=(
                previous_boundary
                if isinstance(previous_boundary, str)
                else None
            ),
            trigger_token_threshold=threshold,
            token_estimation_settings=token_estimation_settings,
        )
        if plan is None:
            return

        target = resolve_functional_conversation_model_target(
            settings,
            source_session=session,
            run_snapshot=run_snapshot,
            task_prompt=prompt,
        )
        if target is None:
            return
        retry_count = int_setting(
            settings,
            "failureRetryCount",
            default_value=DEFAULT_FAILURE_RETRY_COUNT,
            minimum=0,
            maximum=MAX_FAILURE_RETRY_COUNT,
        )
        is_blocking = bool_setting(
            settings,
            "blockingEnabled",
            default_value=False,
        )
        if blocking is not None and is_blocking != blocking:
            return
        trigger = {
            "trigger_type": "incremental_token_threshold",
            "trigger_token_threshold": threshold,
            "newly_covered_token_count": plan.newly_covered_token_count,
            "previous_boundary_message_id": plan.previous_boundary_message_id,
            "snapshot_boundary_message_id": plan.snapshot_boundary_message_id,
            "blocking": is_blocking,
        }
        first_task_id: str | None = None
        for attempt_index in range(retry_count + 1):
            task_id = (
                f"{profile_definition.task_id_prefix}_"
                f"{uuid4().hex[:16]}"
            )
            if first_task_id is None:
                first_task_id = task_id
            creation = None
            try:
                creation = await asyncio.to_thread(
                    repository.create_task,
                    project_id,
                    session_id,
                    task_id=task_id,
                    previous_boundary_message_id=(
                        plan.previous_boundary_message_id
                    ),
                    snapshot_boundary_message_id=(
                        plan.snapshot_boundary_message_id
                    ),
                    newly_covered_message_ids=(
                        plan.newly_covered_message_ids
                    ),
                    target_provider_id=target.provider_id,
                    target_model_id=target.model_id,
                    target_reasoning_mode=target.reasoning_mode,
                    target_settings=target.session_settings,
                    mode=target.mode,
                    trigger=trigger,
                    attempt_index=attempt_index,
                    retry_of=(
                        first_task_id
                        if attempt_index > 0
                        else None
                    ),
                )
                await asyncio.to_thread(
                    repository.mark_task_running,
                    project_id,
                    creation.session.session_id,
                )
                request = ChatCompletionRequest(
                    provider_id=target.provider_id,
                    model_id=target.model_id,
                    project_id=project_id,
                    session_id=creation.session.session_id,
                    messages=(
                        ChatMessage(
                            role=ChatMessageRole.USER,
                            content=prompt,
                        ),
                    ),
                    generation=target.generation,
                    record_usage=True,
                    usage_message_id=(
                        f"system:{profile_definition.usage_feature_key}:"
                        f"{task_id}"
                    ),
                    usage_feature_key=profile_definition.usage_feature_key,
                    return_thinking_content=False,
                    max_tool_calls=creation.session.settings.max_tool_calls,
                )
                await self._functional_conversation_runner(request)
                await asyncio.to_thread(
                    self._validate_function_run,
                    project_id,
                    creation.session.session_id,
                    prompt,
                )
                await asyncio.to_thread(
                    repository.mark_task_completed,
                    project_id,
                    creation.session.session_id,
                )
                return
            except asyncio.CancelledError:
                if creation is not None:
                    await asyncio.to_thread(
                        repository.mark_task_failed,
                        project_id,
                        creation.session.session_id,
                        reason="CancelledError",
                        message=f"{profile_definition.repository.label}任务已取消。",
                    )
                raise
            except ConflictError:
                if creation is not None:
                    await asyncio.to_thread(
                        repository.mark_task_failed,
                        project_id,
                        creation.session.session_id,
                        reason="stale_result",
                        message=(
                            f"{profile_definition.repository.label}"
                            "任务边界已经变化。"
                        ),
                    )
                return
            except Exception as exc:
                if creation is not None:
                    await asyncio.to_thread(
                        repository.mark_task_failed,
                        project_id,
                        creation.session.session_id,
                        reason=type(exc).__name__,
                        message=str(exc),
                    )
                allowed_retries = (
                    min(retry_count, 1)
                    if isinstance(
                        exc,
                        MissingMemoryManagementToolCallError,
                    )
                    else retry_count
                )
                if (
                    isinstance(exc, FunctionalConversationRunError)
                    and exc.code
                    and exc.code not in TRANSIENT_FUNCTION_ERROR_CODES
                ):
                    return
                if attempt_index >= allowed_retries:
                    return
                await asyncio.sleep(min(2 ** attempt_index, 4))

    def _validate_function_run(
        self,
        project_id: str,
        function_session_id: str,
        prompt: str,
    ) -> None:
        messages = self._conversation_service.list_messages(
            project_id,
            function_session_id,
        )
        task_message_index = next(
            (
                index
                for index in range(len(messages) - 1, -1, -1)
                if messages[index].role == "user"
                and messages[index].content.strip() == prompt.strip()
            ),
            None,
        )
        task_messages = (
            messages[task_message_index + 1 :]
            if task_message_index is not None
            else ()
        )
        tool_names = tuple(
            tool_call.name
            for message in task_messages
            if message.role == "assistant"
            for tool_call in message.tool_calls
        )
        if not tool_names:
            raise MissingMemoryManagementToolCallError(
                "长期记忆管理会话没有调用 manage_memory。"
            )
        if any(name != "manage_memory" for name in tool_names):
            raise MissingMemoryManagementToolCallError(
                "长期记忆管理会话调用了非 manage_memory 工具。"
            )
        if any(
            message.role == "tool"
            and message.name == "manage_memory"
            and message.status == "error"
            for message in task_messages
        ):
            raise MissingMemoryManagementToolCallError(
                "manage_memory 工具调用失败。"
            )


@lru_cache
def get_project_conversation_long_term_memory_service(
) -> ProjectConversationLongTermMemoryService:
    return ProjectConversationLongTermMemoryService(
        get_project_conversation_service(),
        get_llm_functional_model_settings_service(),
        (
            get_project_conversation_long_term_memory_repository("project"),
            get_project_conversation_long_term_memory_repository("global"),
        ),
        get_token_estimation_settings_service(),
    )
