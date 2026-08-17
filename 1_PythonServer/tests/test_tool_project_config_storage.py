from json import dumps, loads
from pathlib import Path

import pytest

from app.core.errors import BadRequestError, ConflictError
from app.infra.file_workspace import FileWorkspaceStorage
from app.infra.tools.tool_project_config_storage import ToolProjectConfigStorage
from app.infra.tools.tool_project_config_constants import (
    TOOL_FOLDER_MANIFEST_FILE,
)
from app.services.tools.tool_folder_files import ToolFolderFileService
from app.services.tools.tool_registry import ToolRegistryService
from tests.tool_project_test_support import ToolProjectFixture


def _service(storage: ToolProjectFixture) -> ToolFolderFileService:
    registry = ToolRegistryService(storage)
    registry.rebuild_registry()
    return ToolFolderFileService(
        ToolProjectConfigStorage(),
        FileWorkspaceStorage(),
        registry,
        storage,
    )


def test_tool_project_manifest_save_normalizes_content_and_syncs_project_name(tmp_path):
    storage = ToolProjectFixture(tmp_path / "tools")
    toolset = storage.create_toolset(name="基础工具")
    folder = storage.create_tool_folder(toolset.category_id, name="脚本工具")
    service = _service(storage)
    manifest_path = Path(folder.root_path) / TOOL_FOLDER_MANIFEST_FILE
    payload = loads(manifest_path.read_text(encoding="utf-8"))
    payload.update({
        "display_name": "脚本工具新版",
        "summary": "旧摘要",
        "ui": {"icon": "old"},
    })

    service.write_text_file(
        toolset.category_id,
        folder.project_id,
        TOOL_FOLDER_MANIFEST_FILE,
        "\ufeff" + dumps(payload, ensure_ascii=False),
    )

    saved = loads(manifest_path.read_text(encoding="utf-8"))
    assert saved["display_name"] == "脚本工具新版"
    assert storage.get_tool_folder(toolset.category_id, folder.project_id).name == "脚本工具新版"
    assert "summary" not in saved
    assert "ui" not in saved


def test_tool_project_manifest_rejects_placeholder_call_name(tmp_path):
    storage = ToolProjectFixture(tmp_path / "tools")
    toolset = storage.create_toolset(name="基础工具")
    folder = storage.create_tool_folder(toolset.category_id, name="脚本工具")
    service = _service(storage)

    with pytest.raises(BadRequestError):
        service.write_text_file(
            toolset.category_id,
            folder.project_id,
            TOOL_FOLDER_MANIFEST_FILE,
            dumps({"name": "tool_load_error", "display_name": "脚本工具"}),
        )


def test_tool_project_manifest_rejects_missing_parallel_declaration(tmp_path):
    storage = ToolProjectFixture(tmp_path / "tools")
    toolset = storage.create_toolset(name="基础工具")
    folder = storage.create_tool_folder(toolset.category_id, name="脚本工具")
    service = _service(storage)
    manifest_path = Path(folder.root_path) / TOOL_FOLDER_MANIFEST_FILE
    payload = loads(manifest_path.read_text(encoding="utf-8"))
    payload.pop("execution")

    with pytest.raises(BadRequestError, match="execution.parallel"):
        service.write_text_file(
            toolset.category_id,
            folder.project_id,
            TOOL_FOLDER_MANIFEST_FILE,
            dumps(payload, ensure_ascii=False),
        )


def test_tool_project_manifest_rejects_duplicate_identity(tmp_path):
    storage = ToolProjectFixture(tmp_path / "tools")
    toolset = storage.create_toolset(name="基础工具")
    existing = storage.create_tool_folder(toolset.category_id, name="已有工具")
    editing = storage.create_tool_folder(toolset.category_id, name="待修改工具")
    service = _service(storage)
    existing_manifest = loads(
        (Path(existing.root_path) / TOOL_FOLDER_MANIFEST_FILE).read_text(encoding="utf-8")
    )
    editing_manifest_path = Path(editing.root_path) / TOOL_FOLDER_MANIFEST_FILE
    payload = loads(editing_manifest_path.read_text(encoding="utf-8"))
    payload["name"] = existing_manifest["name"]

    with pytest.raises(ConflictError):
        service.write_text_file(
            toolset.category_id,
            editing.project_id,
            TOOL_FOLDER_MANIFEST_FILE,
            dumps(payload, ensure_ascii=False),
        )
