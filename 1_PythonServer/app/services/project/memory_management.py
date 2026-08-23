from __future__ import annotations

from datetime import UTC, datetime
from functools import lru_cache
from typing import Any
from uuid import uuid4

from app.core.errors import BadRequestError
from app.repositories.project.conversation_memory_repository import (
    ProjectConversationMemoryRepository,
    get_project_conversation_memory_repository,
)

_GLOBAL_SCOPE = "global"
_PROJECT_SCOPE = "project"
_SCOPES = {_GLOBAL_SCOPE, _PROJECT_SCOPE}
_READ_OPERATIONS = {"list", "search"}
_WRITE_OPERATIONS = {"add", "update", "delete"}
_RECORD_STATUSES = {"active", "deleted", "all"}


class ProjectMemoryManagementService:
    def __init__(self, repository: ProjectConversationMemoryRepository) -> None:
        self._repository = repository

    def list_memories(
        self,
        *,
        scope: str,
        project_id: str | None = None,
        query: str = "",
    ) -> list[dict[str, Any]]:
        safe_scope = _normalize_scope(scope)
        memories = self._list_scope_memories(safe_scope, project_id=project_id)
        return _filter_memories(memories, query)

    def list_memory_records(
        self,
        *,
        scope: str,
        project_id: str | None = None,
        query: str = "",
        status: str = "active",
        page: int | None = None,
        page_size: int | None = None,
    ) -> dict[str, Any]:
        safe_scope = _normalize_scope(scope)
        safe_status = _normalize_record_status(status)
        events = self._list_scope_events(safe_scope, project_id=project_id)
        records = _memory_records_from_events(events, scope=safe_scope)
        visible = (
            records
            if safe_status == "all"
            else [record for record in records if record["status"] == safe_status]
        )
        filtered = _filter_memories(visible, query)
        return _paginated_report(
            filtered,
            scope=safe_scope,
            page=page,
            page_size=page_size,
            status=safe_status,
        )

    def list_memory_events(
        self,
        *,
        scope: str,
        project_id: str | None = None,
        query: str = "",
        page: int | None = None,
        page_size: int | None = None,
    ) -> dict[str, Any]:
        safe_scope = _normalize_scope(scope)
        events = self._list_scope_events(safe_scope, project_id=project_id)
        detailed_events = _detailed_memory_events(events)
        filtered = _filter_memory_events(detailed_events, query)
        # The append order is authoritative. The log view presents the latest
        # committed event first without changing that stored order.
        filtered.reverse()
        return _paginated_report(
            filtered,
            scope=safe_scope,
            page=page,
            page_size=page_size,
        )

    def apply_operation(
        self,
        *,
        scope: str,
        operation: str,
        project_id: str | None = None,
        memory_id: str | None = None,
        content: str | None = None,
        keywords: list[str] | None = None,
        reason: str | None = None,
        source_operation_id: str | None = None,
    ) -> dict[str, Any]:
        safe_scope = _normalize_scope(scope)
        safe_operation = _normalize_write_operation(operation)
        current = self._list_scope_memories(safe_scope, project_id=project_id)
        current_by_id = {item["id"]: item for item in current}

        normalized_operation = _build_repository_operation(
            operation=safe_operation,
            current_by_id=current_by_id,
            memory_id=memory_id,
            content=content,
            keywords=keywords,
            reason=reason,
        )
        source_id = (
            source_operation_id.strip()
            if isinstance(source_operation_id, str) and source_operation_id.strip()
            else f"manual_{uuid4().hex[:16]}"
        )
        created_at = datetime.now(UTC).isoformat()
        applied = self._repository.apply_memory_operations(
            compression_id=source_id,
            project_id=project_id or "",
            created_at=created_at,
            global_operations=[normalized_operation] if safe_scope == _GLOBAL_SCOPE else [],
            project_operations=[normalized_operation] if safe_scope == _PROJECT_SCOPE else [],
        )[f"{safe_scope}_memory"]
        if not applied:
            raise BadRequestError("记忆操作未生效，请检查记忆 ID 和参数。")

        updated = self._list_scope_memories(safe_scope, project_id=project_id)
        target_id = _affected_memory_id(applied[0])
        return {
            "scope": safe_scope,
            "operation": safe_operation,
            "source_operation_id": source_id,
            "memory_id": target_id,
            "memory": _find_memory(updated, target_id),
            "memories": updated,
            "applied_event": applied[0],
        }

    def _list_scope_memories(
        self,
        scope: str,
        *,
        project_id: str | None,
    ) -> list[dict[str, Any]]:
        if scope == _GLOBAL_SCOPE:
            return [dict(item) for item in self._repository.list_global_memory_context()]
        if not project_id:
            raise BadRequestError("项目记忆需要当前项目上下文。")
        return [dict(item) for item in self._repository.list_project_memory_context(project_id)]

    def _list_scope_events(
        self,
        scope: str,
        *,
        project_id: str | None,
    ) -> list[dict[str, Any]]:
        if scope == _GLOBAL_SCOPE:
            return [dict(item) for item in self._repository.list_global_memory_events()]
        if not project_id:
            raise BadRequestError("项目记忆需要当前项目上下文。")
        return [dict(item) for item in self._repository.list_project_memory_events(project_id)]


