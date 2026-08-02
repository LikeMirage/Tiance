from pydantic import BaseModel, Field

from app.domain.tools import (
    ToolCallRecord,
    ToolCallRecordOverview,
    ToolCallRecordSummary,
    ToolCallRecordSummaryItem,
)


class ToolCallRecordResponse(BaseModel):
    record_id: str
    tool_project_id: str
    tool_name: str
    call_id: str
    source_project_id: str | None
    source_project_name: str
    session_id: str | None
    session_title: str
    arguments_text: str
    result_text: str
    ok: bool
    error: str | None
    created_at: str
    elapsed_ms: int | None = None
    dynamic: bool | None = None

    @classmethod
    def from_domain(cls, record: ToolCallRecord) -> "ToolCallRecordResponse":
        return cls(
            record_id=record.record_id,
            tool_project_id=record.tool_project_id,
            tool_name=record.tool_name,
            call_id=record.call_id,
            source_project_id=record.source_project_id,
            source_project_name=record.source_project_name,
            session_id=record.session_id,
            session_title=record.session_title,
            arguments_text=record.arguments_text,
            result_text=record.result_text,
            ok=record.ok,
            error=record.error,
            created_at=record.created_at,
            elapsed_ms=record.elapsed_ms,
            dynamic=record.dynamic,
        )


class ToolCallRecordListResponse(BaseModel):
    category_id: str
    project_id: str
    count: int
    items: list[ToolCallRecordResponse] = Field(default_factory=list)


class ToolCallRecordTopToolResponse(BaseModel):
    tool_name: str
    display_name: str
    call_count: int


class ToolCallRecordOverviewResponse(BaseModel):
    total_call_count: int
    top_tools: list[ToolCallRecordTopToolResponse] = Field(default_factory=list)

    @classmethod
    def from_domain(
        cls,
        overview: ToolCallRecordOverview,
    ) -> "ToolCallRecordOverviewResponse":
        return cls(
            total_call_count=overview.total_call_count,
            top_tools=[
                ToolCallRecordTopToolResponse(
                    tool_name=item.tool_name,
                    display_name=item.display_name,
                    call_count=item.call_count,
                )
                for item in overview.top_tools
            ],
        )


class ToolCallRecordSummaryItemResponse(BaseModel):
    project_id: str
    category_id: str
    project_name: str
    tool_name: str
    display_name: str
    enabled: bool | None
    dynamic: bool | None
    parallel: bool | None
    call_count: int
    success_count: int
    failure_count: int
    last_called_at: str | None
    average_elapsed_ms: int | None
    dynamic_count: int
    full_load_count: int
    full_injection_char_count: int
    dynamic_injection_char_count: int
    global_call_share: float

    @classmethod
    def from_domain(
        cls,
        item: ToolCallRecordSummaryItem,
    ) -> "ToolCallRecordSummaryItemResponse":
        return cls(
            project_id=item.project_id,
            category_id=item.category_id,
            project_name=item.project_name,
            tool_name=item.tool_name,
            display_name=item.display_name,
            enabled=item.enabled,
            dynamic=item.dynamic,
            parallel=item.parallel,
            call_count=item.call_count,
            success_count=item.success_count,
            failure_count=item.failure_count,
            last_called_at=item.last_called_at,
            average_elapsed_ms=item.average_elapsed_ms,
            dynamic_count=item.dynamic_count,
            full_load_count=item.full_load_count,
            full_injection_char_count=item.full_injection_char_count,
            dynamic_injection_char_count=item.dynamic_injection_char_count,
            global_call_share=item.global_call_share,
        )


class ToolCallRecordSummaryResponse(BaseModel):
    category_id: str
    total_call_count: int
    category_call_count: int
    items: list[ToolCallRecordSummaryItemResponse] = Field(default_factory=list)

    @classmethod
    def from_domain(
        cls,
        summary: ToolCallRecordSummary,
    ) -> "ToolCallRecordSummaryResponse":
        return cls(
            category_id=summary.category_id,
            total_call_count=summary.total_call_count,
            category_call_count=summary.category_call_count,
            items=[
                ToolCallRecordSummaryItemResponse.from_domain(item)
                for item in summary.items
            ],
        )
