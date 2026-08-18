from __future__ import annotations

from dataclasses import dataclass
from json import dumps
from math import ceil
from pathlib import Path
from typing import Literal

from app.core.errors import BadRequestError, NotFoundError
from app.repositories.project.conversation_database import (
    count_embedded_artifacts,
    count_events,
    count_journal_events,
    count_message_payloads,
    count_project_events,
    database_path_from_workspace,
    list_embedded_artifacts_range,
    list_events_range,
    list_journal_events_range,
    list_message_payloads_range,
    list_project_events_range,
    read_document,
    read_meta,
    read_session,
    read_session_state_payloads,
    read_sessions,
)
from app.repositories.project.conversation_storage import ProjectWorkspaceDirectoryResolver
from app.repositories.project.project_repository import ProjectRepository


ConversationDataViewName = Literal[
    "index.json",
    "session.json",
    "messages.jsonl",
    "conversation_journal.jsonl",
    "model_exchanges.jsonl",
    "model_http_exchanges.jsonl",
    "compressions.jsonl",
    "injection_preview.json",
    "project_memory.jsonl",
]


@dataclass(frozen=True)
class ConversationDataView:
    content: str
    revision_ms: int
    total_count: int | None = None
    page: int | None = None
    page_size: int | None = None
    total_pages: int | None = None
    has_previous: bool = False
    has_next: bool = False


@dataclass(frozen=True)
class _PageWindow:
    page: int
    page_size: int
    total_count: int
    total_pages: int
    start: int
    end: int

    @property
    def has_previous(self) -> bool:
        return self.page > 1

    @property
    def has_next(self) -> bool:
        return self.page < self.total_pages


class ConversationDataViewRepository:
    """Build read-only, pageable dashboard documents from conversation storage."""

    def __init__(self, project_repository: ProjectRepository) -> None:
        self._projects = project_repository
        self._workspace = ProjectWorkspaceDirectoryResolver()

    def read(
        self,
        project_id: str,
        *,
        name: ConversationDataViewName,
        session_id: str | None,
        page: int | None,
        page_size: int,
    ) -> ConversationDataView:
        project = self._projects.get_project(project_id)
        if project is None:
            raise NotFoundError("项目不存在。")
        workspace_dir = self._workspace.resolve_workspace_dir(
            Path(project.root_path),
            for_write=False,
        )
        conversations_dir = workspace_dir / "conversations"
        revision_ms = _database_mtime(workspace_dir)

        if name == "index.json":
            raw_index = read_meta(conversations_dir, "conversation_index", {})
            index = raw_index if isinstance(raw_index, dict) else {}
            stored_sessions = read_sessions(conversations_dir)
            pinned_ids = {
                str(value)
                for value in index.get("pinned_session_ids", [])
                if isinstance(value, str)
            }
            session_items = sorted(
                stored_sessions.values(),
                key=lambda item: (
                    str(item.get("session_id") or "") in pinned_ids,
                    str(item.get("created_at") or ""),
                    int(item.get("sequence_number") or 0),
                ),
                reverse=True,
            )
            states = read_session_state_payloads(
                conversations_dir,
                set(stored_sessions),
            )
            payload = {
                "active_session_id": index.get("active_session_id"),
                "pinned_session_ids": sorted(pinned_ids & set(stored_sessions)),
                "sessions": session_items,
                "session_states": states,
            }
            window = _page_window(
                total_count=len(session_items),
                page=page,
                page_size=page_size,
                default_to_last=False,
            )
            return _paged_view(
                _json(_slice_index_payload(payload, session_items, window)),
                revision_ms,
                window,
            )

        if name == "project_memory.jsonl":
            total_count = count_project_events(workspace_dir, "project_memory")
            window = _page_window(total_count, page, page_size)
            events = list_project_events_range(
                workspace_dir,
                "project_memory",
                start_ordinal=window.start,
                end_ordinal=window.end,
            )
            return _paged_view(_jsonl(events), revision_ms, window)

        if name == "conversation_journal.jsonl":
            normalized_session_id = (session_id or "").strip() or None
            total_count = count_journal_events(
                workspace_dir,
                session_id=normalized_session_id,
            )
            window = _page_window(total_count, page, page_size)
            events = list_journal_events_range(
                workspace_dir,
                session_id=normalized_session_id,
                offset=window.start,
                limit=window.end - window.start,
            )
            return _paged_view(_jsonl(events), revision_ms, window)

        resolved_session_id = _require_session_id(session_id)
        session = read_session(conversations_dir, resolved_session_id)
        if session is None:
            raise NotFoundError("会话不存在。")
        session_dir = conversations_dir / "sessions" / resolved_session_id
        if name == "session.json":
            return ConversationDataView(_json(session), revision_ms)
        if name == "messages.jsonl":
            total_count = count_message_payloads(session_dir)
            window = _page_window(total_count, page, page_size)
            messages = list_message_payloads_range(
                session_dir,
                start_ordinal=window.start,
                end_ordinal=window.end,
            )
            return _paged_view(_jsonl(messages), revision_ms, window)
        if name in {"compressions.jsonl", "model_exchanges.jsonl"}:
            event_kind = name.removesuffix(".jsonl")
            total_count = count_events(session_dir, event_kind)
            window = _page_window(total_count, page, page_size)
            events = list_events_range(
                session_dir,
                event_kind,
                start_ordinal=window.start,
                end_ordinal=window.end,
            )
            return _paged_view(_jsonl(events), revision_ms, window)
        if name == "model_http_exchanges.jsonl":
            total_count = count_embedded_artifacts(
                workspace_dir,
                session_id=resolved_session_id,
                kind="model_http_exchange",
            )
            window = _page_window(total_count, page, page_size)
            artifacts = list_embedded_artifacts_range(
                workspace_dir,
                session_id=resolved_session_id,
                kind="model_http_exchange",
                offset=window.start,
                limit=window.end - window.start,
            )
            return _paged_view(_jsonl(artifacts), revision_ms, window)
        if name == "injection_preview.json":
            return ConversationDataView(
                _json(read_document(session_dir, "injection_preview") or {}),
                revision_ms,
            )
        raise BadRequestError("不支持的数据视图。")


