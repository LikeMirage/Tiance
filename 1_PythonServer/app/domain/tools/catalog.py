from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ToolSummary:
    name: str
    display_name: str
    description: str
    keywords: tuple[str, ...]
    category: str
    dynamic: bool
    parameter_names: tuple[str, ...]
    example_titles: tuple[str, ...]
    parallel: bool = False


@dataclass(frozen=True, slots=True)
class ToolMetadataSnapshot:
    name: str
    manifest: dict[str, Any]
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    examples: tuple[tuple[int, dict[str, Any]], ...]


@dataclass(frozen=True, slots=True)
class ToolRegistryEntry:
    project_id: str
    category_id: str
    category_name: str
    tool_name: str
    display_name: str
    description: str
    keywords: tuple[str, ...]
    enabled: bool
    dynamic: bool
    root_path: str
    runtime_entry: str
    parameter_names: tuple[str, ...]
    example_titles: tuple[str, ...]
    indexed_at: str
    updated_at: str
    parallel: bool = False
    full_injection_char_count: int = 0
    dynamic_injection_char_count: int = 0

    def to_summary(self) -> ToolSummary:
        return ToolSummary(
            name=self.tool_name,
            display_name=self.display_name,
            description=self.description,
            keywords=self.keywords,
            category=self.category_name,
            dynamic=self.dynamic,
            parameter_names=self.parameter_names,
            example_titles=self.example_titles,
            parallel=self.parallel,
        )


@dataclass(frozen=True, slots=True)
class ToolParameterDetail:
    name: str
    input_schema: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ToolExampleSummary:
    index: int
    title: str
    inject_content: bool = False


@dataclass(frozen=True, slots=True)
class ToolExampleDetail:
    index: int
    title: str
    content: str
    inject_content: bool = False


@dataclass(frozen=True, slots=True)
class ToolCallRecord:
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


@dataclass(frozen=True, slots=True)
class ToolCallRecordDraft:
    tool_project_id: str
    tool_name: str
    call_id: str
    source_project_id: str | None
    session_id: str | None
    arguments_text: str
    result_text: str
    ok: bool
    error: str | None
    elapsed_ms: int | None = None
    dynamic: bool | None = None


@dataclass(frozen=True, slots=True)
class ToolCallRecordToolStats:
    tool_name: str
    call_count: int


@dataclass(frozen=True, slots=True)
class ToolCallRecordTopTool:
    tool_name: str
    display_name: str
    call_count: int


@dataclass(frozen=True, slots=True)
class ToolCallRecordOverview:
    total_call_count: int
    top_tools: tuple[ToolCallRecordTopTool, ...]


@dataclass(frozen=True, slots=True)
class ToolCallRecordFolderStats:
    tool_project_id: str
    call_count: int
    success_count: int
    failure_count: int
    last_called_at: str | None
    average_elapsed_ms: int | None
    dynamic_count: int
    full_load_count: int


@dataclass(frozen=True, slots=True)
class ToolCallRecordSummaryItem:
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


@dataclass(frozen=True, slots=True)
class ToolCallRecordSummary:
    category_id: str
    total_call_count: int
    category_call_count: int
    items: tuple[ToolCallRecordSummaryItem, ...]
