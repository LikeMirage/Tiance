from json import dumps
from inspect import signature

from app.api.routes.project.conversations import (
    list_project_conversation_messages,
    read_conversation_data_view,
)
from app.api.routes.project.memory import list_project_memory
from app.api.routes.global_memory import (
    list_global_memory_events,
    list_global_memory_records,
)
from app.domain.project import Project
from app.domain.project.project_conversation import ProjectConversationSessionSettings
from app.infra.llm.chat_adapters.common import _optional_int
from app.repositories.project.conversation_memory_repository import ProjectConversationMemoryRepository
from app.repositories.project.conversation_serialization import (
    _normalize_session_title,
    _optional_int_or_none,
    _payload_int,
)
from app.repositories.project.conversation_serialization_settings import (
    _merge_session_settings,
    _session_settings_from_payload,
)
from app.repositories.llm.usage_repository import _normalize_usage_feature_key
from app.schemas.project.project_conversations import ProjectConversationSessionSettingsPatch
from app.schemas.project.project_database import ProjectDatabaseQueryRequest
from app.services.project.conversation_naming_messages import extract_title
from app.services.project.memory_management import ProjectMemoryManagementService


PROJECT_ID = "00000000-0000-0000-0000-000000000321"


class FakeProjectRepository:
    def __init__(self, root_path: str) -> None:
        self.project = Project(
            project_id=PROJECT_ID,
            name="test",
            root_path=root_path,
            is_default=False,
            sort_order=0,
            created_at="now",
            updated_at="now",
        )

    def get_project(self, project_id: str) -> Project | None:
        return self.project if project_id == PROJECT_ID else None


def test_memory_repository_does_not_truncate_memory_content_reason_or_keywords(tmp_path):
    (tmp_path / "project").mkdir()
    repository = ProjectConversationMemoryRepository(
        FakeProjectRepository(str(tmp_path / "project")),
        global_memory_root=tmp_path / "runtime" / "memory",
    )
    content = "C" * 800
    reason = "R" * 120
    keywords = [f"keyword-{index}-{'K' * 100}" for index in range(20)]

    applied = repository.apply_memory_operations(
        compression_id="compression-1",
        project_id=PROJECT_ID,
        created_at="2026-01-01T00:00:00+00:00",
        global_operations=[],
        project_operations=[
            {
                "operation": "add",
                "content": content,
                "reason": reason,
                "keywords": keywords,
            }
        ],
    )["project_memory"][0]

    assert applied["content"] == content
    assert applied["reason"] == reason
    assert applied["keywords"] == keywords

    context = repository.list_project_memory_context(PROJECT_ID)[0]
    assert context["content"] == content
    assert context["keywords"] == keywords


def test_memory_management_does_not_truncate_manual_keywords(tmp_path):
    (tmp_path / "project").mkdir()
    repository = ProjectConversationMemoryRepository(
        FakeProjectRepository(str(tmp_path / "project")),
        global_memory_root=tmp_path / "runtime" / "memory",
    )
    service = ProjectMemoryManagementService(repository)
    keywords = [f"manual-keyword-{index}-{'K' * 100}" for index in range(20)]

    result = service.apply_operation(
        scope="project",
        operation="add",
        project_id=PROJECT_ID,
        content="手动记忆内容",
        keywords=keywords,
        reason="验证手工关键词列表不会被静默截断",
    )

    assert result["applied_event"]["keywords"] == keywords
    assert result["memory"]["keywords"] == keywords


def test_session_settings_do_not_truncate_system_prompt_or_tool_names():
    system_prompt = "P" * 21000
    tool_names = [f"tool_{index}_{'N' * 100}" for index in range(220)]

    settings = _session_settings_from_payload({
        "system_prompt": system_prompt,
        "enabled_tool_names": tool_names,
    })

    assert settings.system_prompt == system_prompt
    assert settings.enabled_tool_names == tuple(tool_names)

    merged = _merge_session_settings(
        ProjectConversationSessionSettings(),
        {
            "system_prompt": system_prompt,
            "enabled_tool_names": tool_names,
        },
    )

    assert merged.system_prompt == system_prompt
    assert merged.enabled_tool_names == tuple(tool_names)

    patch = ProjectConversationSessionSettingsPatch(
        system_prompt=system_prompt,
        enabled_tool_names=tool_names,
    )
    assert patch.system_prompt == system_prompt
    assert patch.enabled_tool_names == tool_names


