import pytest

from app.services.tools.tool_dependency_requirements import (
    parse_requirements_file,
    resolve_dependency_status,
    select_install_targets,
)


@pytest.mark.parametrize("specifier,version,expected", [
    ("~=1.4", "1.9", "installed"),
    ("~=1.4", "2.0", "version_mismatch"),
    ("~=1.4.2", "1.4.9", "installed"),
    ("~=1.4.2", "1.5", "version_mismatch"),
    (">=1.0", "1.0rc1", "version_mismatch"),
    (">=1.0rc1,<2", "1.0rc2", "installed"),
    ("==1.0", "1.0.dev1", "version_mismatch"),
    (">1.0", "1.0.post1", "version_mismatch"),
    (">=1.0", "1.0.post1", "installed"),
    ("==1.4.*", "1.4.3", "installed"),
    ("!=1.4.*", "1.4.3", "version_mismatch"),
    ("==1.0", "1.0+local", "installed"),
    (">=1!1.0", "2.0", "version_mismatch"),
    (">=1.0", "garbage", "version_mismatch"),
])
def test_version_status_and_install_selection_follow_packaging(tmp_path, specifier, version, expected):
    path = tmp_path / "requirements.txt"
    path.write_text(f"demo{specifier}\n", encoding="utf-8")
    requirement, = parse_requirements_file(path)
    status = resolve_dependency_status(requirement, {"demo": version})
    assert status.status == expected
    assert bool(select_install_targets((status,), requirement=None)) == (expected != "installed")
    assert bool(select_install_targets((status,), requirement="demo")) == (expected != "installed")


@pytest.mark.parametrize("specifier", ["~=1", ">=banana", ">=1.*", "==", "=>1.0"])
def test_invalid_specifier_is_reported_before_install(tmp_path, specifier):
    path = tmp_path / "requirements.txt"
    path.write_text(f"demo{specifier}\n", encoding="utf-8")
    requirement, = parse_requirements_file(path)
    assert resolve_dependency_status(requirement, {}).status == "invalid"
