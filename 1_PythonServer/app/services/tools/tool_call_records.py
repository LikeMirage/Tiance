from __future__ import annotations

from collections import Counter
from dataclasses import replace
from functools import lru_cache

from app.domain.llm.chat import ChatToolResult
from app.domain.tools import (
    ToolCallRecord,
    ToolCallRecordDraft,
    ToolCallRecordFolderStats,
    ToolCallRecordOverview,
    ToolCallRecordSummary,
    ToolCallRecordSummaryItem,
    ToolCallRecordTopTool,
    ToolFolder,
    ToolRegistryEntry,
)
from app.repositories.tools import ToolCallRecordRepository, get_tool_call_record_repository
from app.services.project.project_conversations import (
    ProjectConversationService,
    get_project_conversation_service,
)
from app.services.project.projects import ProjectService, get_project_service
from app.services.tools.tool_projects import ToolProjectService, get_tool_project_service
from app.services.tools.tool_registry import ToolRegistryService, get_tool_registry_service


class ToolCallRecordService:
    def __init__(
        self,
        repository: ToolCallRecordRepository,
        *,
        project_service: ProjectService,
        conversation_service: ProjectConversationService,
        tool_project_service: ToolProjectService,
        tool_registry_service: ToolRegistryService,
    ) -> None:
        self._repository = repository
        self._project_service = project_service
        self._conversation_service = conversation_service
        self._tool_projects = tool_project_service
        self._tool_registry_service = tool_registry_service

    def append_result(
        self,
        tool_result: ChatToolResult,
        *,
        project_id: str | None,
        session_id: str | None,
    ) -> ToolCallRecord | None:
        tool_project_id = tool_result.tool_project_id
        if not tool_project_id:
            return None
        tool_project = self._tool_projects.get_tool_project(tool_project_id)
        if tool_project is None:
            return None
        return self._repository.append(
            tool_project.root_path,
            ToolCallRecordDraft(
                tool_project_id=tool_project_id,
                tool_name=tool_result.name,
                call_id=tool_result.call_id,
                source_project_id=project_id,
                session_id=session_id,
                arguments_text=tool_result.arguments,
                result_text=tool_result.content,
                ok=tool_result.ok,
                error=tool_result.error,
                elapsed_ms=tool_result.elapsed_ms,
                dynamic=tool_result.dynamic,
            ),
        )

    def list_project_records(
        self,
        category_id: str,
        project_id: str,
    ) -> tuple[ToolCallRecord, ...]:
        project = self._tool_projects.require_tool_project(category_id, project_id)
        records = self._repository.list_project_records(project.root_path)
        return tuple(self._with_current_names(record) for record in records)

    def list_tool_records(self, tool_name: str) -> tuple[ToolCallRecord, ...]:
        records = tuple(
            record for record in self._all_records() if record.tool_name == tool_name
        )
        return tuple(self._with_current_names(record) for record in records)

    def get_total_call_count(self) -> int:
        return len(self._all_records())

    def summarize_global_records(self) -> ToolCallRecordOverview:
        records = self._all_records()
        counts = Counter(record.tool_name for record in records)
        display_names = {
            entry.tool_name: entry.display_name or entry.tool_name
            for entry in self._tool_registry_service.list_entries(enabled_only=False)
        }
        top_tools = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[
            :_GLOBAL_TOP_TOOL_LIMIT
        ]
        return ToolCallRecordOverview(
            total_call_count=len(records),
            top_tools=tuple(
                ToolCallRecordTopTool(
                    tool_name=tool_name,
                    display_name=display_names.get(tool_name, tool_name),
                    call_count=call_count,
                )
                for tool_name, call_count in top_tools
            ),
        )

    def summarize_category_records(self, category_id: str) -> ToolCallRecordSummary:
        projects = self._tool_projects.list_tool_folders(category_id)
        entries_by_project_id = {
            entry.project_id: entry
            for entry in self._tool_registry_service.list_entries(enabled_only=False)
        }
        all_records = self._all_records()
        records_by_project_id: dict[str, list[ToolCallRecord]] = {}
        for record in all_records:
            records_by_project_id.setdefault(record.tool_project_id, []).append(record)
        category_call_count = sum(
            len(records_by_project_id.get(project.project_id, ())) for project in projects
        )
        return ToolCallRecordSummary(
            category_id=category_id,
            total_call_count=len(all_records),
            category_call_count=category_call_count,
            items=tuple(
                self._build_summary_item(
                    project,
                    _summarize_project_records(
                        project.project_id,
                        records_by_project_id.get(project.project_id, ()),
                    ),
                    total_call_count=len(all_records),
                    registry_entry=entries_by_project_id.get(project.project_id),
                )
                for project in projects
            ),
        )

    def _all_records(self) -> tuple[ToolCallRecord, ...]:
        roots = tuple(
            project.root_path
            for category in self._tool_projects.list_toolsets()
            for project in self._tool_projects.list_tool_folders(category.category_id)
        )
        return self._repository.list_all(roots)

    def _with_current_names(self, record: ToolCallRecord) -> ToolCallRecord:
        return replace(
            record,
            source_project_name=self._current_project_name(record.source_project_id),
            session_title=self._current_session_title(
                record.source_project_id,
                record.session_id,
            ),
        )

    def _current_project_name(self, project_id: str | None) -> str:
        if not project_id:
            return ""
        project = self._project_service.get_project(project_id)
        return project.name if project is not None else ""

    def _current_session_title(self, project_id: str | None, session_id: str | None) -> str:
        if not project_id or not session_id:
            return ""
        session = self._conversation_service.get_session(project_id, session_id)
        return session.title if session is not None else ""

    @staticmethod
    def _build_summary_item(
        project: ToolFolder,
        stats: ToolCallRecordFolderStats,
        *,
        total_call_count: int,
        registry_entry: ToolRegistryEntry | None,
    ) -> ToolCallRecordSummaryItem:
        return ToolCallRecordSummaryItem(
            project_id=project.project_id,
            category_id=project.category_id,
            project_name=project.name,
            tool_name=registry_entry.tool_name if registry_entry is not None else "",
            display_name=(
                registry_entry.display_name if registry_entry is not None else project.name
            ),
            enabled=registry_entry.enabled if registry_entry is not None else None,
            dynamic=registry_entry.dynamic if registry_entry is not None else None,
            parallel=registry_entry.parallel if registry_entry is not None else None,
            call_count=stats.call_count,
            success_count=stats.success_count,
            failure_count=stats.failure_count,
            last_called_at=stats.last_called_at,
            average_elapsed_ms=stats.average_elapsed_ms,
            dynamic_count=stats.dynamic_count,
            full_load_count=stats.full_load_count,
            full_injection_char_count=(
                registry_entry.full_injection_char_count if registry_entry is not None else 0
            ),
            dynamic_injection_char_count=(
                registry_entry.dynamic_injection_char_count
                if registry_entry is not None
                else 0
            ),
            global_call_share=_ratio(stats.call_count, total_call_count),
        )


