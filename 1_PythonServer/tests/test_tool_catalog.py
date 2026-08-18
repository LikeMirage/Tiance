from json import dumps, loads
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.api.routes.tools import catalog as catalog_routes
from app.core.errors import BadRequestError, NotFoundError
from app.infra.tools.tool_project_config_constants import (
    TOOL_EXAMPLES_FILE,
    TOOL_FOLDER_MANIFEST_FILE,
    TOOL_INPUT_SCHEMA_FILE,
)
from app.services.tools.catalog import ToolCatalogService
from app.services.tools.tool_registry import ToolRegistryService
from tests.tool_project_test_support import ToolProjectFixture


def _create_catalog_tool(
    storage: ToolProjectFixture,
    *,
    category_name: str = "基础工具",
    folder_name: str = "文本读取",
    call_name: str = "read_text_file",
    enabled: bool = True,
    parallel: bool = True,
):
    toolset = storage.create_toolset(name=category_name)
    folder = storage.create_tool_folder(toolset.category_id, name=folder_name)
    folder_root = Path(folder.root_path)

    manifest_path = folder_root / TOOL_FOLDER_MANIFEST_FILE
    manifest = loads(manifest_path.read_text(encoding="utf-8"))
    manifest.update(
        {
            "name": call_name,
            "registration_name": folder_name,
            "description": "读取本地纯文本文件，支持元信息、按行读取和关键词搜索。",
            "keywords": ["文本", "读取", "源码"],
            "loading": {
                "dynamic": True,
            },
            "execution": {
                "parallel": parallel,
            },
            "state": {
                "enabled": enabled,
            },
        }
    )
    manifest_path.write_text(dumps(manifest, ensure_ascii=False), encoding="utf-8")

    input_schema = {
        "type": "object",
        "description": "mode=search 时必须填写 query。",
        "required": ["file_path"],
        "additionalProperties": False,
        "properties": {
            "file_path": {"type": "string", "description": "文件路径。"},
            "mode": {
                "type": "string",
                "enum": ["metadata", "lines", "search", "full"],
                "default": "metadata",
            },
            "query": {"type": "string", "description": "搜索关键词。"},
        },
    }
    (folder_root / TOOL_INPUT_SCHEMA_FILE).write_text(
        dumps(input_schema, ensure_ascii=False),
        encoding="utf-8",
    )

    examples = [
        {
            "title": "查看文件元信息",
            "content": (
                "先确认文件规模。\n\n"
                "输入参数：\n"
                '{"file_path":"C:/work/app.py","mode":"metadata"}\n\n'
                "预期返回：\n"
                '{"ok":true,"mode":"metadata"}'
            ),
        },
        {
            "title": "搜索关键词",
            "content": (
                "定位包含关键词的行。\n\n"
                "输入参数：\n"
                '{"file_path":"C:/work/app.py","mode":"search","query":"error"}\n\n'
                "预期返回：\n"
                '{"ok":true,"mode":"search","matches":[]}'
            ),
        },
    ]
    (folder_root / TOOL_EXAMPLES_FILE).write_text(
        dumps(examples, ensure_ascii=False),
        encoding="utf-8",
    )
    return toolset, folder


def _build_catalog_service(storage: ToolProjectFixture) -> ToolCatalogService:
    registry = ToolRegistryService(storage)
    registry.rebuild_registry()
    return ToolCatalogService(registry)


def test_tool_catalog_lists_lightweight_summaries_for_enabled_tools(tmp_path):
    storage = ToolProjectFixture(tmp_path / "tools")
    _create_catalog_tool(storage)
    _create_catalog_tool(
        storage,
        category_name="隐藏工具",
        folder_name="禁用工具",
        call_name="disabled_tool",
        enabled=False,
    )
    service = _build_catalog_service(storage)

    summaries = service.list_tool_summaries()

    assert len(summaries) == 1
    summary = summaries[0]
    assert summary.name == "read_text_file"
    assert summary.display_name == "文本读取"
    assert summary.category == "基础工具"
    assert summary.dynamic is True
    assert summary.parallel is True
    assert summary.keywords == ("文本", "读取", "源码")
    assert summary.parameter_names == ("file_path", "mode", "query")
    assert summary.example_titles == ("查看文件元信息", "搜索关键词")


def test_tool_catalog_reads_split_metadata_with_utf8_bom(tmp_path):
    storage = ToolProjectFixture(tmp_path / "tools")
    _toolset, folder = _create_catalog_tool(storage)
    folder_root = Path(folder.root_path)

    for relative_path in (
        TOOL_FOLDER_MANIFEST_FILE,
        TOOL_INPUT_SCHEMA_FILE,
        TOOL_EXAMPLES_FILE,
    ):
        file_path = folder_root / relative_path
        file_path.write_text(
            file_path.read_text(encoding="utf-8"),
            encoding="utf-8-sig",
        )

    service = _build_catalog_service(storage)

    summaries = service.list_tool_summaries()

    assert [summary.name for summary in summaries] == ["read_text_file"]
    assert summaries[0].parameter_names == ("file_path", "mode", "query")
    assert summaries[0].example_titles == ("查看文件元信息", "搜索关键词")


