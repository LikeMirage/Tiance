from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from json import dumps
from pathlib import Path
from typing import Any

from app.core.errors import BadRequestError
from app.core.config import get_settings
from app.domain.llm.chat import ChatToolCall, ChatToolResult
from app.domain.tools import ToolMetadataSnapshot, ToolRegistryEntry
from app.services.tools.tool_execution_arguments import (
    parse_tool_arguments,
    validate_tool_arguments,
)
from app.services.tools.tool_execution_results import (
    TOOL_ARGUMENT_VALIDATION_FAILED,
    completed_process_result,
    dynamic_tool_execution_result,
    failure_result,
)
from app.services.tools.dynamic_tool_contract import DYNAMIC_TOOL_EXECUTOR_NAME
from app.services.tools.host_capability_access import (
    HostCapabilityAccessService,
    get_host_capability_access_service,
)
from app.services.tools.tool_execution_runtime import (
    CommandRunner,
    build_python_command,
    build_tool_env,
    build_tool_python_paths,
    default_python_executable,
    resolve_backend_api_base_url,
    resolve_entry_path,
    resolve_workspace_root,
    run_command,
    runtime_timeout_seconds,
    ToolExecutionCancellation,
)
from app.services.tools.tool_metadata import is_enabled, normalize_tool_name
from app.services.tools.tool_registry import ToolRegistryService, get_tool_registry_service


@dataclass(frozen=True, slots=True)
class ToolExecutionContext:
    workspace_root: str | None = None
    project_id: str | None = None
    session_id: str | None = None
    enabled_tool_names: tuple[str, ...] | None = None
    provider_id: str | None = None
    model_id: str | None = None
    input_modalities: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PreparedClientToolExecution:
    tool_project_id: str
    dynamic: bool
    timeout_seconds: int


@dataclass(frozen=True, slots=True)
class PreparedDynamicToolExecution:
    target_call: ChatToolCall
    executor_project_id: str


@dataclass(frozen=True, slots=True)
class _ResolvedToolCall:
    entry: ToolRegistryEntry
    metadata: ToolMetadataSnapshot
    arguments: dict[str, Any]


