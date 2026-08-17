import os
from base64 import b64encode
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from json import dumps, loads

import pytest
from docx import Document

from app.core.errors import BadRequestError, ConflictError, NotFoundError
from app.domain.llm.chat import ChatToolCall
from app.domain.project import Project
from app.domain.project.project_conversation import ProjectConversationNamingCallRecord
from app.infra.projects.project_files import ProjectFileStorage
from app.repositories.project.conversation_repository import ProjectConversationRepository
from app.repositories.project.conversation_records import (
    list_message_payloads,
    read_conversation_control,
    read_events,
    read_session_state,
    read_workspace_state,
    replace_message_payloads,
    storage_marker,
    write_conversation_control,
    write_session_state,
)
from app.schemas.project.project_conversations import ProjectConversationSessionSettingsPatch
from app.schemas.project.project_files import ProjectWorkspaceStatePatchRequest
from app.services.document_conversion import MarkdownDocxService
from app.services.project.project_files import ProjectFileService
from app.services.project.project_workspace import ProjectWorkspaceService


PROJECT_ID = "00000000-0000-0000-0000-000000000123"


class FakeProjectRepository:
    def __init__(self, root_path: str) -> None:
        self.get_project_call_count = 0
        now = datetime.now(UTC).isoformat()
        self.project = Project(
            project_id=PROJECT_ID,
            name="test",
            root_path=root_path,
            is_default=False,
            sort_order=0,
            created_at=now,
            updated_at=now,
        )

    def get_project(self, project_id: str) -> Project | None:
        self.get_project_call_count += 1
        return self.project if project_id == PROJECT_ID else None


def test_workspace_state_accepts_role_configuration_dashboard():
    request = ProjectWorkspaceStatePatchRequest(
        active_dashboard="role_configuration",
    )

    assert request.active_dashboard == "role_configuration"


def test_workspace_state_accepts_theme_configuration_dashboard():
    request = ProjectWorkspaceStatePatchRequest(
        active_dashboard="theme_configuration",
    )

    assert request.active_dashboard == "theme_configuration"


def test_workspace_state_accepts_tool_dashboard():
    request = ProjectWorkspaceStatePatchRequest(active_dashboard="dependencies")

    assert request.active_dashboard == "dependencies"


def test_save_text_file_rejects_stale_mtime_without_overwriting(tmp_path):
    target = tmp_path / "note.txt"
    target.write_text("first", encoding="utf-8")
    repository = FakeProjectRepository(str(tmp_path))
    service = ProjectFileService(repository, ProjectFileStorage(), MarkdownDocxService())

    _content, mtime_ms = service.read_text_file(PROJECT_ID, "note.txt")
    target.write_text("external change", encoding="utf-8")
    next_mtime = target.stat().st_mtime + 2
    os.utime(target, (next_mtime, next_mtime))

    with pytest.raises(ConflictError):
        service.write_text_file(
            PROJECT_ID,
            "note.txt",
            "local change",
            expected_mtime_ms=mtime_ms,
        )

    assert target.read_text(encoding="utf-8") == "external change"


def test_uploaded_file_name_is_not_rejected_by_hidden_length_limit(tmp_path):
    repository = FakeProjectRepository(str(tmp_path))
    service = ProjectFileService(repository, ProjectFileStorage(), MarkdownDocxService())
    filename = f"{'a' * 181}.txt"

    node, saved_name, _mime_type, size_bytes = service.save_uploaded_file(
        PROJECT_ID,
        filename=filename,
        mime_type="text/plain",
        data_base64=b64encode(b"hello").decode("ascii"),
    )

    assert saved_name == filename
    assert size_bytes == 5
    assert (tmp_path / node.path).is_file()


def test_uploaded_image_name_is_not_rejected_by_hidden_length_limit(tmp_path):
    repository = FakeProjectRepository(str(tmp_path))
    service = ProjectFileService(repository, ProjectFileStorage(), MarkdownDocxService())
    filename = f"{'image' * 40}.png"

    node, mime_type, size_bytes = service.save_uploaded_image(
        PROJECT_ID,
        filename=filename,
        mime_type="image/png",
        data_base64=b64encode(b"\x89PNG\r\n\x1a\ncontent").decode("ascii"),
    )

    assert node.path.endswith(filename)
    assert mime_type == "image/png"
    assert size_bytes > 0
    assert (tmp_path / node.path).is_file()


