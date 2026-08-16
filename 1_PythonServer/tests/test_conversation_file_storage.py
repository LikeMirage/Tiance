from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from json import dumps
from pathlib import Path
import sqlite3
from threading import Event

import pytest

from app.domain.project import Project
from app.repositories.project.conversation_data_view_repository import (
    ConversationDataViewRepository,
)
from app.repositories.project.conversation_file_io import (
    append_jsonl_recoverable,
    read_jsonl,
    write_json_object,
)
from app.repositories.project.conversation_records import (
    ensure_file_storage,
    list_message_payloads,
    read_document,
    read_events,
    read_project_events,
    read_session_branch,
    read_workspace_state,
    storage_marker,
)
from app.repositories.project.conversation_repository import (
    ProjectConversationRepository,
)


PROJECT_ID = "project-1"


class _Projects:
    def __init__(self, root: Path) -> None:
        self.project = Project(
            project_id=PROJECT_ID,
            name="project",
            root_path=str(root),
            is_default=False,
            sort_order=0,
            created_at="now",
            updated_at="now",
        )

    def get_project(self, project_id: str):
        return self.project if project_id == PROJECT_ID else None


def test_new_workspace_declares_files_as_truth_and_sqlite_as_cache(tmp_path: Path) -> None:
    workspace = ensure_file_storage(tmp_path / ".Tiance")

    assert storage_marker(workspace) == {
        "version": 2,
        "authoritative_storage": "files",
        "sqlite_role": "disposable_message_index",
    }
    assert not (workspace / "tiance.db").exists()
    assert (workspace / "conversations" / "sessions").is_dir()


def test_file_storage_initialization_is_safe_under_concurrent_access(tmp_path: Path) -> None:
    workspace = tmp_path / ".Tiance"
    with ThreadPoolExecutor(max_workers=12) as executor:
        paths = list(
            executor.map(lambda _index: ensure_file_storage(workspace), range(24))
        )

    assert len(set(paths)) == 1
    assert storage_marker(workspace)["version"] == 2