class ToolExecutionService:
    def __init__(
        self,
        registry_service: ToolRegistryService,
        *,
        python_executable: Path | None = None,
        command_runner: CommandRunner | None = None,
        host_capability_access: HostCapabilityAccessService | None = None,
    ) -> None:
        settings = get_settings()
        self._registry_service = registry_service
        self._python_executable = python_executable or default_python_executable(settings.embedded_python_file)
        self._command_runner = command_runner or run_command
        self._host_capability_access = (
            host_capability_access or get_host_capability_access_service()
        )
        self._api_base_url = resolve_backend_api_base_url(settings.api_prefix)
        self._tools_root = settings.tools_data_path.resolve(strict=False)

    def is_parallel_tool(self, tool_name: str) -> bool:
        normalized_tool_name = _normalize_tool_name_or_empty(tool_name)
        if not normalized_tool_name:
            return False
        entry = self._registry_service.get_enabled_entry(normalized_tool_name)
        return bool(entry and entry.parallel)

    def is_client_tool(self, tool_name: str) -> bool:
        normalized_tool_name = _normalize_tool_name_or_empty(tool_name)
        if not normalized_tool_name:
            return False
        entry = self._registry_service.get_enabled_entry(normalized_tool_name)
        if entry is None:
            return False
        metadata = self._registry_service.get_enabled_metadata(normalized_tool_name)
        if metadata is None:
            return False
        runtime = metadata.manifest.get("runtime")
        if not isinstance(runtime, dict):
            return False
        return str(runtime.get("type") or "").strip().lower() == "client"

    def prepare_dynamic_tool_execution(
        self,
        executor_call: ChatToolCall,
        *,
        enabled_tool_names: tuple[str, ...] | None = None,
    ) -> PreparedDynamicToolExecution | ChatToolResult:
        executor = self._resolve_tool_call(executor_call)
        if isinstance(executor, ChatToolResult):
            return executor
        if executor.metadata.name != DYNAMIC_TOOL_EXECUTOR_NAME:
            return failure_result(executor_call, "这不是动态工具执行调用。")
        return self._prepare_dynamic_target(
            executor_call,
            executor,
            enabled_tool_names=enabled_tool_names,
        )

    def wrap_dynamic_tool_execution(
        self,
        executor_call: ChatToolCall,
        prepared: PreparedDynamicToolExecution,
        target_result: ChatToolResult,
    ) -> ChatToolResult:
        return dynamic_tool_execution_result(
            executor_call,
            target_result,
            executor_project_id=prepared.executor_project_id,
        )

    def prepare_client_tool(
        self,
        tool_call: ChatToolCall,
    ) -> PreparedClientToolExecution | ChatToolResult | None:
        resolved = self._resolve_tool_call(tool_call)
        if isinstance(resolved, ChatToolResult):
            return resolved

        runtime = resolved.metadata.manifest.get("runtime")
        if not isinstance(runtime, dict):
            return None
        if str(runtime.get("type") or "").strip().lower() != "client":
            return None
        return PreparedClientToolExecution(
            tool_project_id=resolved.entry.project_id,
            dynamic=resolved.entry.dynamic,
            timeout_seconds=runtime_timeout_seconds(runtime.get("timeout_seconds")),
        )

    def execute(
        self,
        tool_call: ChatToolCall,
        *,
        context: ToolExecutionContext,
    ) -> ChatToolResult:
        return self._execute(tool_call, context=context, cancellation=None)

    def execute_cancellable(
        self,
        tool_call: ChatToolCall,
        *,
        context: ToolExecutionContext,
        cancellation: ToolExecutionCancellation,
    ) -> ChatToolResult:
        return self._execute(tool_call, context=context, cancellation=cancellation)

    def _execute(
        self,
        tool_call: ChatToolCall,
        *,
        context: ToolExecutionContext,
        cancellation: ToolExecutionCancellation | None,
    ) -> ChatToolResult:
        resolved = self._resolve_tool_call(tool_call)
        if isinstance(resolved, ChatToolResult):
            return resolved

        if resolved.metadata.name == DYNAMIC_TOOL_EXECUTOR_NAME:
            return self._execute_dynamic_tool(
                tool_call,
                resolved,
                context=context,
                cancellation=cancellation,
            )

        return self._execute_resolved_tool(
            tool_call,
            resolved,
            context=context,
            cancellation=cancellation,
        )

    def _execute_dynamic_tool(
        self,
        executor_call: ChatToolCall,
        executor: _ResolvedToolCall,
        *,
        context: ToolExecutionContext,
        cancellation: ToolExecutionCancellation | None,
    ) -> ChatToolResult:
        prepared = self._prepare_dynamic_target(
            executor_call,
            executor,
            enabled_tool_names=context.enabled_tool_names,
        )
        if isinstance(prepared, ChatToolResult):
            return prepared

        target = self._resolve_tool_call(prepared.target_call)
        if isinstance(target, ChatToolResult):
            return self.wrap_dynamic_tool_execution(
                executor_call,
                prepared,
                target,
            )

        target_result = self._execute_resolved_tool(
            prepared.target_call,
            target,
            context=context,
            cancellation=cancellation,
        )
        return self.wrap_dynamic_tool_execution(
            executor_call,
            prepared,
            target_result,
        )

    def _prepare_dynamic_target(
        self,
        executor_call: ChatToolCall,
        executor: _ResolvedToolCall,
        *,
        enabled_tool_names: tuple[str, ...] | None,
    ) -> PreparedDynamicToolExecution | ChatToolResult:
        target_name = _normalize_tool_name_or_empty(str(executor.arguments.get("tool_name") or ""))
        target_arguments = executor.arguments.get("arguments")
        if not target_name or not isinstance(target_arguments, dict):
            return failure_result(
                executor_call,
                "动态工具执行参数无效。",
                tool_project_id=executor.entry.project_id,
                dynamic=False,
            )
        target_call = ChatToolCall(
            call_id=executor_call.call_id,
            name=target_name,
            arguments=dumps(target_arguments, ensure_ascii=False, separators=(",", ":")),
        )
        if not _is_session_tool_enabled(target_name, enabled_tool_names):
            return failure_result(
                executor_call,
                "此工具已关闭。",
                tool_project_id=executor.entry.project_id,
                dynamic=False,
            )
        target = self._resolve_tool_call(target_call)
        if isinstance(target, ChatToolResult):
            return dynamic_tool_execution_result(
                executor_call,
                target,
                executor_project_id=executor.entry.project_id,
            )
        if not target.entry.dynamic:
            return failure_result(
                executor_call,
                "execute_dynamic_tool 只能执行动态加载工具。",
                tool_project_id=executor.entry.project_id,
                dynamic=False,
            )
        return PreparedDynamicToolExecution(
            target_call=target_call,
            executor_project_id=executor.entry.project_id,
        )

    def _execute_resolved_tool(
        self,
        tool_call: ChatToolCall,
        resolved: _ResolvedToolCall,
        *,
        context: ToolExecutionContext,
        cancellation: ToolExecutionCancellation | None = None,
    ) -> ChatToolResult:

        runtime = resolved.metadata.manifest.get("runtime")
        if not isinstance(runtime, dict):
            return failure_result(
                tool_call,
                f"工具 '{resolved.metadata.name}' 缺少运行入口。",
                tool_project_id=resolved.entry.project_id,
                dynamic=resolved.entry.dynamic,
            )
        if str(runtime.get("type") or "python").strip().lower() != "python":
            return failure_result(
                tool_call,
                "当前执行层只支持 Python 工具。",
                tool_project_id=resolved.entry.project_id,
                dynamic=resolved.entry.dynamic,
            )

        tool_root = Path(resolved.entry.root_path).resolve()
        entry_path = resolve_entry_path(tool_root, runtime.get("entry"))
        if entry_path is None or not entry_path.is_file():
            return failure_result(
                tool_call,
                "工具入口文件不存在。",
                tool_project_id=resolved.entry.project_id,
                dynamic=resolved.entry.dynamic,
            )

        timeout_seconds = runtime_timeout_seconds(runtime.get("timeout_seconds"))
        workspace_root = resolve_workspace_root(context.workspace_root)
        cwd = workspace_root if workspace_root is not None else tool_root
        python_paths = build_tool_python_paths(
            entry_path=entry_path,
            tool_root=tool_root,
        )
        capability_grant = self._host_capability_access.issue_grant(
            tool_name=resolved.metadata.name,
            tool_call_id=tool_call.call_id,
            provider_id=context.provider_id,
            model_id=context.model_id,
            project_id=context.project_id,
            session_id=context.session_id,
            lifetime_seconds=timeout_seconds,
        )
        try:
            env = build_tool_env(
                python_paths=python_paths,
                workspace_root=workspace_root,
                tools_root=self._tools_root,
                api_base_url=self._api_base_url,
                project_id=context.project_id,
                session_id=context.session_id,
                provider_id=context.provider_id,
                model_id=context.model_id,
                input_modalities=context.input_modalities,
                host_capability_token=(
                    capability_grant.token if capability_grant is not None else None
                ),
            )

            command = build_python_command(
                python_executable=self._python_executable,
                entry_path=entry_path,
                python_paths=python_paths,
            )
            if self._command_runner is run_command:
                completed = run_command(
                    command,
                    dumps(resolved.arguments, ensure_ascii=False),
                    cwd,
                    env,
                    timeout_seconds,
                    cancellation=cancellation,
                )
            else:
                completed = self._command_runner(
                    command,
                    dumps(resolved.arguments, ensure_ascii=False),
                    cwd,
                    env,
                    timeout_seconds,
                )
        finally:
            if capability_grant is not None:
                self._host_capability_access.revoke(capability_grant.token)
        return completed_process_result(
            tool_call,
            completed,
            tool_project_id=resolved.entry.project_id,
            dynamic=resolved.entry.dynamic,
        )

    def _resolve_tool_call(
        self,
        tool_call: ChatToolCall,
    ) -> _ResolvedToolCall | ChatToolResult:
        tool_name = _normalize_tool_name_or_empty(tool_call.name)
        if not tool_name:
            return failure_result(tool_call, "工具调用名称无效。")

        entry = self._registry_service.get_enabled_entry(tool_name)
        if entry is None:
            known_entry = self._registry_service.get_entry(tool_name)
            if known_entry is not None and not known_entry.enabled:
                return failure_result(
                    tool_call,
                    "此工具已关闭。",
                    tool_project_id=known_entry.project_id,
                    dynamic=known_entry.dynamic,
                )
            return failure_result(tool_call, f"工具 '{tool_name}' 不存在。")

        try:
            arguments = parse_tool_arguments(tool_call.arguments)
        except ValueError as exc:
            return failure_result(tool_call, str(exc), tool_project_id=entry.project_id, dynamic=entry.dynamic)

        metadata = self._registry_service.get_enabled_metadata(tool_name)
        if metadata is None:
            return failure_result(tool_call, f"工具 '{tool_name}' 不存在。")
        if not is_enabled(metadata.manifest):
            return failure_result(tool_call, "此工具已关闭。", tool_project_id=entry.project_id, dynamic=entry.dynamic)
        schema_errors = validate_tool_arguments(arguments, metadata.input_schema)
        if schema_errors:
            return failure_result(
                tool_call,
                "工具参数校验失败：" + "；".join(schema_errors),
                tool_project_id=entry.project_id,
                dynamic=entry.dynamic,
                error_code=TOOL_ARGUMENT_VALIDATION_FAILED,
            )
        return _ResolvedToolCall(
            entry=entry,
            metadata=metadata,
            arguments=arguments,
        )


def _normalize_tool_name_or_empty(tool_name: str) -> str:
    try:
        return normalize_tool_name(tool_name)
    except BadRequestError:
        return ""


def _is_session_tool_enabled(
    tool_name: str,
    enabled_tool_names: tuple[str, ...] | None,
) -> bool:
    if enabled_tool_names is None:
        return True
    return any(
        _normalize_tool_name_or_empty(enabled_tool_name) == tool_name
        for enabled_tool_name in enabled_tool_names
    )


@lru_cache
def get_tool_execution_service() -> ToolExecutionService:
    return ToolExecutionService(get_tool_registry_service())