def test_project_file_service_saves_public_markdown_docx_result(tmp_path):
    source_path = tmp_path / "note.md"
    source_path.write_text("# 项目文档", encoding="utf-8")
    repository = FakeProjectRepository(str(tmp_path))
    service = ProjectFileService(repository, ProjectFileStorage(), MarkdownDocxService())

    node, warnings = service.convert_markdown_content_to_docx(
        PROJECT_ID,
        target_path="note.md",
        content="# 编辑器中的最新内容",
    )

    output_path = tmp_path / node.path
    document = Document(output_path)

    assert node.path == "note.docx"
    assert document.paragraphs[0].text == "编辑器中的最新内容"
    assert warnings == ()


def test_workspace_patch_preserves_unsubmitted_fields(tmp_path):
    repository = FakeProjectRepository(str(tmp_path))
    service = ProjectWorkspaceService(repository)

    service.save_state(
        PROJECT_ID,
        expanded_paths=["src"],
        open_file_paths=["src/a.ts"],
        active_file_path="src/a.ts",
        active_dashboard="conversation_overview",
    )

    patched = service.patch_state(
        PROJECT_ID,
        expanded_paths=["src", "docs"],
        should_update_expanded_paths=True,
    )

    assert patched == {
        "expanded_paths": ["src", "docs"],
        "open_file_paths": ["src/a.ts"],
        "active_file_path": "src/a.ts",
        "active_dashboard": "conversation_overview",
    }


def test_workspace_get_state_ignores_old_workspace_directory(tmp_path):
    old_workspace = tmp_path / ".workspace"
    old_workspace.mkdir()
    (old_workspace / "state.json").write_text(
        dumps({"expanded_paths": ["old"]}, ensure_ascii=False),
        encoding="utf-8",
    )
    repository = FakeProjectRepository(str(tmp_path))
    service = ProjectWorkspaceService(repository)

    state = service.get_state(PROJECT_ID)

    assert state is None
    assert old_workspace.exists()
    assert storage_marker(tmp_path / ".Tiance")["version"] == 2
    assert not (tmp_path / ".Tiance" / "tiance.db").exists()


def test_workspace_save_state_writes_tiance_without_migrating_old_workspace(tmp_path):
    old_workspace = tmp_path / ".workspace"
    old_workspace.mkdir()
    repository = FakeProjectRepository(str(tmp_path))
    service = ProjectWorkspaceService(repository)

    saved = service.save_state(
        PROJECT_ID,
        expanded_paths=["src"],
        open_file_paths=[],
        active_file_path=None,
    )

    assert saved["expanded_paths"] == ["src"]
    assert saved["active_dashboard"] is None
    assert old_workspace.exists()
    assert read_workspace_state(tmp_path / ".Tiance") == saved
    assert not list((tmp_path / ".Tiance").glob(".*.tmp"))


def test_missing_project_root_is_not_recreated_by_project_writes(tmp_path):
    missing_root = tmp_path / "moved-external-project"
    repository = FakeProjectRepository(str(missing_root))
    workspace_service = ProjectWorkspaceService(repository)
    conversation_repository = ProjectConversationRepository(repository)
    file_service = ProjectFileService(
        repository,
        ProjectFileStorage(),
        MarkdownDocxService(),
    )

    with pytest.raises(NotFoundError, match="项目文件夹不存在或已被移动"):
        workspace_service.save_state(
            PROJECT_ID,
            expanded_paths=[],
            open_file_paths=[],
            active_file_path=None,
        )
    with pytest.raises(NotFoundError, match="项目文件夹不存在或已被移动"):
        conversation_repository.create_session(
            PROJECT_ID,
            title=None,
            provider_id=None,
            model_id=None,
            reasoning_mode=None,
        )
    with pytest.raises(NotFoundError, match="项目文件夹不存在或已被移动"):
        file_service.create_entry(
            PROJECT_ID,
            parent_path=None,
            kind="file",
            name="note.txt",
        )

    assert not missing_root.exists()