def _paginated_report(
    items: list[dict[str, Any]],
    *,
    scope: str,
    page: int | None,
    page_size: int | None,
    status: str | None = None,
) -> dict[str, Any]:
    if page_size is None:
        report = {
            "scope": scope,
            "count": len(items),
            "total_count": len(items),
            "page": None,
            "page_size": None,
            "total_pages": None,
            "has_previous": False,
            "has_next": False,
            "items": items,
        }
        if status is not None:
            report["status"] = status
        return report
    if page_size < 1 or (page is not None and page < 1):
        raise BadRequestError("页码和每页条数必须大于 0。")
    total_count = len(items)
    total_pages = max(1, (total_count + page_size - 1) // page_size)
    resolved_page = min(page or total_pages, total_pages)
    start = (resolved_page - 1) * page_size
    page_items = items[start:start + page_size]
    report = {
        "scope": scope,
        "count": len(page_items),
        "total_count": total_count,
        "page": resolved_page,
        "page_size": page_size,
        "total_pages": total_pages,
        "has_previous": resolved_page > 1,
        "has_next": resolved_page < total_pages,
        "items": page_items,
    }
    if status is not None:
        report["status"] = status
    return report


def is_read_operation(operation: str) -> bool:
    return operation.strip().lower() in _READ_OPERATIONS


def _normalize_scope(scope: str) -> str:
    normalized = scope.strip().lower() if isinstance(scope, str) else ""
    if normalized not in _SCOPES:
        raise BadRequestError("记忆范围必须是 global 或 project。")
    return normalized


def _normalize_write_operation(operation: str) -> str:
    normalized = operation.strip().lower() if isinstance(operation, str) else ""
    if normalized not in _WRITE_OPERATIONS:
        raise BadRequestError("写入操作必须是 add、update 或 delete。")
    return normalized


def _normalize_record_status(status: str) -> str:
    normalized = status.strip().lower() if isinstance(status, str) else ""
    if normalized not in _RECORD_STATUSES:
        raise BadRequestError("记忆状态必须是 active、deleted 或 all。")
    return normalized


def _filter_memories(memories: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    needle = query.strip().casefold() if isinstance(query, str) else ""
    if not needle:
        return memories
    return [
        memory
        for memory in memories
        if needle in _memory_search_text(memory).casefold()
    ]


def _memory_records_from_events(events: list[dict[str, Any]], *, scope: str) -> list[dict[str, Any]]:
    records, _detailed_events = _memory_projection(events, scope=scope)
    return records


def _detailed_memory_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    _records, detailed_events = _memory_projection(events, scope="")
    return detailed_events


def _memory_projection(
    events: list[dict[str, Any]],
    *,
    scope: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    active: dict[str, dict[str, Any]] = {}
    records: dict[str, dict[str, Any]] = {}
    histories: dict[str, list[dict[str, Any]]] = {}
    detailed_events: list[dict[str, Any]] = []

    for event_index, event in enumerate(events, start=1):
        operation = event.get("operation")
        memory_id = _event_memory_id(event)
        if not memory_id:
            continue
        before = _memory_payload(active.get(memory_id))
        created_at = _optional_str(event.get("created_at")) or ""
        source = _optional_str(event.get("source_compression_id")) or ""

        if operation == "add":
            content = _normalize_content(_optional_str(event.get("content")))
            if not content:
                continue
            active[memory_id] = {
                "id": memory_id,
                "scope": scope,
                "status": "active",
                "content": content,
                "keywords": _normalize_keywords(event.get("keywords")),
                "created_at": created_at,
                "updated_at": created_at,
                "deleted_at": "",
                "source": source,
                "last_operation": "add",
            }
            records[memory_id] = active[memory_id]
        elif operation == "update":
            content = _normalize_content(_optional_str(event.get("content")))
            if not content or memory_id not in active:
                continue
            active[memory_id] = {
                **active[memory_id],
                "content": content,
                "keywords": _normalize_keywords(event.get("keywords")),
                "updated_at": created_at or active[memory_id].get("updated_at", ""),
                "source": source or active[memory_id].get("source", ""),
                "last_operation": "update",
            }
            records[memory_id] = active[memory_id]
        elif operation == "delete":
            current = active.pop(memory_id, None)
            if current is None:
                continue
            records[memory_id] = {
                **current,
                "status": "deleted",
                "updated_at": created_at or current.get("updated_at", ""),
                "deleted_at": created_at,
                "source": source or current.get("source", ""),
                "last_operation": "delete",
            }
        else:
            continue

        summary = _event_summary(
            event,
            event_index=event_index,
            memory_id=memory_id,
            before=before,
            after=_memory_payload(active.get(memory_id)),
        )
        histories.setdefault(memory_id, []).append(summary)
        detailed_events.append(summary)

    return [
        {
            **record,
            "event_count": len(histories.get(memory_id, [])),
            "events": histories.get(memory_id, []),
        }
        for memory_id, record in records.items()
    ], detailed_events


def _event_memory_id(event: dict[str, Any]) -> str:
    if event.get("operation") == "add":
        return _optional_str(event.get("memory_id")) or ""
    return _optional_str(event.get("target_memory_id")) or ""


def _event_summary(
    event: dict[str, Any],
    *,
    event_index: int,
    memory_id: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "event_index": event_index,
        "operation": _optional_str(event.get("operation")) or "",
        "memory_id": memory_id,
        "source": _optional_str(event.get("source_compression_id")) or "",
        "created_at": _optional_str(event.get("created_at")) or "",
        "reason": _optional_str(event.get("reason")) or "",
        "before": before,
        "after": after,
    }


def _memory_search_text(memory: dict[str, Any]) -> str:
    keywords = memory.get("keywords")
    keyword_text = " ".join(str(item) for item in keywords) if isinstance(keywords, list) else ""
    return f"{memory.get('id', '')} {memory.get('content', '')} {keyword_text}"


def _filter_memory_events(
    events: list[dict[str, Any]],
    query: str,
) -> list[dict[str, Any]]:
    needle = query.strip().casefold() if isinstance(query, str) else ""
    if not needle:
        return events
    return [event for event in events if needle in _memory_event_search_text(event).casefold()]


def _memory_event_search_text(event: dict[str, Any]) -> str:
    before = event.get("before") if isinstance(event.get("before"), dict) else {}
    after = event.get("after") if isinstance(event.get("after"), dict) else {}
    keywords = [
        *(_normalize_keywords(before.get("keywords"))),
        *(_normalize_keywords(after.get("keywords"))),
    ]
    return " ".join((
        str(event.get("event_index", "")),
        str(event.get("memory_id", "")),
        str(event.get("operation", "")),
        str(event.get("source", "")),
        str(event.get("reason", "")),
        str(before.get("content", "")),
        str(after.get("content", "")),
        " ".join(keywords),
    ))


def _memory_payload(record: dict[str, Any] | None) -> dict[str, Any] | None:
    if record is None:
        return None
    return {
        "content": str(record.get("content") or ""),
        "keywords": _normalize_keywords(record.get("keywords")),
    }


def _build_repository_operation(
    *,
    operation: str,
    current_by_id: dict[str, dict[str, Any]],
    memory_id: str | None,
    content: str | None,
    keywords: list[str] | None,
    reason: str | None,
) -> dict[str, Any]:
    safe_keywords = _normalize_keywords(keywords)
    safe_reason = _normalize_content(reason)
    if not safe_reason:
        raise BadRequestError("记忆写入需要明确的变更原因。")
    if operation == "add":
        safe_content = _normalize_content(content)
        if not safe_content:
            raise BadRequestError("新增记忆需要 content。")
        return {
            "operation": "add",
            "content": safe_content,
            "keywords": safe_keywords,
            "reason": safe_reason,
        }

    safe_memory_id = memory_id.strip() if isinstance(memory_id, str) else ""
    if not safe_memory_id or safe_memory_id not in current_by_id:
        raise BadRequestError("记忆 ID 不存在。")
    if operation == "delete":
        return {
            "operation": "delete",
            "target_memory_id": safe_memory_id,
            "content": "",
            "keywords": [],
            "reason": safe_reason,
        }

    current = current_by_id[safe_memory_id]
    safe_content = _normalize_content(content) or str(current.get("content") or "")
    if not safe_content:
        raise BadRequestError("更新记忆需要 content。")
    return {
        "operation": "update",
        "target_memory_id": safe_memory_id,
        "content": safe_content,
        "keywords": safe_keywords if keywords is not None else _normalize_keywords(current.get("keywords")),
        "reason": safe_reason,
    }


def _normalize_content(value: str | None) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()


def _optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _normalize_keywords(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            continue
        keyword = item.strip()
        if not keyword or keyword in seen:
            continue
        result.append(keyword)
        seen.add(keyword)
    return result


def _affected_memory_id(event: dict[str, Any]) -> str:
    if event.get("operation") == "add":
        return str(event.get("memory_id") or "")
    return str(event.get("target_memory_id") or "")


def _find_memory(memories: list[dict[str, Any]], memory_id: str) -> dict[str, Any] | None:
    for memory in memories:
        if memory.get("id") == memory_id:
            return memory
    return None


@lru_cache
def get_project_memory_management_service() -> ProjectMemoryManagementService:
    return ProjectMemoryManagementService(get_project_conversation_memory_repository())
