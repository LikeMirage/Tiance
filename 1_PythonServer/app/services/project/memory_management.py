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
        page: int | None = None,
        page_size: int | None = None,
    ) -> dict[str, Any]:
        safe_scope = _normalize_scope(scope)
        events = self._list_scope_events(safe_scope, project_id=project_id)
        records = _memory_records_from_events(events, scope=safe_scope)
        filtered = _filter_memories(records, query)
        if page_size is None:
            return {
                "scope": safe_scope,
                "count": len(filtered),
                "total_count": len(filtered),
                "page": None,
                "page_size": None,
                "total_pages": None,
                "has_previous": False,
                "has_next": False,
                "items": filtered,
            }
        if page_size < 1 or (page is not None and page < 1):
            raise BadRequestError("页码和每页条数必须大于 0。")
        total_count = len(filtered)
        total_pages = max(1, (total_count + page_size - 1) // page_size)
        resolved_page = min(page or total_pages, total_pages)
        start = (resolved_page - 1) * page_size
        items = filtered[start:start + page_size]
        return {
            "scope": safe_scope,
            "count": len(items),
            "total_count": total_count,
            "page": resolved_page,
            "page_size": page_size,
            "total_pages": total_pages,
            "has_previous": resolved_page > 1,
            "has_next": resolved_page < total_pages,
            "items": items,
        }

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
        source_id = f"manual_{uuid4().hex[:16]}"
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
    current: dict[str, dict[str, Any]] = {}
    histories: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        operation = event.get("operation")
        memory_id = _event_memory_id(event)
        if not memory_id:
            continue
        histories.setdefault(memory_id, []).append(_event_summary(event, memory_id=memory_id))
        if operation == "add":
            content = _normalize_content(_optional_str(event.get("content")))
            if content:
                current[memory_id] = {
                    "id": memory_id,
                    "scope": scope,
                    "content": content,
                    "keywords": _normalize_keywords(event.get("keywords")),
                    "created_at": _optional_str(event.get("created_at")) or "",
                    "updated_at": _optional_str(event.get("created_at")) or "",
                    "source": _optional_str(event.get("source_compression_id")) or "",
                    "last_operation": "add",
                }
        elif operation == "update":
            content = _normalize_content(_optional_str(event.get("content")))
            if content and memory_id in current:
                current[memory_id] = {
                    **current[memory_id],
                    "content": content,
                    "keywords": _normalize_keywords(event.get("keywords")),
                    "updated_at": _optional_str(event.get("created_at")) or current[memory_id].get("updated_at", ""),
                    "source": _optional_str(event.get("source_compression_id")) or current[memory_id].get("source", ""),
                    "last_operation": "update",
                }
        elif operation == "delete":
            current.pop(memory_id, None)

    records: list[dict[str, Any]] = []
    for memory_id, record in current.items():
        record_events = histories.get(memory_id, [])
        records.append({
            **record,
            "event_count": len(record_events),
            "events": record_events,
        })
    return records


def _event_memory_id(event: dict[str, Any]) -> str:
    if event.get("operation") == "add":
        return _optional_str(event.get("memory_id")) or ""
    return _optional_str(event.get("target_memory_id")) or ""


def _event_summary(event: dict[str, Any], *, memory_id: str) -> dict[str, Any]:
    return {
        "operation": _optional_str(event.get("operation")) or "",
        "memory_id": memory_id,
        "source": _optional_str(event.get("source_compression_id")) or "",
        "created_at": _optional_str(event.get("created_at")) or "",
        "reason": _optional_str(event.get("reason")) or "",
    }


def _memory_search_text(memory: dict[str, Any]) -> str:
    keywords = memory.get("keywords")
    keyword_text = " ".join(str(item) for item in keywords) if isinstance(keywords, list) else ""
    return f"{memory.get('id', '')} {memory.get('content', '')} {keyword_text}"


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