def test_workspace_editor_tabs_actions_update_unloaded_project_state(tmp_path):
    repository = FakeProjectRepository(str(tmp_path))
    service = ProjectWorkspaceService(repository)
    service.save_state(
        PROJECT_ID,
        expanded_paths=["docs"],
        open_file_paths=["docs/a.md", "docs/b.md"],
        active_file_path="docs/a.md",
        active_dashboard="conversation_overview",
    )

    opened = service.apply_editor_tabs_action(
        PROJECT_ID,
        action="open_file",
        path="docs/c.md",
    )
    focused = service.apply_editor_tabs_action(
        PROJECT_ID,
        action="focus_file",
        path="docs/b.md",
    )
    closed = service.apply_editor_tabs_action(
        PROJECT_ID,
        action="close_clean_tabs",
        paths=["docs/a.md", "docs/b.md"],
    )

    assert opened["open_file_paths"] == ["docs/a.md", "docs/b.md", "docs/c.md"]
    assert opened["active_file_path"] == "docs/c.md"
    assert opened["active_dashboard"] is None
    assert focused["active_file_path"] == "docs/b.md"
    assert closed["closed_file_paths"] == ["docs/a.md", "docs/b.md"]
    assert closed["open_file_paths"] == ["docs/c.md"]
    assert closed["active_file_path"] == "docs/c.md"
    assert closed["expanded_paths"] == ["docs"]


def test_workspace_editor_tabs_close_others_keeps_requested_tab(tmp_path):
    repository = FakeProjectRepository(str(tmp_path))
    service = ProjectWorkspaceService(repository)
    service.save_state(
        PROJECT_ID,
        expanded_paths=[],
        open_file_paths=["a.txt", "b.txt", "c.txt"],
        active_file_path="a.txt",
    )

    result = service.apply_editor_tabs_action(
        PROJECT_ID,
        action="close_others_clean",
        path="b.txt",
    )

    assert result["closed_file_paths"] == ["a.txt", "c.txt"]
    assert result["open_file_paths"] == ["b.txt"]
    assert result["active_file_path"] == "b.txt"


def test_workspace_editor_tabs_focus_rejects_unopened_file(tmp_path):
    repository = FakeProjectRepository(str(tmp_path))
    service = ProjectWorkspaceService(repository)

    with pytest.raises(BadRequestError, match="没有打开"):
        service.apply_editor_tabs_action(
            PROJECT_ID,
            action="focus_file",
            path="missing.txt",
        )


def test_conversation_session_persists_reasoning_mode(tmp_path):
    repository = ProjectConversationRepository(FakeProjectRepository(str(tmp_path)))

    session = repository.create_session(
        PROJECT_ID,
        title=None,
        provider_id="deepseek",
        model_id="deepseek-v4-flash",
        reasoning_mode="high",
    )

    assert session.reasoning_mode == "high"
    assert repository.get_session(PROJECT_ID, session.session_id).reasoning_mode == "high"

    updated = repository.update_session(
        PROJECT_ID,
        session.session_id,
        reasoning_mode="off",
        should_update_reasoning=True,
    )

    assert updated.reasoning_mode == "off"
    assert repository.get_session(PROJECT_ID, session.session_id).reasoning_mode == "off"


def test_conversation_repository_empty_reads_do_not_create_default_session(tmp_path):
    repository = ProjectConversationRepository(FakeProjectRepository(str(tmp_path)))

    sessions = repository.list_sessions(PROJECT_ID)
    assistant_title, active_session_id, states = repository.get_state(PROJECT_ID)

    assert sessions == ()
    assert assistant_title == "AI 助手"
    assert active_session_id is None
    assert states == {}
    assert storage_marker(tmp_path / ".Tiance")["version"] == 2
    assert not (tmp_path / ".Tiance" / "tiance.db").exists()


def test_conversation_repository_get_state_does_not_write_index(tmp_path):
    repository = ProjectConversationRepository(FakeProjectRepository(str(tmp_path)))
    session = repository.create_session(
        PROJECT_ID,
        title=None,
        provider_id=None,
        model_id=None,
        reasoning_mode=None,
    )
    conversations_dir = tmp_path / ".Tiance" / "conversations"
    session_dir = conversations_dir / "sessions" / session.session_id
    write_conversation_control(
        conversations_dir,
        {"active_session_id": "missing-session"},
    )
    write_session_state(
        session_dir,
        {
            "pinned": False,
            "runtime": {
            "runtime_status": "running",
            "draft": "keep",
            "updated_at": "2000-01-01T00:00:00+00:00",
            },
        },
    )
    before_control = read_conversation_control(conversations_dir)
    before_state = read_session_state(session_dir)

    _assistant_title, active_session_id, states = repository.get_state(PROJECT_ID)

    assert active_session_id == session.session_id
    assert states[session.session_id].runtime_status == "idle"
    assert states[session.session_id].draft == "keep"
    assert states[session.session_id].references == []
    assert read_conversation_control(conversations_dir) == before_control
    assert read_session_state(session_dir) == before_state


