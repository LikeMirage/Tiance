from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from functools import lru_cache
from hashlib import sha256
import json
from typing import Any
from uuid import uuid4

from app.core.errors import AppError, ConflictError
from app.domain.llm.chat import (
    ChatCompletionRequest,
    ChatMessage,
    ChatMessageRole,
)
from app.domain.llm.token_estimation_settings import TokenEstimationSettings
from app.domain.project.project_conversation import (
    ProjectConversationSession,
)
from app.repositories.project.conversation_compaction_repository import (
    ProjectConversationCompactionRepository,
    get_project_conversation_compaction_repository,
)
from app.repositories.project.conversation_memory_repository import (
    ProjectConversationMemoryRepository,
    get_project_conversation_memory_repository,
)
from app.repositories.llm.provider_adaptation_rules_repository import (
    ProviderAdaptationRulesRepository,
    get_provider_adaptation_rules_repository,
)
from app.services.llm.chat.service import ChatCompletionService
from app.services.llm.functional_model_settings import (
    LlmFunctionalModelSettingsService,
    get_llm_functional_model_settings_service,
)
from app.services.llm.token_estimation_settings import (
    TokenEstimationSettingsService,
    get_token_estimation_settings_service,
)
from app.services.llm.usage.estimation import (
    estimate_token_count,
)
from app.services.project.conversation_memory_compaction import (
    COMPACTION_SOURCE_TYPE,
    build_conversation_compaction_plan,
    build_manual_conversation_compaction_plan,
    compaction_source_message_ids,
    latest_completed_compaction,
)
from app.services.project.conversation_memory_context import (
    build_compressed_context_messages,
)
from app.services.project.conversation_memory_delivery import (
    ProjectConversationMemoryDeliveryService,
)
from app.services.project.conversation_message_groups import (
    protocol_safe_message_ids,
)
from app.services.project.conversation_memory_results import (
    parse_compaction_result,
)
from app.services.project.conversation_functional_runtime import (
    resolve_functional_conversation_model_target,
)
from app.services.project.conversation_functional_run import (
    TRANSIENT_FUNCTION_ERROR_CODES,
    FunctionalConversationRunError,
    FunctionalConversationRunner,
)
from app.services.project.conversation_functional_settings import (
    bool_setting,
    int_setting,
    string_setting,
)
from app.services.project.conversation_functional_snapshot import (
    context_token_measurement,
)
from app.services.project.conversation_run_snapshot import (
    ConversationRunSnapshot,
)
from app.services.project.conversation_request_messages import (
    build_conversation_request_messages,
)
from app.services.project.project_conversations import (
    ProjectConversationService,
    get_project_conversation_service,
)


_MEMORY_PROFILE_KEY = "memoryCompression"
_COMPACTION_STATUS_MESSAGE_NAME = "memory_compaction"
DEFAULT_COMPACTION_FAILURE_RETRY_COUNT = 0
MAX_COMPACTION_FAILURE_RETRY_COUNT = 10
class MissingCompactionSubmissionError(RuntimeError):
    pass


