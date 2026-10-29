from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ToolCallRecordListItem:
    record_id: str
    tool_project_id: str
    tool_name: str
    call_id: str
    source_project_id: str | None
    source_project_name: str
    session_id: str | None
    session_title: str
    ok: bool
    created_at: str
    elapsed_ms: int | None
    dynamic: bool | None


@dataclass(frozen=True, slots=True)
class ToolCallRecordPage:
    items: tuple[ToolCallRecordListItem, ...]
    count: int
    offset: int
    limit: int
    snapshot: str | None


class ToolCallRecordSnapshotExpired(ValueError):
    """The source log was replaced since the first page was read."""