def test_conversation_repository_persists_session_references(tmp_path):
    repository = ProjectConversationRepository(FakeProjectRepository(str(tmp_path)))
    session = repository.create_session(
        PROJECT_ID,
        title=None,
        provider_id=None,
        model_id=None,
        reasoning_mode=None,
    )
    references = [
        {"type": "file", "reference": {"id": "file-1", "filePath": "docs/a.md"}},
        {"type": "image", "reference": {"id": "image-1", "imagePath": ".Tiance/uploads/a.png"}},
        {"type": "text", "reference": {"id": "text-1", "content": "selected"}},
    ]

    _assistant_title, _active_session_id, states = repository.save_state(
        PROJECT_ID,
        assistant_title=None,
        should_update_assistant_title=False,
        active_session_id=None,
        should_update_active_session=False,
        session_states={session.session_id: {"references": references}},
    )

    assert states[session.session_id].references == references
    saved_state = read_session_state(
        tmp_path
        / ".Tiance"
        / "conversations"
        / "sessions"
        / session.session_id
    )
    assert saved_state["runtime"]["references"] == references


def test_conversation_repository_recreates_default_session_after_deleting_last(tmp_path):
    repository = ProjectConversationRepository(FakeProjectRepository(str(tmp_path)))
    first_session = repository.create_session(
        PROJECT_ID,
        title=None,
        provider_id=None,
        model_id=None,
        reasoning_mode=None,
    )

    repository.delete_session(PROJECT_ID, first_session.session_id)

    sessions = repository.list_sessions(PROJECT_ID)
    assert len(sessions) == 1
    assert sessions[0].session_id != first_session.session_id
    assert sessions[0].sequence_number == 1
    assert sessions[0].title == "新对话"

    control = read_conversation_control(tmp_path / ".Tiance" / "conversations")
    assert control["active_session_id"] == sessions[0].session_id


def test_conversation_repository_persists_pins_without_changing_updated_at(tmp_path):
    repository = ProjectConversationRepository(FakeProjectRepository(str(tmp_path)))
    older_session = repository.create_session(
        PROJECT_ID,
        title="较早会话",
        provider_id=None,
        model_id=None,
        reasoning_mode=None,
    )
    newer_session = repository.create_session(
        PROJECT_ID,
        title="较新会话",
        provider_id=None,
        model_id=None,
        reasoning_mode=None,
    )

    pinned_session = repository.set_session_pinned(
        PROJECT_ID,
        older_session.session_id,
        pinned=True,
    )

    assert pinned_session.pinned is True
    assert pinned_session.updated_at == older_session.updated_at
    assert [session.session_id for session in repository.list_sessions(PROJECT_ID)] == [
        older_session.session_id,
        newer_session.session_id,
    ]
    pinned_state = read_session_state(
        tmp_path
        / ".Tiance"
        / "conversations"
        / "sessions"
        / older_session.session_id
    )
    assert pinned_state["pinned"] is True

    unpinned_session = repository.set_session_pinned(
        PROJECT_ID,
        older_session.session_id,
        pinned=False,
    )

    assert unpinned_session.pinned is False
    assert unpinned_session.updated_at == older_session.updated_at
    assert [session.session_id for session in repository.list_sessions(PROJECT_ID)] == [
        newer_session.session_id,
        older_session.session_id,
    ]


def test_conversation_repository_removes_deleted_session_from_pins(tmp_path):
    repository = ProjectConversationRepository(FakeProjectRepository(str(tmp_path)))
    pinned_session = repository.create_session(
        PROJECT_ID,
        title="置顶会话",
        provider_id=None,
        model_id=None,
        reasoning_mode=None,
    )
    repository.create_session(
        PROJECT_ID,
        title="保留会话",
        provider_id=None,
        model_id=None,
        reasoning_mode=None,
    )
    repository.set_session_pinned(
        PROJECT_ID,
        pinned_session.session_id,
        pinned=True,
    )

    repository.delete_session(PROJECT_ID, pinned_session.session_id)

    assert not (
        tmp_path
        / ".Tiance"
        / "conversations"
        / "sessions"
        / pinned_session.session_id
    ).exists()
    assert all(
        session.session_id != pinned_session.session_id
        for session in repository.list_sessions(PROJECT_ID)
    )