def _summarize_project_records(
    project_id: str,
    records: list[ToolCallRecord] | tuple[ToolCallRecord, ...],
) -> ToolCallRecordFolderStats:
    elapsed_values = [record.elapsed_ms for record in records if record.elapsed_ms is not None]
    return ToolCallRecordFolderStats(
        tool_project_id=project_id,
        call_count=len(records),
        success_count=sum(1 for record in records if record.ok),
        failure_count=sum(1 for record in records if not record.ok),
        last_called_at=max((record.created_at for record in records), default=None),
        average_elapsed_ms=(
            round(sum(elapsed_values) / len(elapsed_values)) if elapsed_values else None
        ),
        dynamic_count=sum(1 for record in records if record.dynamic is True),
        full_load_count=sum(1 for record in records if record.dynamic is False),
    )


@lru_cache
def get_tool_call_record_service() -> ToolCallRecordService:
    return ToolCallRecordService(
        get_tool_call_record_repository(),
        project_service=get_project_service(),
        conversation_service=get_project_conversation_service(),
        tool_project_service=get_tool_project_service(),
        tool_registry_service=get_tool_registry_service(),
    )


_GLOBAL_TOP_TOOL_LIMIT = 3


def _ratio(value: int, total: int) -> float:
    return value / total if total > 0 else 0.0
