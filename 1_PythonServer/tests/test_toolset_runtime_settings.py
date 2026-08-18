from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.errors import BadRequestError
from app.infra.tools.tool_project_config_constants import TOOL_FOLDER_MANIFEST_FILE
from app.services.tools.toolsets import ToolsetService
from tests.tool_project_test_support import ToolProjectFixture


class _RegistrySpy:
    def __init__(self) -> None:
        self.rebuild_count = 0

    def rebuild_registry(self) -> None:
        self.rebuild_count += 1


def test_runtime_settings_patch_updates_all_card_switches(tmp_path: Path) -> None:
    projects = ToolProjectFixture(tmp_path)
    toolset = projects.create_toolset(name="基础工具")
    folder = projects.create_tool_folder(toolset.category_id, name="测试工具")
    registry = _RegistrySpy()
    service = ToolsetService(projects, registry)  # type: ignore[arg-type]

    result = service.set_tool_folder_runtime_settings(
        toolset.category_id,
        folder.project_id,
        enabled=False,
        dynamic=False,
        parallel=False,
    )

    manifest = json.loads(
        (Path(folder.root_path) / TOOL_FOLDER_MANIFEST_FILE).read_text(encoding="utf-8")
    )
    assert manifest["state"]["enabled"] is False
    assert manifest["loading"]["dynamic"] is False
    assert manifest["execution"]["parallel"] is False
    assert result.enabled is False
    assert result.dynamic is False
    assert result.parallel is False
    assert registry.rebuild_count == 1


def test_runtime_settings_patch_preserves_unspecified_switches(tmp_path: Path) -> None:
    projects = ToolProjectFixture(tmp_path)
    toolset = projects.create_toolset(name="基础工具")
    folder = projects.create_tool_folder(toolset.category_id, name="测试工具")
    service = ToolsetService(projects)

    result = service.set_tool_folder_runtime_settings(
        toolset.category_id,
        folder.project_id,
        enabled=False,
        dynamic=None,
        parallel=None,
    )

    assert result.enabled is False
    assert result.dynamic is True
    assert result.parallel is True


def test_runtime_settings_patch_rejects_empty_update(tmp_path: Path) -> None:
    projects = ToolProjectFixture(tmp_path)
    toolset = projects.create_toolset(name="基础工具")
    folder = projects.create_tool_folder(toolset.category_id, name="测试工具")
    service = ToolsetService(projects)

    with pytest.raises(BadRequestError, match="至少需要修改一项"):
        service.set_tool_folder_runtime_settings(
            toolset.category_id,
            folder.project_id,
            enabled=None,
            dynamic=None,
            parallel=None,
        )
