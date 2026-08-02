from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache
from json import dumps, loads
from pathlib import Path
from re import fullmatch
from typing import Any
from uuid import uuid4

from app.core.config import get_settings
from app.core.errors import NotFoundError
from app.repositories.project.conversation_storage import (
    CONVERSATIONS_DIR,
    SESSION_FILE,
    ProjectWorkspaceDirectoryResolver,
    append_jsonl,
    atomic_write_text,
    conversation_write_lock,
)
from app.repositories.project.project_repository import ProjectRepository, get_project_repository

COMPRESSIONS_FILE = "compressions.jsonl"
PROJECT_MEMORY_FILE = "project_memory.jsonl"
GLOBAL_MEMORY_FILE = "global_memory.jsonl"
MEMORY_DELIVERY_FILE = "memory_delivery.json"


class ProjectConversationMemoryRepository:
    def __init__(
        self,
        project_repository: ProjectRepository,
        *,
        global_memory_root: Path,
        workspace_resolver: ProjectWorkspaceDirectoryResolver | None = None,
    ) -> None:
        self._project_repository = project_repository
        self._global_memory_root = global_memory_root
        self._workspace_resolver = workspace_resolver or ProjectWorkspaceDirectoryResolver()

    def list_global_memory_context(self) -> list[dict[str, str]]:
        return _memory_context_from_events(_read_jsonl(self._global_memory_path()))

    def list_project_memory_context(self, project_id: str) -> list[dict[str, str]]:
        return _memory_context_from_events(_read_jsonl(self._project_memory_path(project_id, for_write=False)))

    def list_global_memory_events(self) -> list[dict[str, Any]]:
        return _read_jsonl(self._global_memory_path())

    def list_project_memory_events(self, project_id: str) -> list[dict[str, Any]]:
        return _read_jsonl(self._project_memory_path(project_id, for_write=False))

    def read_session_memory_delivery_state(
        self,
        project_id: str,
        session_id: str,
    ) -> dict[str, Any] | None:
        path = self._session_dir(project_id, session_id) / MEMORY_DELIVERY_FILE
        return _read_json_object(path)

    def update_session_memory_delivery_state(
        self,
        project_id: str,
        session_id: str,
        update: Callable[[dict[str, Any] | None], dict[str, Any]],
    ) -> dict[str, Any]:
        session_dir = self._session_dir(project_id, session_id, for_write=True)
        path = session_dir / MEMORY_DELIVERY_FILE
        with conversation_write_lock(_conversations_dir_from_session_dir(session_dir)):
            updated = update(_read_json_object(path))
            atomic_write_text(
                path,
                f"{dumps(updated, ensure_ascii=False, separators=(',', ':'))}\n",
            )
        return updated

    def append_compression(
        self,
        project_id: str,
        session_id: str,
        payload: dict[str, Any],
    ) -> None:
        session_dir = self._session_dir(project_id, session_id, for_write=True)
        path = session_dir / COMPRESSIONS_FILE
        with conversation_write_lock(_conversations_dir_from_session_dir(session_dir)):
            records = _read_jsonl(path)
            records.append(payload)
            _write_compression_records(path, records)

    def list_compressions(
        self,
        project_id: str,
        session_id: str,
    ) -> list[dict[str, Any]]:
        return _read_jsonl(self._session_dir(project_id, session_id) / COMPRESSIONS_FILE)

    def apply_memory_operations(
        self,
        *,
        compression_id: str,
        project_id: str,
        created_at: str,
        global_operations: list[dict[str, Any]],
        project_operations: list[dict[str, Any]],
    ) -> dict[str, list[dict[str, Any]]]:
        applied: dict[str, list[dict[str, Any]]] = {
            "global_memory": [],
            "project_memory": [],
        }
        if _has_effective_operations(global_operations):
            applied["global_memory"] = self._append_memory_operations(
                self._global_memory_path(),
                scope="global",
                compression_id=compression_id,
                created_at=created_at,
                operations=global_operations,
            )
        if _has_effective_operations(project_operations):
            applied["project_memory"] = self._append_memory_operations(
                self._project_memory_path(project_id, for_write=True),
                scope="project",
                compression_id=compression_id,
                created_at=created_at,
                operations=project_operations,
            )
        return applied

    def _append_memory_operations(
        self,
        path: Path,
        *,
        scope: str,
        compression_id: str,
        created_at: str,
        operations: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        applied: list[dict[str, Any]] = []
        with conversation_write_lock(path.parent):
            current_ids = {
                item["id"]
                for item in _memory_context_from_events(_read_jsonl(path))
            }
            for operation in operations:
                event = _normalize_memory_operation_event(
                    operation,
                    scope=scope,
                    compression_id=compression_id,
                    current_ids=current_ids,
                    created_at=created_at,
                )
                if event is None:
                    continue
                append_jsonl(path, event)
                applied.append(event)
                op = event["operation"]
                if op == "add":
                    current_ids.add(str(event["memory_id"]))
                elif op == "delete":
                    current_ids.discard(str(event["target_memory_id"]))
        return applied

    def _global_memory_path(self) -> Path:
        return self._global_memory_root / GLOBAL_MEMORY_FILE

    def _project_memory_path(self, project_id: str, *, for_write: bool) -> Path:
        return self._workspace_dir(project_id, for_write=for_write) / "memory" / PROJECT_MEMORY_FILE

    def _session_dir(self, project_id: str, session_id: str, *, for_write: bool = False) -> Path:
        if not fullmatch(r"[A-Za-z0-9_-]+", session_id):
            raise NotFoundError(f"Conversation session '{session_id}' was not found.")
        session_dir = self._workspace_dir(project_id, for_write=for_write) / CONVERSATIONS_DIR / "sessions" / session_id
        if not (session_dir / SESSION_FILE).is_file():
            raise NotFoundError(f"Conversation session '{session_id}' was not found.")
        return session_dir

    def _workspace_dir(self, project_id: str, *, for_write: bool = False) -> Path:
        project = self._project_repository.get_project(project_id)
        if project is None:
            raise NotFoundError(f"项目 '{project_id}' 不存在。")
        return self._workspace_resolver.resolve_workspace_dir(Path(project.root_path), for_write=for_write)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = loads(line)
        except ValueError as exc:
            raise ValueError("Invalid conversation memory JSONL record.") from exc
        if not isinstance(payload, dict):
            raise ValueError("Conversation memory JSONL records must be objects.")
        events.append(payload)
    return events


def _read_json_object(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ValueError("Invalid conversation memory delivery JSON.") from exc
    if not isinstance(payload, dict):
        raise ValueError("Conversation memory delivery data must be a JSON object.")
    return payload


def _write_compression_records(path: Path, records: list[dict[str, Any]]) -> None:
    content = "".join(
        f"{dumps(record, ensure_ascii=False, separators=(',', ':'))}\n"
        for record in records
    )
    atomic_write_text(path, content)


def _conversations_dir_from_session_dir(session_dir: Path) -> Path:
    return session_dir.parent.parent


def _has_effective_operations(operations: list[dict[str, Any]]) -> bool:
    return any(operation.get("operation") != "none" for operation in operations)


def _memory_context_from_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    current: dict[str, dict[str, Any]] = {}
    for event in events:
        operation = event.get("operation")
        if operation == "add":
            memory_id = _optional_str(event.get("memory_id"))
            content = _optional_str(event.get("content"))
            if memory_id and content:
                current[memory_id] = {
                    "content": content,
                    "keywords": _string_list(event.get("keywords")),
                }
        elif operation == "update":
            target_memory_id = _optional_str(event.get("target_memory_id"))
            content = _optional_str(event.get("content"))
            if target_memory_id and content and target_memory_id in current:
                current[target_memory_id] = {
                    "content": content,
                    "keywords": _string_list(event.get("keywords")),
                }
        elif operation == "delete":
            target_memory_id = _optional_str(event.get("target_memory_id"))
            if target_memory_id:
                current.pop(target_memory_id, None)
    return [
        {
            "id": memory_id,
            "content": payload["content"],
            "keywords": payload["keywords"],
        }
        for memory_id, payload in current.items()
    ]


def _normalize_memory_operation_event(
    operation: dict[str, Any],
    *,
    scope: str,
    compression_id: str,
    current_ids: set[str],
    created_at: str,
) -> dict[str, Any] | None:
    op = operation.get("operation")
    if op == "none":
        return None
    reason = _trim_text(operation.get("reason"))
    keywords = _string_list(operation.get("keywords"))
    if op == "add":
        content = _trim_text(operation.get("content"))
        if not content:
            return None
        return {
            "memory_id": f"{_scope_prefix(scope)}_{uuid4().hex[:16]}",
            "operation": "add",
            "target_memory_id": None,
            "content": content,
            "keywords": keywords,
            "reason": reason,
            "source_compression_id": compression_id,
            "created_at": created_at,
        }
    if op in {"update", "delete"}:
        target_memory_id = _optional_str(operation.get("target_memory_id"))
        if not target_memory_id or target_memory_id not in current_ids:
            return None
        content = "" if op == "delete" else _trim_text(operation.get("content"))
        if op == "update" and not content:
            return None
        return {
            "memory_id": None,
            "operation": op,
            "target_memory_id": target_memory_id,
            "content": content,
            "keywords": keywords,
            "reason": reason,
            "source_compression_id": compression_id,
            "created_at": created_at,
        }
    return None


def _scope_prefix(scope: str) -> str:
    return {"global": "gm", "project": "pm"}.get(scope, "mem")


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _trim_text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    items: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = _trim_text(item)
        if not text or text in seen:
            continue
        items.append(text)
        seen.add(text)
    return items


@lru_cache
def get_project_conversation_memory_repository() -> ProjectConversationMemoryRepository:
    settings = get_settings()
    return ProjectConversationMemoryRepository(
        get_project_repository(),
        global_memory_root=settings.memory_data_path,
    )
