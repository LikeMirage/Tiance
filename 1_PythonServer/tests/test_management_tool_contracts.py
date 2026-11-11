import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.domain.project import ProjectKind
from app.infra.tools.tool_project_config_storage import ToolProjectConfigStorage
from app.services.tools.tool_execution_arguments import validate_tool_arguments
from app.services.tools.tool_metadata import load_tool
from tests.test_collection_scaffold import workspace


ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "Data/tools"
TOOL = TOOLS / "34b16133-f310-4064-b71f-f0411d13ab1d"
ROLE = TOOLS / "030b5552-6e0c-5a24-b200-6a626038ce9e"
THEME = TOOLS / "a737ec05-d224-5299-8e37-abfdb14f4d27"


@pytest.mark.parametrize("root", [TOOL, ROLE, THEME])
def test_management_metadata_normalizes_without_loss_and_init_is_declared(root):
    loaded = load_tool(str(root))
    assert "根目录" in loaded.manifest["description"]
    assert not validate_tool_arguments({"action": "initialize_current"}, loaded.input_schema)
    storage = ToolProjectConfigStorage()
    for path in (root / ".tool").glob("*.json"):
        raw = path.read_text("utf-8")
        assert json.loads(storage.normalize_standard_file_content(f".tool/{path.name}", raw)) == json.loads(raw), path


@pytest.mark.parametrize("root,action", [(TOOL, "create_tool"), (ROLE, "create_role")])
def test_manager_action_contract_rejects_wrong_or_missing_targets(root, action):
    schema = load_tool(str(root)).input_schema
    for args in [
        {"action": "initialize_current", "project_id": "elsewhere"},
        {"action": "delete", "project_id": "target"},
        {"action": "delete", "project_id": "target", "confirm": False},
        {"action": action, "name": "no category"},
    ]:
        assert validate_tool_arguments(args, schema)
    assert not validate_tool_arguments({"action": "delete", "project_id": "target", "confirm": True}, schema)


def theme_actions():
    spec = importlib.util.spec_from_file_location("test_theme_workspace_actions", THEME / "program/workspace_actions.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_theme_init_uses_caller_context_preserves_custom_theme_and_never_switches(workspace, monkeypatch):
    root, project, category, roots = workspace
    # Shared fixture's file writer targets root; place it under the theme root.
    from app.services.application import project_scaffold
    monkeypatch.setattr(project_scaffold, "get_settings", lambda: SimpleNamespace(
        tools_data_path=roots["roles"], roles_data_path=roots["roles"], themes_data_path=root.parent))
    project.project_kind = category.category_kind = ProjectKind.THEME
    project.name = "Theme"
    monkeypatch.setenv("TIANCE_PROJECT_ID", project.project_id)
    monkeypatch.setenv("TIANCE_WORKSPACE_ROOT", str(root))
    actions = theme_actions()
    result = actions.initialize_current_theme(THEME)
    assert result["activated"] is False
    assert result["written_files"] == ["theme.json", "docs/theme-development/README.md"]
    theme = json.loads((root / "theme.json").read_text("utf-8"))
    assert theme["id"] == root.name
    theme["registrationName"] = "user design"
    (root / "theme.json").write_text(json.dumps(theme), encoding="utf-8")
    assert actions.initialize_current_theme(THEME)["written_files"] == []
    assert json.loads((root / "theme.json").read_text("utf-8"))["registrationName"] == "user design"
    monkeypatch.delenv("TIANCE_PROJECT_ID")
    with pytest.raises(ValueError, match="上下文"):
        actions.initialize_current_theme(THEME)


def test_theme_delete_uses_project_lifecycle_and_blocks_caller(monkeypatch, tmp_path):
    actions = theme_actions()
    target = SimpleNamespace(project_id="theme-project", project_kind=ProjectKind.THEME, root_path=str(tmp_path))
    events = []
    monkeypatch.setattr(actions, "get_project_service", lambda: SimpleNamespace(
        list_projects=lambda: [target], delete_project=lambda project_id: events.append(("delete", project_id))))
    monkeypatch.setattr(actions, "ensure_theme_project_can_be_deleted", lambda project: events.append(("policy", project.project_id)))
    monkeypatch.setenv("TIANCE_PROJECT_ID", "other-project")
    assert actions.delete_theme_project(tmp_path) == "theme-project"
    assert events == [("policy", "theme-project"), ("delete", "theme-project")]
    monkeypatch.setenv("TIANCE_PROJECT_ID", "theme-project")
    with pytest.raises(ValueError, match="不能删除"):
        actions.delete_theme_project(tmp_path)
    assert len(events) == 2