def test_database_query_request_has_no_hidden_sql_or_limit_ceiling():
    sql = "SELECT 1 " + ("/* long */ " * 3000)

    request = ProjectDatabaseQueryRequest(path="data.sqlite", sql=sql, limit=5000)

    assert request.sql == sql
    assert request.limit == 5000


def test_conversation_message_list_limit_has_no_hidden_ceiling():
    parameter = signature(list_project_conversation_messages).parameters["limit"]

    assert "Ge(ge=1)" in repr(parameter.default.metadata)
    assert "Le(" not in repr(parameter.default.metadata)


def test_dashboard_page_sizes_have_no_hidden_ceiling():
    conversation_page_size = signature(read_conversation_data_view).parameters["page_size"]
    memory_page_size = signature(list_project_memory).parameters["page_size"]
    global_records_page_size = signature(list_global_memory_records).parameters["page_size"]
    global_events_page_size = signature(list_global_memory_events).parameters["page_size"]

    assert "Ge(ge=1)" in repr(conversation_page_size.default.metadata)
    assert "Le(" not in repr(conversation_page_size.default.metadata)
    assert "Ge(ge=1)" in repr(memory_page_size.default.metadata)
    assert "Le(" not in repr(memory_page_size.default.metadata)
    assert "Ge(ge=1)" in repr(global_records_page_size.default.metadata)
    assert "Le(" not in repr(global_records_page_size.default.metadata)
    assert "Ge(ge=1)" in repr(global_events_page_size.default.metadata)
    assert "Le(" not in repr(global_events_page_size.default.metadata)


def test_memory_dashboard_pages_keep_every_record_reachable(tmp_path):
    (tmp_path / "project").mkdir()
    repository = ProjectConversationMemoryRepository(
        FakeProjectRepository(str(tmp_path / "project")),
        global_memory_root=tmp_path / "runtime" / "memory",
    )
    repository.apply_memory_operations(
        compression_id="compression-many",
        project_id=PROJECT_ID,
        created_at="2026-01-01T00:00:00+00:00",
        global_operations=[],
        project_operations=[
            {
                "operation": "add",
                "content": f"记忆 {index}",
                "reason": "分页测试",
                "keywords": [],
            }
            for index in range(55)
        ],
    )
    service = ProjectMemoryManagementService(repository)

    first = service.list_memory_records(
        scope="project",
        project_id=PROJECT_ID,
        page=1,
        page_size=20,
    )
    last = service.list_memory_records(
        scope="project",
        project_id=PROJECT_ID,
        page=3,
        page_size=20,
    )

    assert first["total_count"] == 55
    assert first["total_pages"] == 3
    assert len(first["items"]) == 20
    assert len(last["items"]) == 15
    assert first["has_next"] is True
    assert last["has_previous"] is True


def test_negative_integer_metadata_is_not_silently_clamped_to_zero():
    assert _optional_int(-7) == -7
    assert _optional_int("-8") == -8
    assert _payload_int(-9) == -9
    assert _payload_int("-10") == -10
    assert _optional_int_or_none(-11) == -11
    assert _optional_int_or_none("-12") == -12


def test_session_and_generated_titles_are_not_truncated():
    title = "标题" * 100

    assert _normalize_session_title(title) == title
    assert extract_title(dumps({"title": title}, ensure_ascii=False)) == title


def test_provider_web_search_usage_is_not_silently_reclassified_as_main_chat():
    assert _normalize_usage_feature_key("provider_web_search") == "provider_web_search"