class ProjectConversationMemoryService:
    def __init__(
        self,
        conversation_service: ProjectConversationService,
        memory_repository: ProjectConversationMemoryRepository,
        functional_model_settings_service: LlmFunctionalModelSettingsService,
        chat_service: ChatCompletionService | None = None,
        compaction_repository: ProjectConversationCompactionRepository | None = None,
        token_estimation_settings_service: TokenEstimationSettingsService | None = None,
        adaptation_rules_repository: ProviderAdaptationRulesRepository | None = None,
    ) -> None:
        self._conversation_service = conversation_service
        self._memory_repository = memory_repository
        self._functional_model_settings_service = functional_model_settings_service
        self._compaction_repository = (
            compaction_repository
            or get_project_conversation_compaction_repository()
        )
        self._token_estimation_settings_service = (
            token_estimation_settings_service
            or get_token_estimation_settings_service()
        )
        self._functional_conversation_runner: FunctionalConversationRunner | None = None
        self._compaction_locks: dict[tuple[str, str], asyncio.Lock] = {}
        self._memory_delivery = ProjectConversationMemoryDeliveryService(
            conversation_service,
            memory_repository,
            adaptation_rules_repository or get_provider_adaptation_rules_repository(),
        )
        _ = chat_service

    def set_functional_conversation_runner(
        self,
        runner: FunctionalConversationRunner,
    ) -> None:
        self._functional_conversation_runner = runner

    async def is_blocking_enabled(self) -> bool:
        profile = await asyncio.to_thread(
            self._functional_model_settings_service.get_profile_settings,
            _MEMORY_PROFILE_KEY,
        )
        settings = profile.settings if profile is not None else {}
        return bool_setting(
            settings,
            "blockingEnabled",
            default_value=False,
        )

    async def compact_context_if_enabled(
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
        lock = self._compaction_locks.setdefault(
            (project_id, session_id),
            asyncio.Lock(),
        )
        async with lock:
            await self._compact_context_once(
                project_id,
                session_id,
                blocking=blocking,
                session_snapshot=session_snapshot,
                run_snapshot=run_snapshot,
            )

    async def compact_request_if_enabled(
        self,
        project_id: str,
        session_id: str,
        *,
        blocking: bool | None = None,
        model_request: ChatCompletionRequest,
        session_snapshot: ProjectConversationSession | None = None,
    ) -> None:
        await self.compact_context_if_enabled(
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

    def submit_compaction_result(
        self,
        project_id: str,
        function_session_id: str,
        result: object,
    ) -> dict[str, Any]:
        if not isinstance(result, dict):
            raise ConflictError("记忆压缩结果必须是 JSON 对象。")
        try:
            normalized = parse_compaction_result(
                json.dumps(result, ensure_ascii=False)
            )
        except (TypeError, ValueError) as exc:
            raise ConflictError(f"记忆压缩结果格式错误：{exc}") from exc
        return self._compaction_repository.submit_result(
            project_id,
            function_session_id,
            result=normalized,
            token_measurements=_function_task_token_measurements(
                self._conversation_service.list_messages(
                    project_id,
                    function_session_id,
                ),
                self._token_estimation_settings_service.get_settings(),
            ),
        )

    def handle_compaction_tool_call(
        self,
        project_id: str,
        session_id: str,
        result: object,
    ) -> dict[str, Any]:
        if self._compaction_repository.is_memory_compaction_function_session(
            project_id,
            session_id,
        ):
            return {
                "action": "submitted",
                "task": self.submit_compaction_result(
                    project_id,
                    session_id,
                    result,
                ),
            }

        session = self._conversation_service.get_session(
            project_id,
            session_id,
        )
        if session is None:
            raise ConflictError("当前会话不存在。")
        if not session.settings.memory_compression_enabled:
            return {
                "action": "disabled",
                "protected_token_reserve": (
                    session.settings.memory_raw_context_token_reserve
                ),
            }

        messages = self._conversation_service.list_messages(
            project_id,
            session_id,
        )
        request = ChatCompletionRequest(
            provider_id=session.provider_id or "",
            model_id=session.model_id or "",
            project_id=project_id,
            session_id=session_id,
            messages=build_conversation_request_messages(
                messages,
                None,
                session.settings,
            ),
        )
        records = self._memory_repository.list_compressions(
            project_id,
            session_id,
        )
        token_estimation_settings = (
            self._token_estimation_settings_service.get_settings()
        )
        plan = build_manual_conversation_compaction_plan(
            ConversationRunSnapshot(
                model_request=request,
                assistant_response=ChatMessage(
                    role=ChatMessageRole.ASSISTANT,
                    content="",
                ),
                context_tokens=None,
                context_tokens_estimated=False,
            ),
            records,
            target_token_count=max(
                1,
                session.settings.memory_context_token_trigger_threshold,
            ),
            protected_token_reserve=max(
                0,
                session.settings.memory_raw_context_token_reserve,
            ),
            token_estimation_settings=token_estimation_settings,
        )
        if plan is None:
            return {
                "action": "not_needed",
                "protected_token_reserve": (
                    session.settings.memory_raw_context_token_reserve
                ),
            }

        request_record = self._compaction_repository.request_manual_compaction(
            project_id,
            session_id,
            newly_covered_token_count=plan.newly_covered_token_count,
            protected_tail_token_count=plan.protected_tail_token_count,
        )
        return {
            "action": "scheduled",
            "request": request_record,
        }

    def build_request_with_compressed_context(
        self,
        request: ChatCompletionRequest,
    ) -> ChatCompletionRequest:
        if not request.project_id or not request.session_id:
            return request
        session = self._conversation_service.get_session(
            request.project_id,
            request.session_id,
        )
        if session is None or not session.settings.memory_compression_enabled:
            return request
        result = build_compressed_context_messages(
            messages=request.messages,
            compression_records=self._memory_repository.list_compressions(
                request.project_id,
                request.session_id,
            ),
        )
        if result is None:
            return request
        return replace(request, messages=result.messages)

    def prepare_long_term_memory_delivery(
        self,
        project_id: str,
        session_id: str,
        user_message_id: str,
        *,
        provider_id: str,
        model_id: str,
    ) -> None:
        self._memory_delivery.prepare(
            project_id,
            session_id,
            user_message_id,
            provider_id=provider_id,
            model_id=model_id,
        )

    def inject_long_term_memory_context(
        self,
        request: ChatCompletionRequest,
        *,
        include_pending_changes: bool = False,
    ) -> ChatCompletionRequest:
        return self._memory_delivery.inject(
            request,
            include_pending_changes=include_pending_changes,
        )

    async def _compact_context_once(
        self,
        project_id: str,
        session_id: str,
        *,
        blocking: bool | None,
        session_snapshot: ProjectConversationSession | None,
        run_snapshot: ConversationRunSnapshot,
    ) -> None:
        session = await asyncio.to_thread(
            self._conversation_service.get_session,
            project_id,
            session_id,
        )
        if session is None or not session.settings.memory_compression_enabled:
            return
        if await asyncio.to_thread(
            self._is_active_compaction_function_session,
            project_id,
            session_id,
        ):
            return

        records = await asyncio.to_thread(
            self._memory_repository.list_compressions,
            project_id,
            session_id,
        )
        manual_request = await asyncio.to_thread(
            self._compaction_repository.read_manual_compaction_request,
            project_id,
            session_id,
        )
        active_record = latest_completed_compaction(records)
        if (
            active_record is not None
            and not _request_uses_compaction(
                run_snapshot.model_request,
                active_record,
            )
            and not _compaction_record_needs_protocol_repair(
                run_snapshot.model_request,
                active_record,
            )
        ):
            return
        target_tokens = max(
            1,
            session.settings.memory_context_token_trigger_threshold,
        )
        protected_tokens = max(
            0,
            session.settings.memory_raw_context_token_reserve,
        )
        token_estimation_settings = await asyncio.to_thread(
            self._token_estimation_settings_service.get_settings
        )
        plan_builder = (
            build_manual_conversation_compaction_plan
            if manual_request is not None
            else build_conversation_compaction_plan
        )
        plan = plan_builder(
            run_snapshot,
            records,
            target_token_count=target_tokens,
            protected_token_reserve=protected_tokens,
            token_estimation_settings=token_estimation_settings,
        )
        if plan is None:
            await self._clear_manual_compaction_request(
                project_id,
                session_id,
                manual_request,
            )
            return

        profile = await asyncio.to_thread(
            self._functional_model_settings_service.get_profile_settings,
            _MEMORY_PROFILE_KEY,
        )
        settings = profile.settings if profile is not None else {}
        is_blocking = (
            bool_setting(settings, "blockingEnabled", default_value=False)
            if blocking is None
            else blocking
        )
        prompt = string_setting(settings, "prompt")
        retry_count = int_setting(
            settings,
            "failureRetryCount",
            default_value=DEFAULT_COMPACTION_FAILURE_RETRY_COUNT,
            minimum=0,
            maximum=MAX_COMPACTION_FAILURE_RETRY_COUNT,
        )
        task_prompt = prompt
        target = resolve_functional_conversation_model_target(
            settings,
            source_session=session,
            run_snapshot=run_snapshot,
            task_prompt=task_prompt,
        )
        provider_id = target.provider_id if target is not None else None
        model_id = target.model_id if target is not None else None
        mode = target.mode if target is not None else (
            "dedicated"
            if settings.get("modelSource") == "dedicated"
            else "session"
        )
        fingerprint = _configuration_fingerprint(
            settings=settings,
            failure_retry_count=retry_count,
            mode=mode,
            provider_id=provider_id,
            model_id=model_id,
            prompt=prompt,
        )
        if _same_configuration_failure(
            records,
            plan.source_message_ids,
            fingerprint,
        ):
            await self._clear_manual_compaction_request(
                project_id,
                session_id,
                manual_request,
            )
            return
        if not prompt or provider_id is None or model_id is None:
            await asyncio.to_thread(
                self._memory_repository.append_compression,
                project_id,
                session_id,
                _configuration_failure_record(
                    project_id=project_id,
                    session_id=session_id,
                    plan=plan,
                    mode=mode,
                    provider_id=provider_id,
                    model_id=model_id,
                    fingerprint=fingerprint,
                    reason="empty_prompt" if not prompt else "missing_model",
                ),
            )
            await self._clear_manual_compaction_request(
                project_id,
                session_id,
                manual_request,
            )
            return

        if target is None:
            await self._clear_manual_compaction_request(
                project_id,
                session_id,
                manual_request,
            )
            return
        trigger_context_tokens, trigger_source = _context_token_measurement(
            run_snapshot,
            token_estimation_settings,
        )
        trigger = {
            "context_token_count": trigger_context_tokens,
            "context_token_source": trigger_source,
            "trigger_type": (
                "manual_tool"
                if manual_request is not None
                else "automatic_threshold"
            ),
            "target_token_count": target_tokens,
            "protected_token_reserve": protected_tokens,
            "newly_covered_token_count": plan.newly_covered_token_count,
            "protected_tail_token_count": plan.protected_tail_token_count,
        }
        first_compression_id: str | None = None
        for attempt_index in range(retry_count + 1):
            if not await self._memory_compression_is_enabled(
                project_id,
                session_id,
            ):
                await self._clear_manual_compaction_request(
                    project_id,
                    session_id,
                    manual_request,
                )
                return
            compression_id = f"cmp_{uuid4().hex[:16]}"
            if first_compression_id is None:
                first_compression_id = compression_id
            creation = None
            try:
                creation = await asyncio.to_thread(
                    self._compaction_repository.create_task,
                    project_id,
                    session_id,
                    compression_id=compression_id,
                    source_boundary_message_id=plan.source_boundary_message_id,
                    snapshot_boundary_message_id=plan.snapshot_boundary_message_id,
                    source_message_ids=plan.source_message_ids,
                    newly_covered_message_ids=plan.newly_covered_message_ids,
                    supersedes_compression_id=(
                        plan.active_record.get("compression_id")
                        if plan.active_record is not None
                        else None
                    ),
                    target_provider_id=provider_id,
                    target_model_id=model_id,
                    target_reasoning_mode=target.reasoning_mode,
                    target_settings=target.session_settings,
                    mode=mode,
                    trigger=trigger,
                    configuration_fingerprint=fingerprint,
                    attempt_index=attempt_index,
                    retry_of=(
                        first_compression_id
                        if attempt_index > 0
                        else None
                    ),
                )
                if attempt_index == 0:
                    await self._insert_compaction_status(
                        project_id,
                        session_id,
                        after_message_id=plan.snapshot_boundary_message_id,
                        content=(
                            "正在执行记忆压缩。"
                            if is_blocking
                            else "正在异步执行记忆压缩。"
                        ),
                    )
                await asyncio.to_thread(
                    self._compaction_repository.mark_task_running,
                    project_id,
                    creation.session.session_id,
                )
                request = ChatCompletionRequest(
                    provider_id=provider_id,
                    model_id=model_id,
                    project_id=project_id,
                    session_id=creation.session.session_id,
                    messages=(
                        ChatMessage(
                            role=ChatMessageRole.USER,
                            content=task_prompt,
                        ),
                    ),
                    generation=target.generation,
                    record_usage=True,
                    usage_message_id=(
                        f"system:memory_compression:{compression_id}"
                    ),
                    usage_feature_key="memory_compression",
                    max_tool_calls=creation.session.settings.max_tool_calls,
                )
                await self._functional_conversation_runner(request)
                task = await asyncio.to_thread(
                    self._compaction_repository.read_task,
                    project_id,
                    creation.session.session_id,
                )
                if task is not None and task.get("status") == "completed":
                    await self._append_compaction_status(
                        project_id,
                        session_id,
                        content=(
                            "已完成记忆压缩。"
                            if is_blocking
                            else "已完成异步记忆压缩。"
                        ),
                        status="done",
                    )
                    await self._clear_manual_compaction_request(
                        project_id,
                        session_id,
                        manual_request,
                    )
                    return
                raise MissingCompactionSubmissionError(
                    "压缩会话结束时没有提交压缩结果。"
                )
            except asyncio.CancelledError:
                if creation is not None:
                    await asyncio.to_thread(
                        self._compaction_repository.mark_task_failed,
                        project_id,
                        creation.session.session_id,
                        stage="cancelled",
                        reason="CancelledError",
                        message="记忆压缩任务已取消。",
                    )
                    await self._append_compaction_status(
                        project_id,
                        session_id,
                        content=(
                            "记忆压缩已取消。"
                            if is_blocking
                            else "异步记忆压缩已取消。"
                        ),
                        status="error",
                    )
                raise
            except ConflictError as exc:
                if creation is None:
                    return
                await asyncio.to_thread(
                    self._compaction_repository.mark_task_failed,
                    project_id,
                    creation.session.session_id,
                    stage="stale_result",
                    reason=type(exc).__name__,
                    message=str(exc),
                )
                await self._append_compaction_status(
                    project_id,
                    session_id,
                    content=(
                        "记忆压缩失败。"
                        if is_blocking
                        else "异步记忆压缩失败。"
                    ),
                    status="error",
                )
                await self._clear_manual_compaction_request(
                    project_id,
                    session_id,
                    manual_request,
                )
                return
            except Exception as exc:
                if creation is not None:
                    await asyncio.to_thread(
                        self._compaction_repository.mark_task_failed,
                        project_id,
                        creation.session.session_id,
                        stage="conversation_run",
                        reason=type(exc).__name__,
                        message=str(exc),
                    )
                allowed_retries = (
                    min(retry_count, 1)
                    if isinstance(exc, MissingCompactionSubmissionError)
                    else retry_count
                )
                if (
                    isinstance(exc, FunctionalConversationRunError)
                    and exc.code
                    and exc.code not in TRANSIENT_FUNCTION_ERROR_CODES
                ):
                    await self._append_compaction_status(
                        project_id,
                        session_id,
                        content=(
                            "记忆压缩失败。"
                            if is_blocking
                            else "异步记忆压缩失败。"
                        ),
                        status="error",
                    )
                    await self._clear_manual_compaction_request(
                        project_id,
                        session_id,
                        manual_request,
                    )
                    return
                if attempt_index >= allowed_retries:
                    await self._append_compaction_status(
                        project_id,
                        session_id,
                        content=(
                            "记忆压缩失败。"
                            if is_blocking
                            else "异步记忆压缩失败。"
                        ),
                        status="error",
                    )
                    await self._clear_manual_compaction_request(
                        project_id,
                        session_id,
                        manual_request,
                    )
                    return
                await self._append_compaction_status(
                    project_id,
                    session_id,
                    content=(
                        "记忆压缩失败，正在重试。"
                        if is_blocking
                        else "异步记忆压缩失败，正在重试。"
                    ),
                    status="running",
                )
                await asyncio.sleep(min(2 ** attempt_index, 4))

    async def _memory_compression_is_enabled(
        self,
        project_id: str,
        session_id: str,
    ) -> bool:
        session = await asyncio.to_thread(
            self._conversation_service.get_session,
            project_id,
            session_id,
        )
        return bool(
            session is not None
            and session.settings.memory_compression_enabled
        )

    async def _insert_compaction_status(
        self,
        project_id: str,
        session_id: str,
        *,
        after_message_id: str,
        content: str,
    ) -> None:
        try:
            await asyncio.to_thread(
                self._conversation_service.insert_system_message_after,
                project_id,
                session_id,
                after_message_id=after_message_id,
                content=content,
                name=_COMPACTION_STATUS_MESSAGE_NAME,
                status="running",
            )
        except (AppError, OSError, ValueError):
            return

    async def _append_compaction_status(
        self,
        project_id: str,
        session_id: str,
        *,
        content: str,
        status: str,
    ) -> None:
        try:
            await asyncio.to_thread(
                self._conversation_service.append_message,
                project_id,
                session_id,
                role="system",
                content=content,
                name=_COMPACTION_STATUS_MESSAGE_NAME,
                status=status,
                sync_session_model=False,
            )
        except (AppError, OSError, ValueError):
            return

    async def _clear_manual_compaction_request(
        self,
        project_id: str,
        session_id: str,
        request: dict[str, Any] | None,
    ) -> None:
        if request is None:
            return
        request_id = request.get("request_id")
        if not isinstance(request_id, str) or not request_id:
            return
        await asyncio.to_thread(
            self._compaction_repository.clear_manual_compaction_request,
            project_id,
            session_id,
            request_id=request_id,
        )

    def _is_active_compaction_function_session(
        self,
        project_id: str,
        session_id: str,
    ) -> bool:
        try:
            task = self._compaction_repository.read_task(
                project_id,
                session_id,
            )
        except (AppError, OSError, ValueError):
            return False
        return bool(
            task is not None
            and task.get("status") in {"pending", "running"}
        )


def _context_token_measurement(
    run_snapshot: ConversationRunSnapshot,
    token_estimation_settings: TokenEstimationSettings,
) -> tuple[int, str]:
    return context_token_measurement(
        run_snapshot,
        token_estimation_settings,
    )


def _function_task_token_measurements(
    messages,
    token_estimation_settings: TokenEstimationSettings,
) -> tuple[int, str, int, str]:
    for message in reversed(messages):
        if message.role != "assistant":
            continue
        usage = message.usage if isinstance(message.usage, dict) else {}
        estimated = {
            item
            for item in usage.get("estimated_fields", [])
            if isinstance(item, str)
        }
        prompt_tokens = usage.get("prompt_tokens")
        completion_tokens = usage.get("completion_tokens")
        if isinstance(prompt_tokens, int) and isinstance(completion_tokens, int):
            return (
                max(0, prompt_tokens),
                "local_estimate" if "prompt_tokens" in estimated else "provider_reported",
                max(0, completion_tokens),
                "local_estimate" if "completion_tokens" in estimated else "provider_reported",
            )
        if message.context_tokens is not None:
            completion_estimate = estimate_token_count(
                "\n".join(
                    (
                        message.content,
                        message.thinking_content,
                        *(tool_call.arguments for tool_call in message.tool_calls),
                    )
                ),
                token_estimation_settings,
            )
            return (
                max(0, message.context_tokens),
                (
                    "local_estimate"
                    if message.context_tokens_estimated
                    else "provider_reported"
                ),
                max(1, completion_estimate),
                "local_estimate",
            )
    return 0, "unavailable", 0, "unavailable"


def _configuration_failure_record(
    *,
    project_id: str,
    session_id: str,
    plan,
    mode: str,
    provider_id: str | None,
    model_id: str | None,
    fingerprint: str,
    reason: str,
) -> dict[str, Any]:
    now = _utc_now()
    return {
        "compression_id": f"cmp_{uuid4().hex[:16]}",
        "status": "failed",
        "project_id": project_id,
        "session_id": session_id,
        "source_type": COMPACTION_SOURCE_TYPE,
        "source_message_ids": list(plan.source_message_ids),
        "newly_covered_message_ids": list(plan.newly_covered_message_ids),
        "source_message_count": len(plan.source_message_ids),
        "supersedes_compression_id": (
            plan.active_record.get("compression_id")
            if plan.active_record is not None
            else None
        ),
        "mode": mode,
        "provider_id": provider_id,
        "model_id": model_id,
        "configuration_fingerprint": fingerprint,
        "created_at": now,
        "completed_at": now,
        "failure": {
            "stage": "configuration",
            "reason": reason,
            "message": (
                "记忆压缩提示词为空。"
                if reason == "empty_prompt"
                else "记忆压缩模型未配置。"
            ),
        },
    }


def _configuration_fingerprint(
    *,
    settings: dict[str, Any],
    failure_retry_count: int,
    mode: str,
    provider_id: str | None,
    model_id: str | None,
    prompt: str,
) -> str:
    payload = {
        "generation": settings.get("generation"),
        "failure_retry_count": failure_retry_count,
        "mode": mode,
        "model_id": model_id,
        "prompt": prompt,
        "provider_id": provider_id,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _same_configuration_failure(
    records: list[dict[str, Any]],
    source_message_ids: tuple[str, ...],
    fingerprint: str,
) -> bool:
    expected = list(source_message_ids)
    for record in reversed(records):
        if record.get("source_type") != COMPACTION_SOURCE_TYPE:
            continue
        if record.get("status") == "completed":
            return False
        failure = record.get("failure")
        if (
            record.get("status") == "failed"
            and record.get("source_message_ids") == expected
            and isinstance(failure, dict)
            and failure.get("stage") == "configuration"
        ):
            return record.get("configuration_fingerprint") == fingerprint
    return False


def _request_uses_compaction(
    request: ChatCompletionRequest,
    record: dict[str, Any],
) -> bool:
    compression_id = record.get("compression_id")
    if not isinstance(compression_id, str) or not compression_id:
        return False
    return any(
        isinstance(metadata, dict)
        and metadata.get("compression_id") == compression_id
        for message in request.messages
        for metadata in [message.preview_metadata.get("memory_compression")]
    )


def _compaction_record_needs_protocol_repair(
    request: ChatCompletionRequest,
    record: dict[str, Any],
) -> bool:
    source_ids = compaction_source_message_ids(record)
    return bool(
        source_ids
        and protocol_safe_message_ids(request.messages, source_ids) != source_ids
    )


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


@lru_cache
def get_project_conversation_memory_service() -> ProjectConversationMemoryService:
    return ProjectConversationMemoryService(
        get_project_conversation_service(),
        get_project_conversation_memory_repository(),
        get_llm_functional_model_settings_service(),
        compaction_repository=get_project_conversation_compaction_repository(),
        token_estimation_settings_service=get_token_estimation_settings_service(),
    )
