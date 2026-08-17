from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from json import dumps
from pathlib import Path
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


def test_existing_legacy_sqlite_file_is_left_untouched(tmp_path: Path) -> None:
    workspace = tmp_path / ".Tiance"
    workspace.mkdir()
    legacy_database = workspace / "tiance.db"
    legacy_content = b"legacy-database-placeholder"
    legacy_database.write_bytes(legacy_content)

    ensure_file_storage(workspace)

    assert legacy_database.read_bytes() == legacy_content
    assert storage_marker(workspace)["authoritative_storage"] == "files"
    assert not (workspace / "migrations").exists()


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