def test_partial_jsonl_append_is_read_consistently_and_repaired(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    append_jsonl_recoverable(path, {"id": "first"})
    source_size = path.stat().st_size
    pending_payload = {"id": "interrupted", "content": "未完整写入"}
    encoded = (
        dumps(pending_payload, ensure_ascii=False, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    write_json_object(
        path.with_name(".events.jsonl.pending.json"),
        {
            "version": 1,
            "source_size": source_size,
            "payload": pending_payload,
        },
    )
    with path.open("ab") as output:
        output.write(encoded[: len(encoded) // 2])

    assert read_jsonl(path) == [{"id": "first"}, pending_payload]

    append_jsonl_recoverable(path, {"id": "after-recovery"})

    assert read_jsonl(path) == [
        {"id": "first"},
        pending_payload,
        {"id": "after-recovery"},
    ]
    assert not path.with_name(".events.jsonl.pending.json").exists()


def test_full_history_is_never_read_from_a_limited_cache_view(tmp_path: Path) -> None:
    repository = ProjectConversationRepository(_Projects(tmp_path))
    session = repository.create_session(
        PROJECT_ID,
        title="完整历史",
        provider_id="provider",
        model_id="model",
        reasoning_mode=None,
    )
    for index in range(1_205):
        repository.append_message(
            PROJECT_ID,
            session.session_id,
            role="user" if index % 2 == 0 else "assistant",
            content=f"message-{index}",
            message_id=f"message-{index}",
        )

    messages = repository.list_messages(PROJECT_ID, session.session_id)

    assert len(messages) == 1_205
    assert messages[0].content == "message-0"
    assert messages[-1].content == "message-1204"


def test_disposable_sqlite_index_can_be_deleted_and_rebuilt(tmp_path: Path) -> None:
    repository = ProjectConversationRepository(_Projects(tmp_path))
    session = repository.create_session(
        PROJECT_ID,
        title="缓存重建",
        provider_id=None,
        model_id=None,
        reasoning_mode=None,
    )
    for index in range(80):
        repository.append_message(
            PROJECT_ID,
            session.session_id,
            role="user",
            content=f"record-{index}",
            message_id=f"record-{index}",
        )
    page = repository.list_messages_page(
        PROJECT_ID,
        session.session_id,
        limit=15,
    )
    assert len(page.items) == 15

    cache = tmp_path / ".Tiance" / "cache" / "conversation-index.db"
    assert cache.is_file()
    cache.unlink()

    rebuilt = repository.list_messages_page(
        PROJECT_ID,
        session.session_id,
        limit=15,
    )
    assert cache.is_file()
    assert rebuilt.total_count == 80
    assert [item.content for item in rebuilt.items] == [
        f"record-{index}" for index in range(65, 80)
    ]


def test_different_sessions_append_concurrently_without_overwriting(tmp_path: Path) -> None:
    repository = ProjectConversationRepository(_Projects(tmp_path))
    sessions = [
        repository.create_session(
            PROJECT_ID,
            title=f"并发-{index}",
            provider_id=None,
            model_id=None,
            reasoning_mode=None,
            set_active=index == 0,
        )
        for index in range(4)
    ]

    def append_range(session_id: str, worker: int) -> None:
        for index in range(50):
            message_id = f"{worker}-{index}"
            repository.append_message(
                PROJECT_ID,
                session_id,
                role="user",
                content=message_id,
                message_id=message_id,
            )

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [
            executor.submit(append_range, session.session_id, worker)
            for worker, session in enumerate(sessions)
        ]
        for future in futures:
            future.result()

    assert [
        len(repository.list_messages(PROJECT_ID, session.session_id))
        for session in sessions
    ] == [50, 50, 50, 50]


def test_deleting_a_session_waits_for_its_inflight_append(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repository = ProjectConversationRepository(_Projects(tmp_path))
    session = repository.create_session(
        PROJECT_ID,
        title="并发删除",
        provider_id=None,
        model_id=None,
        reasoning_mode=None,
    )
    append_entered = Event()
    allow_append = Event()
    original_append = repository._message_store.append_message

    def delayed_append(session_dir, message):
        append_entered.set()
        assert allow_append.wait(timeout=5)
        return original_append(session_dir, message)

    monkeypatch.setattr(repository._message_store, "append_message", delayed_append)
    with ThreadPoolExecutor(max_workers=2) as executor:
        append_future = executor.submit(
            repository.append_message,
            PROJECT_ID,
            session.session_id,
            role="user",
            content="must finish before deletion",
        )
        assert append_entered.wait(timeout=5)
        delete_future = executor.submit(
            repository.delete_session,
            PROJECT_ID,
            session.session_id,
        )
        with pytest.raises(FutureTimeoutError):
            delete_future.result(timeout=0.1)
        allow_append.set()
        assert append_future.result(timeout=5).content == "must finish before deletion"
        replacement = delete_future.result(timeout=5)

    assert replacement is not None
    assert repository.get_session(PROJECT_ID, session.session_id) is None
    assert replacement.session_id != session.session_id


def test_data_views_are_generated_from_canonical_files(tmp_path: Path) -> None:
    projects = _Projects(tmp_path)
    conversations = ProjectConversationRepository(projects)
    session = conversations.create_session(
        PROJECT_ID,
        title="数据看板",
        provider_id="provider",
        model_id="model",
        reasoning_mode=None,
    )
    conversations.append_message(
        PROJECT_ID,
        session.session_id,
        role="user",
        content="权威文件里的原始消息",
    )

    content, revision, total_count, truncated = ConversationDataViewRepository(
        projects
    ).read(
        PROJECT_ID,
        name="messages.jsonl",
        session_id=session.session_id,
    )

    assert "权威文件里的原始消息" in content
    assert revision > 0
    assert total_count == 1
    assert truncated is False
    assert (
        tmp_path
        / ".Tiance"
        / "conversations"
        / "sessions"
        / session.session_id
        / "messages.jsonl"
    ).is_file()


def test_legacy_sqlite_workspace_migrates_every_storage_family(tmp_path: Path) -> None:
    workspace = tmp_path / ".Tiance"
    database = workspace / "tiance.db"
    _create_legacy_database(database, message_count=135)

    ensure_file_storage(workspace)

    marker = storage_marker(workspace)
    assert marker["migrated_from"] == "sqlite-v1"
    assert marker["legacy_backup"] == "migrations/sqlite-v1/tiance.db"
    assert not database.exists()
    assert (workspace / marker["legacy_backup"]).is_file()
    session_dir = workspace / "conversations" / "sessions" / "session-a"
    messages = list_message_payloads(session_dir)
    assert len(messages) == 135
    assert messages[0]["content"] == "legacy-0"
    assert messages[-1]["content"] == "legacy-134"
    assert read_events(session_dir, "compressions") == [{"compression_id": "c1"}]
    assert read_document(session_dir, "memory_delivery") == {"version": 1}
    assert read_project_events(workspace, "project_memory") == [
        {"operation": "add", "memory_id": "pm1"}
    ]
    assert read_session_branch(session_dir)["node"]["session_id"] == "session-a"
    assert read_workspace_state(workspace) == {"expanded_paths": ["src"]}


def _create_legacy_database(path: Path, *, message_count: int) -> None:
    path.parent.mkdir(parents=True)
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE conversation_schema(version INTEGER NOT NULL);
        CREATE TABLE conversation_meta(key TEXT PRIMARY KEY, value_json TEXT NOT NULL);
        CREATE TABLE conversation_sessions(session_id TEXT PRIMARY KEY, payload_json TEXT NOT NULL);
        CREATE TABLE conversation_messages(
            session_id TEXT NOT NULL, ordinal INTEGER NOT NULL,
            message_id TEXT NOT NULL, payload_json TEXT NOT NULL,
            PRIMARY KEY(session_id, ordinal), UNIQUE(session_id, message_id)
        );
        CREATE TABLE conversation_session_documents(
            session_id TEXT NOT NULL, kind TEXT NOT NULL, payload_json TEXT NOT NULL,
            PRIMARY KEY(session_id, kind)
        );
        CREATE TABLE conversation_session_events(
            session_id TEXT NOT NULL, kind TEXT NOT NULL, ordinal INTEGER NOT NULL,
            payload_json TEXT NOT NULL, PRIMARY KEY(session_id, kind, ordinal)
        );
        CREATE TABLE conversation_project_events(
            kind TEXT NOT NULL, ordinal INTEGER NOT NULL, payload_json TEXT NOT NULL,
            PRIMARY KEY(kind, ordinal)
        );
        INSERT INTO conversation_schema(version) VALUES (1);
        """
    )
    session = {
        "session_id": "session-a",
        "sequence_number": 1,
        "title": "旧会话",
        "provider_id": None,
        "model_id": None,
        "reasoning_mode": None,
        "created_at": "2026-08-01T00:00:00+00:00",
        "updated_at": "2026-08-01T00:00:00+00:00",
        "message_count": message_count,
        "manual_title": False,
        "settings": {},
    }
    connection.execute(
        "INSERT INTO conversation_sessions VALUES (?, ?)",
        ("session-a", _json(session)),
    )
    for index in range(message_count):
        message = {
            "message_id": f"legacy-{index}",
            "session_id": "session-a",
            "role": "user",
            "content": f"legacy-{index}",
        }
        connection.execute(
            "INSERT INTO conversation_messages VALUES (?, ?, ?, ?)",
            ("session-a", index, message["message_id"], _json(message)),
        )
    connection.execute(
        "INSERT INTO conversation_session_events VALUES (?, ?, ?, ?)",
        ("session-a", "compressions", 0, _json({"compression_id": "c1"})),
    )
    connection.execute(
        "INSERT INTO conversation_session_documents VALUES (?, ?, ?)",
        ("session-a", "memory_delivery", _json({"version": 1})),
    )
    connection.execute(
        "INSERT INTO conversation_project_events VALUES (?, ?, ?)",
        (
            "project_memory",
            0,
            _json({"operation": "add", "memory_id": "pm1"}),
        ),
    )
    branch_graph = {
        "version": 4,
        "nodes": [
            {
                "branch_id": "branch-a",
                "tree_id": "tree-a",
                "session_id": "session-a",
                "parent_branch_id": None,
                "parent_session_id": None,
                "relation_kind": "root",
                "function_type": None,
                "created_by": "user",
                "history_mode": "empty",
                "source_message_id": None,
                "sibling_index": 0,
                "created_at": "2026-08-01T00:00:00+00:00",
                "deleted_at": None,
            }
        ],
        "variants": [],
    }
    index = {
        "active_session_id": "session-a",
        "pinned_session_ids": ["session-a"],
        "session_states": {"session-a": {"runtime_status": "idle"}},
    }
    for key, value in (
        ("branch_graph", branch_graph),
        ("conversation_index", index),
        ("workspace_state", {"expanded_paths": ["src"]}),
    ):
        connection.execute(
            "INSERT INTO conversation_meta VALUES (?, ?)",
            (key, _json(value)),
        )
    connection.commit()
    connection.close()


def _json(value: object) -> str:
    return dumps(value, ensure_ascii=False, separators=(",", ":"))
