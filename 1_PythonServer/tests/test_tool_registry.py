from json import dumps, loads
from pathlib import Path

import pytest
from watchfiles import Change

from app.core.errors import BadRequestError
from app.infra.tools.tool_project_config_constants import (
    TOOL_EXAMPLES_FILE,
    TOOL_FOLDER_MANIFEST_FILE,
    TOOL_INPUT_SCHEMA_FILE,
    TOOL_OUTPUT_SCHEMA_FILE,
)
from app.services.tools.catalog import ToolCatalogService
from app.services.tools.tool_metadata_watcher import tool_metadata_change_paths
from app.services.tools.tool_registry import ToolRegistryService
from tests.tool_project_test_support import ToolProjectFixture


def test_tool_registry_rebuild_populates_searchable_memory_index(tmp_path):
    storage = ToolProjectFixture(tmp_path / "tools")
    toolset = storage.create_toolset(name="基础工具")
    folder = storage.create_tool_folder(toolset.category_id, name="文本读取")
    folder_root = Path(folder.root_path)

    manifest_path = folder_root / TOOL_FOLDER_MANIFEST_FILE
    manifest = loads(manifest_path.read_text(encoding="utf-8"))
    manifest.update(
        {
            "name": "read_text_file",
            "display_name": "文本读取",
            "description": "读取本地纯文本文件。",
            "keywords": ["文本", "源码"],
            "execution": {"parallel": True},
            "state": {"enabled": True},
        }
    )
    manifest_path.write_text(dumps(manifest, ensure_ascii=False), encoding="utf-8")
    (folder_root / TOOL_INPUT_SCHEMA_FILE).write_text(
        dumps(
            {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "mode": {"type": "string"},
                },
                "required": ["file_path"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (folder_root / TOOL_EXAMPLES_FILE).write_text(
        dumps(
            [
                {
                    "title": "查看文件元信息",
                    "content": "先确认文件大小。",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (folder_root / TOOL_OUTPUT_SCHEMA_FILE).write_text(
        dumps({"type": "object", "properties": {"content": {"type": "string"}}}, ensure_ascii=False),
        encoding="utf-8",
    )

    service = ToolRegistryService(storage)

    entries = service.rebuild_registry()

    assert len(entries) == 1
    entry = service.get_enabled_entry("read_text_file")
    assert entry is not None
    assert entry.project_id == folder.project_id
    assert entry.category_name == "基础工具"
    assert entry.parallel is True
    assert entry.parameter_names == ("file_path", "mode")
    assert entry.example_titles == ("查看文件元信息",)
    assert entry.full_injection_char_count > 0
    assert entry.dynamic_injection_char_count > 0
    metadata = service.get_enabled_metadata("read_text_file")
    assert metadata is not None
    assert metadata.input_schema["required"] == ["file_path"]
    assert metadata.output_schema["properties"]["content"]["type"] == "string"
    assert metadata.examples[0][1]["content"] == "先确认文件大小。"
    assert service.search_entries("源码")[0].tool_name == "read_text_file"


def test_tool_catalog_can_read_summaries_from_registry(tmp_path):
    storage = ToolProjectFixture(tmp_path / "tools")
    toolset = storage.create_toolset(name="基础工具")
    folder = storage.create_tool_folder(toolset.category_id, name="文本读取")
    folder_root = Path(folder.root_path)
    manifest_path = folder_root / TOOL_FOLDER_MANIFEST_FILE
    manifest = loads(manifest_path.read_text(encoding="utf-8"))
    manifest.update(
        {
            "name": "read_text_file",
            "display_name": "文本读取",
            "description": "读取本地纯文本文件。",
            "keywords": ["文本"],
            "state": {"enabled": True},
        }
    )
    manifest_path.write_text(dumps(manifest, ensure_ascii=False), encoding="utf-8")

    registry = ToolRegistryService(storage)
    registry.rebuild_registry()
    catalog = ToolCatalogService(registry)

    summaries = catalog.list_tool_summaries()

    assert [summary.name for summary in summaries] == ["read_text_file"]
    assert summaries[0].display_name == "文本读取"
    assert summaries[0].parallel is True


def test_tool_registry_rejects_manifest_without_parallel_declaration(tmp_path):
    storage = ToolProjectFixture(tmp_path / "tools")
    toolset = storage.create_toolset(name="基础工具")
    folder = storage.create_tool_folder(toolset.category_id, name="文本读取")
    manifest_path = Path(folder.root_path) / TOOL_FOLDER_MANIFEST_FILE
    manifest = loads(manifest_path.read_text(encoding="utf-8"))
    manifest.pop("execution")
    manifest_path.write_text(dumps(manifest, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(BadRequestError, match="execution.parallel"):
        ToolRegistryService(storage).rebuild_registry()


def test_tool_registry_rebuild_raises_when_tool_files_are_incomplete(tmp_path):
    storage = ToolProjectFixture(tmp_path / "tools")
    toolset = storage.create_toolset(name="基础工具")
    folder = storage.create_tool_folder(toolset.category_id, name="文本读取")
    folder_root = Path(folder.root_path)
    manifest_path = folder_root / TOOL_FOLDER_MANIFEST_FILE
    manifest = loads(manifest_path.read_text(encoding="utf-8"))
    manifest.update(
        {
            "name": "read_text_file",
            "display_name": "文本读取",
            "description": "读取本地纯文本文件。",
            "state": {"enabled": True},
        }
    )
    manifest_path.write_text(dumps(manifest, ensure_ascii=False), encoding="utf-8")

    service = ToolRegistryService(storage)
    service.rebuild_registry()
    (folder_root / TOOL_INPUT_SCHEMA_FILE).unlink()

    with pytest.raises(FileNotFoundError):
        service.rebuild_registry()

    assert service.get_enabled_metadata("read_text_file") is not None


def test_tool_metadata_change_paths_only_include_standard_metadata_files(tmp_path):
    root = tmp_path / "tools"
    changes = {
        (
            Change.modified,
            str(root / "tool-project" / ".tool" / "tool.json"),
        ),
        (
            Change.modified,
            str(root / "tool-project" / ".tool" / "examples.json"),
        ),
        (
            Change.modified,
            str(root / "tool-project" / "program" / "main.py"),
        ),
    }

    paths = tool_metadata_change_paths(root, changes)

    assert paths == (
        "tool-project/.tool/examples.json",
        "tool-project/.tool/tool.json",
    )
