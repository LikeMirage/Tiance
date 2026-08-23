from json import dumps, loads
from pathlib import Path

import pytest

from app.core.errors import BadRequestError, ConflictError
from app.infra.file_workspace import FileWorkspaceStorage
from app.infra.tools.tool_project_config_storage import ToolProjectConfigStorage
from app.infra.tools.tool_project_config_constants import (
    TOOL_FOLDER_MANIFEST_FILE,
    TOOL_INPUT_SCHEMA_FILE,
    TOOL_PERMISSIONS_FILE,
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


def test_tool_project_manifest_save_keeps_registration_and_project_names_independent(tmp_path):
    storage = ToolProjectFixture(tmp_path / "tools")
    toolset = storage.create_toolset(name="基础工具")
    folder = storage.create_tool_folder(toolset.category_id, name="脚本工具")
    service = _service(storage)
    manifest_path = Path(folder.root_path) / TOOL_FOLDER_MANIFEST_FILE
    payload = loads(manifest_path.read_text(encoding="utf-8"))
    payload.update({
        "registration_name": "脚本工具发布名",
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
    assert saved["registration_name"] == "脚本工具发布名"
    assert storage.get_tool_folder(toolset.category_id, folder.project_id).name == "脚本工具"
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
            dumps({"name": "tool_load_error", "registration_name": "脚本工具"}),
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


def test_input_schema_save_preserves_valid_parameter_permission_type():
    storage = ToolProjectConfigStorage()
    content = storage.normalize_standard_file_content(
        TOOL_INPUT_SCHEMA_FILE,
        dumps({
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "permission_type": "filesystem_read",
                },
                "encoding": {"type": "string"},
            },
            "required": ["file_path"],
        }),
    )

    saved = loads(content)
    assert saved["properties"]["file_path"]["permission_type"] == "filesystem_read"
    assert "permission_type" not in saved["properties"]["encoding"]


def test_input_schema_save_rejects_invalid_parameter_permission_type():
    storage = ToolProjectConfigStorage()

    with pytest.raises(BadRequestError, match="permission_type"):
        storage.normalize_standard_file_content(
            TOOL_INPUT_SCHEMA_FILE,
            dumps({
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "permission_type": "read_everything",
                    },
                },
                "required": [],
            }),
        )


def test_permissions_save_completes_missing_policy_cells():
    storage = ToolProjectConfigStorage()
    content = storage.normalize_standard_file_content(
        TOOL_PERMISSIONS_FILE,
        dumps({
            "version": 1,
            "fallback": "ask",
            "policies": {
                "filesystem_read": {"workspace_inside": "allow"},
            },
        }),
    )

    saved = loads(content)
    assert saved["policies"]["filesystem_read"] == {
        "workspace_inside": "allow",
        "workspace_outside": "ask",
        "unresolved": "ask",
    }
    assert saved["policies"]["network_access"]["public_network"] == "ask"
    assert saved["policies"]["unknown"] == {"all": "ask"}


def test_permissions_save_rejects_invalid_decision():
    storage = ToolProjectConfigStorage()

    with pytest.raises(BadRequestError, match="deny、ask 或 allow"):
        storage.normalize_standard_file_content(
            TOOL_PERMISSIONS_FILE,
            dumps({
                "version": 1,
                "fallback": "sometimes",
                "policies": {},
            }),
        )
