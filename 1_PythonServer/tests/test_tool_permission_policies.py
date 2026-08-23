from json import dumps, loads

from app.domain.tools.permission_policies import build_default_tool_permission_policy
from app.infra.tools.tool_project_config_constants import TOOL_PERMISSIONS_FILE
from app.services.application.tool_market import _move_local_tool_state


def test_default_tool_permission_policy_is_risk_based():
    policy = build_default_tool_permission_policy()

    assert policy["fallback"] == "ask"
    assert policy["policies"]["filesystem_read"] == {
        "workspace_inside": "allow",
        "workspace_outside": "allow",
        "unresolved": "allow",
    }
    assert policy["policies"]["filesystem_write"] == {
        "workspace_inside": "allow",
        "workspace_outside": "ask",
        "unresolved": "ask",
    }
    assert policy["policies"]["filesystem_delete"] == {
        "workspace_inside": "ask",
        "workspace_outside": "deny",
        "unresolved": "deny",
    }
    assert policy["policies"]["external_data_read"] == {"all": "allow"}
    assert policy["policies"]["external_data_modify"] == {"all": "ask"}
    assert policy["policies"]["unknown"] == {"all": "ask"}


def test_tool_market_update_preserves_local_permission_policy(tmp_path):
    current_root = tmp_path / "current"
    update_root = tmp_path / "update"
    current_path = current_root / TOOL_PERMISSIONS_FILE
    update_path = update_root / TOOL_PERMISSIONS_FILE
    current_path.parent.mkdir(parents=True)
    update_path.parent.mkdir(parents=True)

    current_policy = build_default_tool_permission_policy()
    current_policy["policies"]["filesystem_read"]["workspace_inside"] = "allow"
    current_path.write_text(dumps(current_policy), encoding="utf-8")
    update_path.write_text(dumps(build_default_tool_permission_policy()), encoding="utf-8")

    _move_local_tool_state(current_root, update_root)

    saved = loads(update_path.read_text(encoding="utf-8"))
    assert saved["policies"]["filesystem_read"]["workspace_inside"] == "allow"
    assert not current_path.exists()
