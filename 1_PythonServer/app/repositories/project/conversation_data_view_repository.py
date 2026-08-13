from __future__ import annotations

from json import dumps
from pathlib import Path
from typing import Literal

from app.core.errors import BadRequestError, NotFoundError
from app.repositories.project.conversation_database import (
    database_path_from_workspace,
    count_message_payloads,
    list_message_payloads_range,
    read_document,
    read_events,
    read_meta,
    read_project_events,
    read_session,
)
from app.repositories.project.conversation_storage import ProjectWorkspaceDirectoryResolver
from app.repositories.project.project_repository import ProjectRepository


ConversationDataViewName = Literal[
    "index.json",
    "session.json",
    "messages.jsonl",
    "compressions.jsonl",
    "injection_preview.json",
    "project_memory.jsonl",
]


class ConversationDataViewRepository:
    """Build read-only dashboard documents from the project conversation database."""

    def __init__(self, project_repository: ProjectRepository) -> None:
        self._projects = project_repository
        self._workspace = ProjectWorkspaceDirectoryResolver()

    def read(
        self,
        project_id: str,
        *,
        name: ConversationDataViewName,
        session_id: str | None,
    ) -> tuple[str, int, int | None, bool]:
        project = self._projects.get_project(project_id)
        if project is None:
            raise NotFoundError("项目不存在。")
        workspace_dir = self._workspace.resolve_workspace_dir(
            Path(project.root_path),
            for_write=False,
        )
        conversations_dir = workspace_dir / "conversations"
        if name == "index.json":
            payload = read_meta(conversations_dir, "conversation_index", {})
            return _json(payload), _database_mtime(workspace_dir), None, False
        if name == "project_memory.jsonl":
            events = read_project_events(workspace_dir, "project_memory")
            return _jsonl(events), _database_mtime(workspace_dir), len(events), False

        resolved_session_id = _require_session_id(session_id)
        session = read_session(conversations_dir, resolved_session_id)
        if session is None:
            raise NotFoundError("会话不存在。")
        session_dir = conversations_dir / "sessions" / resolved_session_id
        if name == "session.json":
            return _json(session), _database_mtime(workspace_dir), None, False
        if name == "messages.jsonl":
            total_count = count_message_payloads(session_dir)
            start = max(0, total_count - 1_000)
            messages = list_message_payloads_range(
                session_dir,
                start_ordinal=start,
                end_ordinal=total_count,
            )
            return (
                _jsonl(messages),
                _database_mtime(workspace_dir),
                total_count,
                start > 0,
            )
        if name == "compressions.jsonl":
            events = read_events(session_dir, "compressions")
            return _jsonl(events), _database_mtime(workspace_dir), len(events), False
        if name == "injection_preview.json":
            return _json(read_document(session_dir, "injection_preview") or {}), _database_mtime(workspace_dir), None, False
        raise BadRequestError("不支持的数据视图。")


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