def test_conversation_repository_can_create_without_changing_active_session(tmp_path):
    repository = ProjectConversationRepository(FakeProjectRepository(str(tmp_path)))
    active_session = repository.create_session(
        PROJECT_ID,
        title="当前会话",
        provider_id="provider-a",
        model_id="model-a",
        reasoning_mode="off",
    )

    background_session = repository.create_session(
        PROJECT_ID,
        title="后台会话",
        provider_id="provider-a",
        model_id="model-a",
        reasoning_mode="off",
        set_active=False,
    )

    control = read_conversation_control(tmp_path / ".Tiance" / "conversations")
    assert control["active_session_id"] == active_session.session_id
    assert [item.session_id for item in repository.list_sessions(PROJECT_ID)] == [
        background_session.session_id,
        active_session.session_id,
    ]
    assert read_session_state(
        tmp_path
        / ".Tiance"
        / "conversations"
        / "sessions"
        / background_session.session_id
    )["runtime"]["runtime_status"] == "idle"


def test_conversation_session_uses_current_tool_call_default(tmp_path):
    repository = ProjectConversationRepository(FakeProjectRepository(str(tmp_path)))

    session = repository.create_session(
        PROJECT_ID,
        title="默认设置会话",
        provider_id="deepseek",
        model_id="deepseek-v4-flash",
        reasoning_mode=None,
    )

    assert session.settings.max_tool_calls == 99999
    assert session.settings.tools_enabled is True
    assert session.settings.inject_message_timestamps is True
    loaded = repository.get_session(PROJECT_ID, session.session_id)
    assert loaded.settings.max_tool_calls == 99999
    assert loaded.settings.tools_enabled is True
    assert loaded.settings.inject_message_timestamps is True


def test_conversation_session_persists_settings_and_manual_title(tmp_path):
    repository = ProjectConversationRepository(FakeProjectRepository(str(tmp_path)))

    assert (
        ProjectConversationSessionSettingsPatch(
            memory_context_token_trigger_threshold=400,
        ).memory_context_token_trigger_threshold
        == 400
    )

    session = repository.create_session(
        PROJECT_ID,
        title="手动标题",
        provider_id="deepseek",
        model_id="deepseek-v4-flash",
        reasoning_mode=None,
        manual_title=True,
        settings={
            "return_cancelled_messages": True,
            "return_user_before_cancelled": True,
            "streaming_enabled": False,
            "system_prompt": "你是主 Agent。",
            "global_memory_enabled": False,
            "memory_context_token_trigger_threshold": 123456,
            "memory_compression_enabled": False,
            "memory_raw_context_token_reserve": 12000,
            "project_memory_enabled": False,
            "max_output_tokens": 12000,
            "temperature": 3,
            "top_p": 2,
            "tools_enabled": False,
            "enabled_tool_names": ["read_text_file", "system_info"],
            "max_tool_calls": 400,
        },
    )

    loaded = repository.get_session(PROJECT_ID, session.session_id)
    assert loaded.manual_title is True
    assert loaded.settings.return_cancelled_messages is True
    assert loaded.settings.return_user_before_cancelled is True
    assert loaded.settings.streaming_enabled is False
    assert loaded.settings.system_prompt == "你是主 Agent。"
    assert loaded.settings.global_memory_enabled is False
    assert loaded.settings.memory_context_token_trigger_threshold == 123456
    assert loaded.settings.memory_compression_enabled is False
    assert loaded.settings.memory_raw_context_token_reserve == 12000
    assert loaded.settings.project_memory_enabled is False
    assert loaded.settings.max_output_tokens == 12000
    assert loaded.settings.temperature == 3
    assert loaded.settings.top_p == 2
    assert loaded.settings.tools_enabled is False
    assert loaded.settings.enabled_tool_names == ("read_text_file", "system_info")
    assert loaded.settings.max_tool_calls == 400

    updated = repository.update_session(
        PROJECT_ID,
        session.session_id,
        settings={
            "return_cancelled_messages": False,
            "inject_message_timestamps": False,
            "system_prompt": "新的提示词",
            "memory_context_token_trigger_threshold": 654321,
            "memory_compression_enabled": True,
            "memory_raw_context_token_reserve": 18000,
            "project_memory_enabled": True,
            "max_output_tokens": 4096,
            "temperature": 0.2,
            "top_p": None,
            "tools_enabled": True,
            "enabled_tool_names": ["read_text_file"],
            "max_tool_calls": 401,
        },
        should_update_settings=True,
    )

    assert updated.settings.return_cancelled_messages is False
    assert updated.settings.return_user_before_cancelled is True
    assert updated.settings.inject_message_timestamps is False
    assert updated.settings.streaming_enabled is False
    assert updated.settings.system_prompt == "新的提示词"
    assert updated.settings.global_memory_enabled is False
    assert updated.settings.memory_context_token_trigger_threshold == 654321
    assert updated.settings.memory_compression_enabled is True
    assert updated.settings.memory_raw_context_token_reserve == 18000
    assert updated.settings.project_memory_enabled is True
    assert updated.settings.max_output_tokens == 4096
    assert updated.settings.temperature == 0.2
    assert updated.settings.top_p is None
    assert updated.settings.tools_enabled is True
    assert updated.settings.enabled_tool_names == ("read_text_file",)
    assert updated.settings.max_tool_calls == 401


