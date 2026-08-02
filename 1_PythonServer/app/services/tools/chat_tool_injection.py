from __future__ import annotations

from dataclasses import replace
from functools import lru_cache

from app.domain.llm.chat import (
    ChatCompletionRequest,
    ChatMessage,
    ChatMessageRole,
    ChatToolDefinition,
)
from app.domain.tools import ToolSummary
from app.services.tools.catalog import ToolCatalogService, get_tool_catalog_service
from app.services.tools.dynamic_tool_contract import (
    DYNAMIC_TOOL_INFRASTRUCTURE_NAMES,
)
from app.services.tools.dynamic_tool_prompt import dynamic_tool_directory_intro_lines
from app.services.tools.tool_metadata import normalize_tool_name


class ChatToolInjectionService:
    """Build chat tool definitions from enabled Tiance metadata."""

    def __init__(self, catalog_service: ToolCatalogService) -> None:
        self._catalog_service = catalog_service

    def inject_request_tools(
        self,
        request: ChatCompletionRequest,
        *,
        enabled_tool_names: tuple[str, ...] | None,
    ) -> ChatCompletionRequest:
        summaries = self._list_allowed_summaries(enabled_tool_names=enabled_tool_names)
        injected_tools = self._build_chat_tools_from_summaries(summaries)
        dynamic_directory = _dynamic_tool_directory_prompt(summaries)
        if not injected_tools and not dynamic_directory:
            return request
        messages = request.messages
        if dynamic_directory:
            messages = _insert_system_message(messages, dynamic_directory)
        return replace(
            request,
            messages=messages,
            tools=_merge_tool_definitions(request.tools, injected_tools),
        )

    def build_chat_tools(
        self,
        *,
        enabled_tool_names: tuple[str, ...] | None,
    ) -> tuple[ChatToolDefinition, ...]:
        summaries = self._list_allowed_summaries(enabled_tool_names=enabled_tool_names)
        return self._build_chat_tools_from_summaries(summaries)

    def build_dynamic_tool_directory(
        self,
        *,
        enabled_tool_names: tuple[str, ...] | None,
    ) -> str:
        summaries = self._list_allowed_summaries(enabled_tool_names=enabled_tool_names)
        return _dynamic_tool_directory_prompt(summaries)

    def _list_allowed_summaries(
        self,
        *,
        enabled_tool_names: tuple[str, ...] | None,
    ) -> tuple[ToolSummary, ...]:
        allowed_tool_names = _normalize_allowed_tool_names(enabled_tool_names)
        if allowed_tool_names is not None and not allowed_tool_names:
            return ()

        catalog_summaries = self._catalog_service.list_tool_summaries()
        if allowed_tool_names is None:
            return tuple(catalog_summaries)

        selected_names = set(allowed_tool_names)
        if any(
            summary.dynamic and summary.name in selected_names
            for summary in catalog_summaries
        ):
            selected_names.update(DYNAMIC_TOOL_INFRASTRUCTURE_NAMES)
        return tuple(
            summary
            for summary in catalog_summaries
            if summary.name in selected_names
        )

    def _build_chat_tools_from_summaries(
        self,
        summaries: tuple[ToolSummary, ...],
    ) -> tuple[ChatToolDefinition, ...]:
        definitions: list[ChatToolDefinition] = []
        for summary in summaries:
            if summary.dynamic:
                continue
            parameter_detail = self._catalog_service.get_tool_parameters(summary.name)
            definitions.append(
                ChatToolDefinition(
                    name=summary.name,
                    description=summary.description,
                    parameters=parameter_detail.input_schema,
                )
            )
        return tuple(definitions)


def _normalize_allowed_tool_names(
    enabled_tool_names: tuple[str, ...] | None,
) -> set[str] | None:
    if enabled_tool_names is None:
        return None

    allowed_tool_names: set[str] = set()
    for tool_name in enabled_tool_names:
        allowed_tool_names.add(normalize_tool_name(tool_name))
    return allowed_tool_names


def _dynamic_tool_directory_prompt(summaries: tuple[ToolSummary, ...]) -> str:
    available_names = {summary.name for summary in summaries}
    if not DYNAMIC_TOOL_INFRASTRUCTURE_NAMES.issubset(available_names):
        return ""

    dynamic_summaries = tuple(summary for summary in summaries if summary.dynamic)
    if not dynamic_summaries:
        return ""

    lines: list[str] = dynamic_tool_directory_intro_lines()
    for summary in dynamic_summaries:
        lines.extend(
            [
                "",
                f"工具：{summary.name}",
                f"显示名称：{summary.display_name}",
                f"说明：{summary.description}",
                f"参数名：{', '.join(summary.parameter_names) if summary.parameter_names else '无'}",
            ]
        )
        if summary.example_titles:
            lines.append("应用示例：")
            for index, title in enumerate(summary.example_titles, start=1):
                lines.append(f"{index}. {title}")
    return "\n".join(lines)


def _insert_system_message(
    messages: tuple[ChatMessage, ...],
    content: str,
) -> tuple[ChatMessage, ...]:
    system_message = ChatMessage(role=ChatMessageRole.SYSTEM, content=content)
    insert_at = 0
    while insert_at < len(messages) and messages[insert_at].role == ChatMessageRole.SYSTEM:
        insert_at += 1
    return (
        *messages[:insert_at],
        system_message,
        *messages[insert_at:],
    )


def _merge_tool_definitions(
    existing_tools: tuple[ChatToolDefinition, ...],
    injected_tools: tuple[ChatToolDefinition, ...],
) -> tuple[ChatToolDefinition, ...]:
    merged_tools = list(existing_tools)
    existing_names = {tool.name for tool in existing_tools}
    for tool in injected_tools:
        if tool.name in existing_names:
            continue
        merged_tools.append(tool)
        existing_names.add(tool.name)
    return tuple(merged_tools)


@lru_cache
def get_chat_tool_injection_service() -> ChatToolInjectionService:
    return ChatToolInjectionService(get_tool_catalog_service())