def _page_window(
    total_count: int,
    page: int | None,
    page_size: int,
    *,
    default_to_last: bool = True,
) -> _PageWindow:
    if page_size < 1 or (page is not None and page < 1):
        raise BadRequestError("页码和每页条数必须大于 0。")
    total_pages = max(1, ceil(total_count / page_size))
    requested_page = total_pages if page is None and default_to_last else page or 1
    resolved_page = min(requested_page, total_pages)
    start = (resolved_page - 1) * page_size
    return _PageWindow(
        page=resolved_page,
        page_size=page_size,
        total_count=total_count,
        total_pages=total_pages,
        start=start,
        end=min(start + page_size, total_count),
    )


def _paged_view(
    content: str,
    revision_ms: int,
    window: _PageWindow,
) -> ConversationDataView:
    return ConversationDataView(
        content=content,
        revision_ms=revision_ms,
        total_count=window.total_count,
        page=window.page,
        page_size=window.page_size,
        total_pages=window.total_pages,
        has_previous=window.has_previous,
        has_next=window.has_next,
    )


def _slice_index_payload(
    payload: object,
    sessions: list[dict],
    window: _PageWindow,
) -> object:
    if not isinstance(payload, dict):
        return payload
    visible_sessions = sessions[window.start:window.end]
    visible_ids = {
        str(item.get("session_id"))
        for item in visible_sessions
        if item.get("session_id") is not None
    }
    result = dict(payload)
    result["sessions"] = visible_sessions
    states = payload.get("session_states")
    if isinstance(states, dict):
        result["session_states"] = {
            session_id: value
            for session_id, value in states.items()
            if session_id in visible_ids
        }
    pinned = payload.get("pinned_session_ids")
    if isinstance(pinned, list):
        result["pinned_session_ids"] = [
            session_id for session_id in pinned if str(session_id) in visible_ids
        ]
    return result


def _require_session_id(value: str | None) -> str:
    normalized = (value or "").strip()
    if not normalized:
        raise BadRequestError("此数据视图需要会话 ID。")
    return normalized


def _json(value: object) -> str:
    return dumps(value, ensure_ascii=False, indent=2)


def _jsonl(values: list[dict]) -> str:
    return "".join(f"{dumps(value, ensure_ascii=False)}\n" for value in values)


def _database_mtime(workspace_dir: Path) -> int:
    path = database_path_from_workspace(workspace_dir)
    try:
        return int(path.stat().st_mtime_ns // 1_000_000)
    except OSError:
        return 0