def test_conversation_message_can_skip_session_model_sync(tmp_path):
    repository = ProjectConversationRepository(FakeProjectRepository(str(tmp_path)))
    session = repository.create_session(
        PROJECT_ID,
        title=None,
        provider_id="volcengine",
        model_id="doubao-seed-1-6-flash",
        reasoning_mode=None,
    )

    message = repository.append_message(
        PROJECT_ID,
        session.session_id,
        role="assistant",
        content="partial",
        provider_id="deepseek",
        model_id="deepseek-v4",
        status="cancelled",
        sync_session_model=False,
    )

    updated_session = repository.get_session(PROJECT_ID, session.session_id)
    assert message.provider_id == "deepseek"
    assert message.model_id == "deepseek-v4"
    assert message.status == "cancelled"
    assert message.created_at_local is not None
    assert message.created_at_local[-6] in {"+", "-"}
    assert repository.list_messages(
        PROJECT_ID,
        session.session_id,
    )[0].created_at_local == message.created_at_local
    assert updated_session.provider_id == "volcengine"
    assert updated_session.model_id == "doubao-seed-1-6-flash"


def test_concurrent_conversation_writes_preserve_all_sessions_and_messages(tmp_path):
    repository = ProjectConversationRepository(FakeProjectRepository(str(tmp_path)))
    sessions = [
        repository.create_session(
            PROJECT_ID,
            title=f"session {index}",
            provider_id="deepseek",
            model_id="deepseek-v4-flash",
            reasoning_mode=None,
        )
        for index in range(4)
    ]

    def append_messages(session_index: int) -> None:
        session_id = sessions[session_index].session_id
        for message_index in range(5):
            repository.append_message(
                PROJECT_ID,
                session_id,
                role="user",
                content=f"{session_index}:{message_index}",
            )

    with ThreadPoolExecutor(max_workers=len(sessions)) as executor:
        list(executor.map(append_messages, range(len(sessions))))

    listed_sessions = {
        session.session_id: session
        for session in repository.list_sessions(PROJECT_ID)
    }
    assert set(listed_sessions) == {session.session_id for session in sessions}
    for session_index, session in enumerate(sessions):
        assert listed_sessions[session.session_id].message_count == 5
        assert [
            message.content
            for message in repository.list_messages(PROJECT_ID, session.session_id)
        ] == [f"{session_index}:{message_index}" for message_index in range(5)]


def test_runtime_status_update_does_not_rescan_all_sessions(tmp_path, monkeypatch):
    repository = ProjectConversationRepository(FakeProjectRepository(str(tmp_path)))
    session = repository.create_session(
        PROJECT_ID,
        title=None,
        provider_id="deepseek",
        model_id="deepseek-v4-flash",
        reasoning_mode=None,
    )

    def fail_if_scanned(_project_id):
        raise AssertionError("runtime status update must not scan every session")

    monkeypatch.setattr(repository, "list_sessions", fail_if_scanned)

    repository.save_session_runtime_status(PROJECT_ID, session.session_id, "running")

    conversations_dir = tmp_path / ".Tiance" / "conversations"
    index = repository._session_store.read_index(conversations_dir)
    assert index["session_states"][session.session_id]["runtime_status"] == "running"