def test_tool_catalog_reads_parameter_detail_without_examples(tmp_path):
    storage = ToolProjectFixture(tmp_path / "tools")
    _create_catalog_tool(storage)
    service = _build_catalog_service(storage)

    detail = service.get_tool_parameters("read_text_file")

    assert detail.name == "read_text_file"
    assert detail.input_schema["required"] == ["file_path"]
    assert list(detail.input_schema["properties"].keys()) == [
        "file_path",
        "mode",
        "query",
    ]


def test_tool_catalog_lists_example_titles_without_payloads(tmp_path):
    storage = ToolProjectFixture(tmp_path / "tools")
    _create_catalog_tool(storage)
    service = _build_catalog_service(storage)

    summaries = service.list_tool_example_summaries("read_text_file")

    assert [(item.index, item.title) for item in summaries] == [
        (1, "查看文件元信息"),
        (2, "搜索关键词"),
    ]


def test_tool_catalog_reads_selected_examples_by_index_and_title(tmp_path):
    storage = ToolProjectFixture(tmp_path / "tools")
    _create_catalog_tool(storage)
    service = _build_catalog_service(storage)

    examples = service.get_tool_examples(
        "read_text_file",
        indexes=(2,),
        titles=("查看文件元信息",),
    )

    assert [example.title for example in examples] == ["搜索关键词", "查看文件元信息"]
    assert "mode\":\"search" in examples[0].content
    assert "mode\":\"metadata" in examples[1].content


def test_tool_catalog_reads_all_examples(tmp_path):
    storage = ToolProjectFixture(tmp_path / "tools")
    _create_catalog_tool(storage)
    service = _build_catalog_service(storage)

    examples = service.get_tool_examples("read_text_file", include_all=True)

    assert [example.index for example in examples] == [1, 2]


def test_tool_catalog_rejects_empty_example_query(tmp_path):
    storage = ToolProjectFixture(tmp_path / "tools")
    _create_catalog_tool(storage)
    service = _build_catalog_service(storage)

    with pytest.raises(BadRequestError):
        service.get_tool_examples("read_text_file")


def test_tool_catalog_unknown_tool_raises_not_found(tmp_path):
    storage = ToolProjectFixture(tmp_path / "tools")
    _create_catalog_tool(storage)
    service = _build_catalog_service(storage)

    with pytest.raises(NotFoundError):
        service.get_tool_parameters("missing_tool")


def test_tool_catalog_reports_closed_tool_when_manifest_is_disabled(tmp_path):
    storage = ToolProjectFixture(tmp_path / "tools")
    _create_catalog_tool(storage, enabled=False)
    service = _build_catalog_service(storage)

    with pytest.raises(NotFoundError) as exc:
        service.get_tool_parameters("read_text_file")

    assert exc.value.message == "此工具已关闭。"


def test_tool_catalog_route_session_context_rejects_disabled_session_tool(monkeypatch):
    fake_session = SimpleNamespace(
        settings=SimpleNamespace(
            tools_enabled=True,
            enabled_tool_names=("allowed_tool",),
        ),
    )
    fake_service = SimpleNamespace(
        get_session=lambda project_id, session_id: fake_session,
    )
    monkeypatch.setattr(
        catalog_routes,
        "get_project_conversation_service",
        lambda: fake_service,
    )

    with pytest.raises(NotFoundError) as exc:
        catalog_routes._assert_session_tool_allowed(
            "read_text_file",
            project_id="project-1",
            session_id="session-1",
        )

    assert exc.value.message == "此工具已关闭。"


def test_tool_catalog_route_session_context_allows_enabled_session_tool(monkeypatch):
    fake_session = SimpleNamespace(
        settings=SimpleNamespace(
            tools_enabled=True,
            enabled_tool_names=("read_text_file",),
        ),
    )
    fake_service = SimpleNamespace(
        get_session=lambda project_id, session_id: fake_session,
    )
    monkeypatch.setattr(
        catalog_routes,
        "get_project_conversation_service",
        lambda: fake_service,
    )

    catalog_routes._assert_session_tool_allowed(
        "read_text_file",
        project_id="project-1",
        session_id="session-1",
    )


def test_tool_catalog_route_rejects_tool_when_session_master_switch_is_off(monkeypatch):
    fake_session = SimpleNamespace(
        settings=SimpleNamespace(
            tools_enabled=False,
            enabled_tool_names=None,
        ),
    )
    fake_service = SimpleNamespace(
        get_session=lambda project_id, session_id: fake_session,
    )
    monkeypatch.setattr(
        catalog_routes,
        "get_project_conversation_service",
        lambda: fake_service,
    )

    with pytest.raises(NotFoundError) as exc:
        catalog_routes._assert_session_tool_allowed(
            "read_text_file",
            project_id="project-1",
            session_id="session-1",
        )

    assert exc.value.message == "会话工具总开关已关闭。"