def test_conversation_overview_resolves_project_root_once(tmp_path):
    project_repository = FakeProjectRepository(str(tmp_path))
    repository = ProjectConversationRepository(project_repository)
    created_sessions = tuple(
        repository.create_session(
            PROJECT_ID,
            title=f"session {index}",
            provider_id="deepseek",
            model_id="deepseek-v4-flash",
            reasoning_mode=None,
        )
        for index in range(3)
    )
    project_repository.get_project_call_count = 0

    sessions, branch_nodes, active_session_id, session_states = (
        repository.get_overview_data(PROJECT_ID)
    )

    assert {session.session_id for session in sessions} == {
        session.session_id for session in created_sessions
    }
    assert branch_nodes == ()
    assert active_session_id == created_sessions[-1].session_id
    assert set(session_states) == {
        session.session_id for session in created_sessions
    }
    assert project_repository.get_project_call_count == 1


def test_conversation_message_jsonl_uses_role_specific_fields(tmp_path):
    repository = ProjectConversationRepository(FakeProjectRepository(str(tmp_path)))
    session = repository.create_session(
        PROJECT_ID,
        title=None,
        provider_id="deepseek",
        model_id="deepseek-v4-flash",
        reasoning_mode=None,
    )

    user_message = repository.append_message(
        PROJECT_ID,
        session.session_id,
        role="user",
        content="只回复一个数字",
        thinking_content="ignored",
        usage={"total_tokens": 999},
        context_tokens=999,
        provider_id="deepseek",
        model_id="deepseek-v4-flash",
        references=[
            {"type": "file", "reference": {
                    "displayPath": "docs/a.md",
                    "fileName": "a.md",
                    "filePath": "docs/a.md",
                    "id": "file-1",
                    "kind": "file",
                    "projectId": PROJECT_ID,
                    "source": "project_file",
            }},
        ],
    )
    assistant_message = repository.append_message(
        PROJECT_ID,
        session.session_id,
        role="assistant",
        content="1",
        thinking_content="thinking",
        usage={"total_tokens": 12},
        context_tokens=3456,
        provider_id="deepseek",
        model_id="deepseek-v4-flash",
    )

    assert user_message.provider_id is None
    assert user_message.model_id is None
    assert user_message.target_provider_id == "deepseek"
    assert user_message.target_model_id == "deepseek-v4-flash"
    assert assistant_message.provider_id == "deepseek"
    assert assistant_message.model_id == "deepseek-v4-flash"
    assert assistant_message.context_tokens == 3456

    messages_dir = (
        tmp_path
        / ".Tiance"
        / "conversations"
        / "sessions"
        / session.session_id
    )
    user_payload, assistant_payload = list_message_payloads(messages_dir)

    assert user_payload["role"] == "user"
    assert user_payload["target_provider_id"] == "deepseek"
    assert user_payload["target_model_id"] == "deepseek-v4-flash"
    assert user_payload["content"] == "只回复一个数字"
    assert user_payload["references"] == user_message.references
    assert "provider_id" not in user_payload
    assert "model_id" not in user_payload
    assert "thinking_content" not in user_payload
    assert "usage" not in user_payload
    assert "context_tokens" not in user_payload

    assert assistant_payload["role"] == "assistant"
    assert assistant_payload["provider_id"] == "deepseek"
    assert assistant_payload["model_id"] == "deepseek-v4-flash"
    assert assistant_payload["thinking_content"] == "thinking"
    assert assistant_payload["usage"] == {"total_tokens": 12}
    assert assistant_payload["context_tokens"] == 3456
    assert "target_provider_id" not in assistant_payload
    assert "target_model_id" not in assistant_payload

    reloaded_messages = repository.list_messages(PROJECT_ID, session.session_id)
    assert reloaded_messages[0].references == user_message.references
    assert reloaded_messages[-1].context_tokens == 3456


def test_conversation_message_reader_ignores_user_provider_model_fields(tmp_path):
    repository = ProjectConversationRepository(FakeProjectRepository(str(tmp_path)))
    session = repository.create_session(
        PROJECT_ID,
        title=None,
        provider_id="deepseek",
        model_id="deepseek-v4-flash",
        reasoning_mode=None,
    )
    messages_dir = (
        tmp_path
        / ".Tiance"
        / "conversations"
        / "sessions"
        / session.session_id
    )
    replace_message_payloads(
        messages_dir,
        [{
                "message_id": "msg_user_current_contract",
                "session_id": session.session_id,
                "role": "user",
                "content": "hi",
                "thinking_content": "",
                "usage": None,
                "provider_id": "deepseek",
                "model_id": "deepseek-v4-flash",
                "status": "done",
                "created_at": "now",
                "updated_at": "now",
        }],
    )

    message = repository.list_messages(PROJECT_ID, session.session_id)[0]

    assert message.provider_id is None
    assert message.model_id is None
    assert message.target_provider_id is None
    assert message.target_model_id is None
    assert message.thinking_content == ""
    assert message.usage is None


def test_conversation_repository_lists_messages_by_recent_page(tmp_path):
    repository = ProjectConversationRepository(FakeProjectRepository(str(tmp_path)))
    session = repository.create_session(
        PROJECT_ID,
        title=None,
        provider_id="deepseek",
        model_id="deepseek-v4-flash",
        reasoning_mode=None,
    )
    for index in range(5):
        repository.append_message(
            PROJECT_ID,
            session.session_id,
            role="user",
            content=f"message {index}",
        )

    first_page = repository.list_messages_page(PROJECT_ID, session.session_id, limit=2)
    second_page = repository.list_messages_page(
        PROJECT_ID,
        session.session_id,
        limit=2,
        before_message_id=first_page.next_before_message_id,
    )

    assert first_page.total_count == 5
    assert [message.content for message in first_page.items] == ["message 3", "message 4"]
    assert first_page.has_more is True
    assert [message.content for message in second_page.items] == ["message 1", "message 2"]
    assert second_page.has_more is True


def test_conversation_recent_page_keeps_tool_result_with_preceding_tool_call(tmp_path):
    repository = ProjectConversationRepository(FakeProjectRepository(str(tmp_path)))
    session = repository.create_session(
        PROJECT_ID,
        title=None,
        provider_id="deepseek",
        model_id="deepseek-v4-flash",
        reasoning_mode=None,
    )
    repository.append_message(
        PROJECT_ID,
        session.session_id,
        role="user",
        content="old",
    )
    assistant_message = repository.append_message(
        PROJECT_ID,
        session.session_id,
        role="assistant",
        content="",
        tool_calls=(
            ChatToolCall(
                call_id="call-1",
                name="read_text_file",
                arguments='{"file_path":"README.md"}',
            ),
        ),
    )
    repository.append_message(
        PROJECT_ID,
        session.session_id,
        role="tool",
        content='{"ok":true,"content":"hello"}',
        name="read_text_file",
        tool_call_id="call-1",
    )
    repository.append_message(
        PROJECT_ID,
        session.session_id,
        role="user",
        content="latest",
    )

    page = repository.list_messages_page(PROJECT_ID, session.session_id, limit=2)

    assert [message.role for message in page.items] == ["assistant", "tool", "user"]
    assert page.items[0].message_id == assistant_message.message_id
    assert page.items[0].tool_calls[0].call_id == "call-1"
    assert page.items[1].tool_call_id == "call-1"
    assert page.has_more is True
    assert page.next_before_message_id == assistant_message.message_id


def test_conversation_naming_call_record_writes_jsonl(tmp_path):
    repository = ProjectConversationRepository(FakeProjectRepository(str(tmp_path)))
    session = repository.create_session(
        PROJECT_ID,
        title=None,
        provider_id="deepseek",
        model_id="deepseek-v4",
        reasoning_mode=None,
    )

    repository.append_naming_call_record(
        PROJECT_ID,
        session.session_id,
        ProjectConversationNamingCallRecord(
            naming_call_id="naming_call_1",
            session_id=session.session_id,
            provider_id="deepseek",
            model_id="deepseek-v4-flash",
            request={
                "messages": [
                    {"role": "system", "content": "输出 JSON 标题"},
                    {"role": "user", "content": "{\"messages\":[]}"},
                ],
                "generation": {"temperature": 0.2},
                "output": {"format": "json_object"},
            },
            response={"selected_title": "用量统计设计"},
            status="done",
            error=None,
            created_at="now",
            completed_at="now",
        ),
    )

    session_dir = (
        tmp_path
        / ".Tiance"
        / "conversations"
        / "sessions"
        / session.session_id
    )
    payload = read_events(session_dir, "naming_calls")[0]
    assert payload["naming_call_id"] == "naming_call_1"
    assert payload["request"]["messages"][0]["role"] == "system"
    assert payload["response"]["selected_title"] == "用量统计设计"
