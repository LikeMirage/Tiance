from __future__ import annotations

from contextlib import contextmanager
from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path
import shutil
import sys
from types import ModuleType, SimpleNamespace

from tests.formal_tool_paths import resolve_formal_tool_root


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_REPLACE_TEXT = resolve_formal_tool_root("replace_text")
_SAFE_PATCH = resolve_formal_tool_root("safe_patch")
_READ_MANY_FILES = resolve_formal_tool_root("read_many_files")
_FIND_PROJECT_FILES = resolve_formal_tool_root("find_project_files")
_TOOL_HEALTH_CHECK = resolve_formal_tool_root("tool_health_check")
_THEME_DESIGNER = resolve_formal_tool_root("theme_designer")
_RUN_PYTHON_SCRIPT = resolve_formal_tool_root("run_python_script")
_INTERACT_AI_CONVERSATION = resolve_formal_tool_root(
    "interact_ai_conversation"
)


def test_replace_text_keeps_original_when_atomic_commit_fails(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_tool("replace_text", _REPLACE_TEXT)
    source = tmp_path / "source.txt"
    source.write_bytes(b"before\n")
    monkeypatch.setenv("TIANCE_WORKSPACE_ROOT", str(tmp_path))
    atomic_os = module.replace_bytes_atomically.__globals__["os"]
    monkeypatch.setattr(
        atomic_os,
        "replace",
        lambda *_args: (_ for _ in ()).throw(OSError("simulated failure")),
    )

    result = module.run(
        {
            "file_path": "source.txt",
            "old_text": "before",
            "new_text": "after",
            "backup": True,
        }
    )

    assert result["ok"] is False
    assert result["error_info"]["code"] == "WRITE_FAILED"
    assert source.read_bytes() == b"before\n"
    assert not list(tmp_path.glob(".source.txt.*.tmp"))
    assert not list(tmp_path.glob("source.txt.*.bak"))


def test_replace_text_detects_change_between_read_and_commit(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_tool("replace_text_conflict", _REPLACE_TEXT)
    source = tmp_path / "source.txt"
    source.write_text("before\n", encoding="utf-8")
    monkeypatch.setenv("TIANCE_WORKSPACE_ROOT", str(tmp_path))
    require_unchanged = module.replace_bytes_atomically.__globals__["_require_unchanged"]
    calls = 0

    def change_before_check(path: Path, expected: bytes) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            path.write_text("external\n", encoding="utf-8")
        require_unchanged(path, expected)

    module.replace_bytes_atomically.__globals__["_require_unchanged"] = change_before_check
    try:
        result = module.run(
            {
                "file_path": "source.txt",
                "old_text": "before",
                "new_text": "after",
            }
        )
    finally:
        module.replace_bytes_atomically.__globals__["_require_unchanged"] = require_unchanged

    assert result["ok"] is False
    assert result["error_info"]["code"] == "WRITE_CONFLICT"
    assert source.read_text(encoding="utf-8") == "external\n"


def test_replace_text_rejects_unencodable_replacement_without_writing(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_tool("replace_text_encoding", _REPLACE_TEXT)
    source = tmp_path / "source.txt"
    original = "旧值\r\n".encode("gbk")
    source.write_bytes(original)
    monkeypatch.setenv("TIANCE_WORKSPACE_ROOT", str(tmp_path))

    result = module.run(
        {
            "file_path": "source.txt",
            "old_text": "旧值",
            "new_text": "🚀",
            "encoding": "gbk",
        }
    )

    assert result["ok"] is False
    assert result["error_info"]["code"] == "ENCODING_ERROR"
    assert source.read_bytes() == original


def test_safe_patch_preserves_utf8_bom_and_crlf(monkeypatch, tmp_path: Path) -> None:
    module = _load_tool("safe_patch_bom", _SAFE_PATCH)
    source = tmp_path / "source.txt"
    source.write_bytes(b"\xef\xbb\xbfalpha\r\nbeta\r\n")
    monkeypatch.setenv("TIANCE_WORKSPACE_ROOT", str(tmp_path))

    result = module.run(
        {
            "patch_text": (
                "--- a/source.txt\n"
                "+++ b/source.txt\n"
                "@@ -1,2 +1,2 @@\n"
                " alpha\n"
                "-beta\n"
                "+gamma\n"
            )
        }
    )

    assert result["ok"] is True
    assert source.read_bytes() == b"\xef\xbb\xbfalpha\r\ngamma\r\n"


def test_safe_patch_supports_explicit_gbk_without_reencoding(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_tool("safe_patch_gbk", _SAFE_PATCH)
    source = tmp_path / "source.txt"
    source.write_bytes("标题\r\n旧值\r\n".encode("gbk"))
    monkeypatch.setenv("TIANCE_WORKSPACE_ROOT", str(tmp_path))

    result = module.run(
        {
            "encoding": "gbk",
            "patch_text": (
                "--- a/source.txt\n"
                "+++ b/source.txt\n"
                "@@ -1,2 +1,2 @@\n"
                " 标题\n"
                "-旧值\n"
                "+新值\n"
            ),
        }
    )

    assert result["ok"] is True
    assert source.read_bytes().decode("gbk") == "标题\r\n新值\r\n"


def test_safe_patch_rejects_wrong_encoding_without_changing_file(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_tool("safe_patch_encoding_error", _SAFE_PATCH)
    source = tmp_path / "source.txt"
    original = "标题\r\n旧值\r\n".encode("gbk")
    source.write_bytes(original)
    monkeypatch.setenv("TIANCE_WORKSPACE_ROOT", str(tmp_path))

    result = module.run(
        {
            "patch_text": (
                "--- a/source.txt\n"
                "+++ b/source.txt\n"
                "@@ -1,2 +1,2 @@\n"
                " 标题\n"
                "-旧值\n"
                "+新值\n"
            )
        }
    )

    assert result["ok"] is False
    assert result["error_info"]["code"] == "ENCODING_ERROR"
    assert source.read_bytes() == original


def test_safe_patch_rejects_unencodable_patch_without_changing_file(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_tool("safe_patch_unencodable", _SAFE_PATCH)
    source = tmp_path / "source.txt"
    original = "旧值\r\n".encode("gbk")
    source.write_bytes(original)
    monkeypatch.setenv("TIANCE_WORKSPACE_ROOT", str(tmp_path))

    result = module.run(
        {
            "encoding": "gbk",
            "patch_text": (
                "--- a/source.txt\n"
                "+++ b/source.txt\n"
                "@@ -1 +1 @@\n"
                "-旧值\n"
                "+🚀\n"
            ),
        }
    )

    assert result["ok"] is False
    assert result["error_info"]["code"] == "ENCODING_ERROR"
    assert source.read_bytes() == original


def test_safe_patch_rolls_back_first_file_when_second_commit_fails(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_tool("safe_patch_rollback", _SAFE_PATCH)
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("first old\n", encoding="utf-8")
    second.write_text("second old\n", encoding="utf-8")
    monkeypatch.setenv("TIANCE_WORKSPACE_ROOT", str(tmp_path))
    transaction_module = sys.modules[module.apply_file_transaction.__module__]
    real_replace = transaction_module.os.replace
    failed = False

    def fail_second_once(source: object, destination: object) -> None:
        nonlocal failed
        if Path(destination) == second and not failed:
            failed = True
            raise OSError("simulated second-file failure")
        real_replace(source, destination)

    monkeypatch.setattr(transaction_module.os, "replace", fail_second_once)
    result = module.run(
        {
            "patch_text": (
                "--- a/first.txt\n"
                "+++ b/first.txt\n"
                "@@ -1 +1 @@\n"
                "-first old\n"
                "+first new\n"
                "--- a/second.txt\n"
                "+++ b/second.txt\n"
                "@@ -1 +1 @@\n"
                "-second old\n"
                "+second new\n"
            )
        }
    )

    assert result["ok"] is False
    assert result["error_info"]["code"] == "WRITE_FAILED"
    assert first.read_text(encoding="utf-8") == "first old\n"
    assert second.read_text(encoding="utf-8") == "second old\n"
    assert not list(tmp_path.glob(".*.tmp"))


def test_read_many_files_reports_each_truncation_reason(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_tool("read_many_reasons", _READ_MANY_FILES)
    source = tmp_path / "lines.txt"
    source.write_text("\n".join(f"line-{index:04d}" for index in range(300)), encoding="utf-8")
    monkeypatch.setenv("TIANCE_WORKSPACE_ROOT", str(tmp_path))

    result = module.run(
        {
            "files": [{"file_path": "lines.txt", "max_lines": 200}],
            "max_chars_per_file": 1000,
            "total_max_chars": 2000,
        }
    )

    item = result["data"]["files"][0]
    assert result["ok"] is True
    assert item["truncated"] is True
    assert item["truncation_reasons"] == ["line_limit", "file_char_limit"]
    assert item["selected_line_count"] == 200
    assert item["line_count"] < item["selected_line_count"]


def test_read_many_files_returns_budget_entries_for_every_unread_file(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_tool("read_many_budget", _READ_MANY_FILES)
    (tmp_path / "first.txt").write_text("a" * 800, encoding="utf-8")
    (tmp_path / "second.txt").write_text("b" * 500, encoding="utf-8")
    monkeypatch.setenv("TIANCE_WORKSPACE_ROOT", str(tmp_path))

    result = module.run(
        {
            "files": ["first.txt", "second.txt", "never-read.txt"],
            "total_max_chars": 1000,
        }
    )

    files = result["data"]["files"]
    assert len(files) == 3
    assert files[0]["truncation_reasons"] == []
    assert files[1]["truncation_reasons"] == ["total_char_limit"]
    assert files[2]["ok"] is False
    assert files[2]["requested_path"] == "never-read.txt"
    assert files[2]["error_info"]["code"] == "TOTAL_BUDGET_EXHAUSTED"


def test_read_many_files_rejects_removed_path_alias(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_tool("read_many_removed_path_alias", _READ_MANY_FILES)
    monkeypatch.setenv("TIANCE_WORKSPACE_ROOT", str(tmp_path))

    result = module.run({"files": [{"path": "old-contract.txt"}]})

    assert result["ok"] is False
    assert result["error_info"]["code"] == "INVALID_ARGUMENT"
    assert result["error_info"]["details"]["fields"] == ["path"]


def test_find_project_files_uses_explicit_keywords(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_tool("find_project_files_keywords", _FIND_PROJECT_FILES)
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    (source_dir / "auth_service.py").write_text(
        "# 登录鉴权\nasync def login():\n    return '/auth/login'\n",
        encoding="utf-8",
    )
    (source_dir / "format_date.py").write_text(
        "def format_date(value):\n    return str(value)\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("TIANCE_WORKSPACE_ROOT", str(tmp_path))

    result = module.run(
        {
            "keywords": ["登录", "auth"],
            "include_git_status": False,
        }
    )

    assert result["ok"] is True
    assert result["data"]["keywords"] == ["登录", "auth"]
    assert "task" not in result["data"]
    assert "terms" not in result["data"]
    assert [item["path"] for item in result["data"]["selected_files"]] == [
        "src/auth_service.py"
    ]
    assert "Keywords: 登录, auth" in result["data"]["context_pack"]
    assert "format_date.py" not in result["data"]["context_pack"].split(
        "## Relevant Files",
        maxsplit=1,
    )[1]


def test_find_project_files_rejects_removed_task_contract(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_tool("find_project_files_removed_task", _FIND_PROJECT_FILES)
    monkeypatch.setenv("TIANCE_WORKSPACE_ROOT", str(tmp_path))

    result = module.run({"task": "登录 鉴权"})

    assert result["ok"] is False
    assert result["error_info"]["code"] == "INVALID_ARGUMENT"
    assert result["error_info"]["message"] == "keywords 必须是非空字符串数组。"


def test_updated_tool_schemas_describe_new_contracts() -> None:
    safe_patch_input = _read_json(_SAFE_PATCH / ".tool" / "input.schema.json")
    read_many_input = _read_json(_READ_MANY_FILES / ".tool" / "input.schema.json")
    read_many_output = _read_json(_READ_MANY_FILES / ".tool" / "output.schema.json")
    find_project_files_input = _read_json(
        _FIND_PROJECT_FILES / ".tool" / "input.schema.json"
    )
    find_project_files_output = _read_json(
        _FIND_PROJECT_FILES / ".tool" / "output.schema.json"
    )

    assert safe_patch_input["properties"]["encoding"]["default"] == "utf-8"
    read_many_object = read_many_input["properties"]["files"]["items"]["oneOf"][1]
    assert read_many_object["required"] == ["file_path"]
    assert "path" not in read_many_object["properties"]
    success_item = read_many_output["properties"]["data"]["properties"]["files"][
        "items"
    ]["oneOf"][0]
    reasons = success_item["properties"]["truncation_reasons"]["items"]["enum"]
    assert reasons == ["line_limit", "file_char_limit", "total_char_limit"]
    assert find_project_files_input["required"] == ["keywords"]
    assert "task" not in find_project_files_input["properties"]
    assert (
        find_project_files_input["properties"]["keywords"]["items"]["type"]
        == "string"
    )
    find_project_files_data = find_project_files_output["properties"]["data"]
    assert "keywords" in find_project_files_data["required"]
    assert "task" not in find_project_files_data["properties"]
    assert "terms" not in find_project_files_data["properties"]


def test_tool_health_check_uses_host_tools_root(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_tool("tool_health_check", _TOOL_HEALTH_CHECK)
    tools_root = tmp_path / "real-tools"
    tools_root.mkdir()
    monkeypatch.setenv("TIANCE_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("TIANCE_TOOLS_ROOT", str(tools_root))

    assert module.resolve_tools_root(None) == tools_root.resolve()


def test_theme_designer_current_and_list_results_are_compact(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_tool("theme_designer", _THEME_DESIGNER)
    themes_root = tmp_path / "themes"
    theme_package = themes_root / "midnight"
    theme_package.mkdir(parents=True)
    theme_path = theme_package / "theme.json"
    theme_path.write_text("{}", encoding="utf-8")
    payload = {
        "id": "midnight",
        "name": "午夜",
        "mode": "dark",
        "tokens": {
            "color": {
                "accent": {"base": "#ffaa00"},
                "surface": {"base": "#101010"},
                "text": {"primary": "#f5f5f5"},
            }
        },
    }
    repository = SimpleNamespace(get_active_theme_id=lambda: "midnight")
    monkeypatch.setattr(module, "get_settings", lambda: SimpleNamespace(themes_data_path=themes_root))
    monkeypatch.setattr(module, "get_theme_settings_repository", lambda: repository)
    monkeypatch.setattr(module, "read_theme_payload", lambda *_args, **_kwargs: payload)

    current = module.run({"action": "get_current"})
    listed = module.run({"action": "list"})

    assert current["data"] == {
        "action": "get_current",
        "theme_id": "midnight",
        "theme_name": "午夜",
        "mode": "dark",
        "accent_base": "#ffaa00",
        "surface_base": "#101010",
        "text_primary": "#f5f5f5",
    }
    assert listed["data"]["themes"] == [
        {
            "theme_id": "midnight",
            "theme_name": "午夜",
            "mode": "dark",
            "active": True,
        }
    ]
    assert "editable_parameters" not in listed["data"]
    assert "theme_dir" not in listed["data"]


def test_theme_designer_clone_copies_assets_and_applies_explicit_overrides(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_tool("theme_designer_clone", _THEME_DESIGNER)
    themes_root = tmp_path / "themes"
    source_package = themes_root / "light"
    shutil.copytree(_PROJECT_ROOT / "Data" / "themes" / "light", source_package)
    source_theme_before = (source_package / "theme.json").read_bytes()
    source_assets_before = {
        path.relative_to(source_package / "assets"): path.read_bytes()
        for path in (source_package / "assets").rglob("*")
        if path.is_file()
    }
    monkeypatch.setattr(
        module,
        "get_settings",
        lambda: SimpleNamespace(themes_data_path=themes_root),
    )

    result = module.run(
        {
            "action": "clone",
            "source_theme_id": "light",
            "theme_id": "light-copy",
            "theme_name": "浅色副本",
            "accent_base": "#336699",
            "accent_rgb": "51, 102, 153",
            "background_opacity": 0.25,
        }
    )

    target_package = themes_root / "light-copy"
    target_payload = json.loads(
        (target_package / "theme.json").read_text(encoding="utf-8")
    )
    target_assets = {
        path.relative_to(target_package / "assets"): path.read_bytes()
        for path in (target_package / "assets").rglob("*")
        if path.is_file()
    }
    assert result["ok"] is True
    assert result["data"]["action"] == "clone"
    assert result["data"]["source_theme_id"] == "light"
    assert result["data"]["theme_id"] == "light-copy"
    assert result["data"]["activated"] is False
    assert result["data"]["copied_asset_count"] == len(source_assets_before)
    assert target_payload["id"] == "light-copy"
    assert target_payload["name"] == "浅色副本"
    assert target_payload["tokens"]["color"]["accent"]["base"] == "#336699"
    assert target_payload["tokens"]["color"]["accent"]["rgb"] == "51, 102, 153"
    assert target_payload["tokens"]["background"]["opacity"] == 0.25
    assert target_assets == source_assets_before
    assert (source_package / "theme.json").read_bytes() == source_theme_before


def test_theme_designer_clone_rejects_existing_target_without_modifying_it(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_tool("theme_designer_clone_existing", _THEME_DESIGNER)
    themes_root = tmp_path / "themes"
    source_package = themes_root / "light"
    target_package = themes_root / "existing"
    shutil.copytree(_PROJECT_ROOT / "Data" / "themes" / "light", source_package)
    target_package.mkdir(parents=True)
    marker = target_package / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    monkeypatch.setattr(
        module,
        "get_settings",
        lambda: SimpleNamespace(themes_data_path=themes_root),
    )

    result = module.run(
        {
            "action": "clone",
            "source_theme_id": "light",
            "theme_id": "existing",
            "theme_name": "不能覆盖",
        }
    )

    assert result["ok"] is False
    assert result["error_info"]["code"] == "THEME_ID_EXISTS"
    assert marker.read_text(encoding="utf-8") == "keep"
    assert not list(themes_root.glob(".existing.*.tmp"))


def test_theme_designer_clone_cleans_temporary_package_on_failure(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_tool("theme_designer_clone_cleanup", _THEME_DESIGNER)
    themes_root = tmp_path / "themes"
    source_package = themes_root / "light"
    shutil.copytree(_PROJECT_ROOT / "Data" / "themes" / "light", source_package)
    monkeypatch.setattr(
        module,
        "get_settings",
        lambda: SimpleNamespace(themes_data_path=themes_root),
    )

    def reject_write(*_args, **_kwargs) -> None:
        raise module.ToolError("WRITE_THEME_FAILED", "simulated failure")

    monkeypatch.setattr(module, "write_theme_payload", reject_write)
    result = module.run(
        {
            "action": "clone",
            "source_theme_id": "light",
            "theme_id": "failed-copy",
            "theme_name": "失败副本",
        }
    )

    assert result["ok"] is False
    assert result["error_info"]["code"] == "WRITE_THEME_FAILED"
    assert not (themes_root / "failed-copy").exists()
    assert not list(themes_root.glob(".failed-copy.*.tmp"))
    assert (source_package / "theme.json").is_file()


def test_theme_designer_clone_is_exposed_in_contract() -> None:
    input_schema = _read_json(_THEME_DESIGNER / ".tool" / "input.schema.json")
    examples = _read_json(_THEME_DESIGNER / ".tool" / "examples.json")

    assert "clone" in input_schema["properties"]["action"]["enum"]
    assert input_schema["properties"]["source_theme_id"]["pattern"]
    assert "clone 必填" in input_schema["properties"]["source_theme_id"]["description"]
    assert any('"action":"clone"' in example["content"] for example in examples)


def test_theme_designer_derives_palette_deterministically_and_preserves_non_color_settings(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_tool("theme_designer_palette", _THEME_DESIGNER)
    themes_root = tmp_path / "themes"
    theme_package = themes_root / "light"
    shutil.copytree(_PROJECT_ROOT / "Data" / "themes" / "light", theme_package)
    theme_path = theme_package / "theme.json"
    before = json.loads(theme_path.read_text(encoding="utf-8"))
    monkeypatch.setattr(
        module,
        "get_settings",
        lambda: SimpleNamespace(themes_data_path=themes_root),
    )
    request = {
        "action": "derive_palette",
        "theme_id": "light",
        "palette": {
            "background": "#F3F5F7",
            "panel": "#FFFFFF",
            "text": "#20262C",
            "accent": "#356A8A",
        },
    }

    first_result = module.run(request)
    first_content = theme_path.read_bytes()
    first_payload = json.loads(first_content)
    second_result = module.run(request)

    assert first_result["ok"] is True
    assert second_result["ok"] is True
    assert first_result["data"]["derived_token_count"] == 67
    assert first_result["data"]["palette"] == request["palette"]
    assert first_payload["tokens"]["color"]["surface"]["base"] == "#F3F5F7"
    assert first_payload["tokens"]["color"]["surface"]["panel"] == "#FFFFFF"
    assert first_payload["tokens"]["color"]["text"]["primary"] == "#20262C"
    assert first_payload["tokens"]["color"]["accent"]["base"] == "#356A8A"
    assert first_payload["tokens"]["color"]["accent"]["rgb"] == "53, 106, 138"
    assert first_payload["tokens"]["color"]["accent"]["selectionText"] == "#FFFFFF"
    assert first_payload["id"] == before["id"]
    assert first_payload["name"] == before["name"]
    assert first_payload["mode"] == before["mode"]
    assert first_payload["tokens"]["background"] == before["tokens"]["background"]
    assert first_payload["tokens"]["structure"]["enabled"] == before["tokens"]["structure"]["enabled"]
    assert first_payload["tokens"]["structure"]["lines"] == before["tokens"]["structure"]["lines"]
    assert first_payload["tokens"]["structure"]["width"] == before["tokens"]["structure"]["width"]
    assert first_payload["integrations"] == before["integrations"]
    assert theme_path.read_bytes() == first_content
    lighter_accent = module.derive_theme_palette(
        {
            "background": "#101820",
            "panel": "#182630",
            "text": "#EDF4F6",
            "accent": "#79AABD",
        },
        mode="dark",
    )
    assert lighter_accent["accent_selection_text"] == "#000000"


def test_theme_designer_rejects_invalid_palette_without_modifying_theme(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_tool("theme_designer_palette_invalid", _THEME_DESIGNER)
    themes_root = tmp_path / "themes"
    theme_package = themes_root / "light"
    shutil.copytree(_PROJECT_ROOT / "Data" / "themes" / "light", theme_package)
    theme_path = theme_package / "theme.json"
    before = theme_path.read_bytes()
    monkeypatch.setattr(
        module,
        "get_settings",
        lambda: SimpleNamespace(themes_data_path=themes_root),
    )

    result = module.run(
        {
            "action": "derive_palette",
            "theme_id": "light",
            "palette": {
                "background": "#F3F5F7",
                "panel": "#FFFFFF",
                "text": "not-a-color",
                "accent": "#356A8A",
            },
        }
    )

    assert result["ok"] is False
    assert result["error_info"]["code"] == "INVALID_PALETTE"
    assert theme_path.read_bytes() == before


def test_theme_designer_palette_is_exposed_in_contract() -> None:
    input_schema = _read_json(_THEME_DESIGNER / ".tool" / "input.schema.json")
    examples = _read_json(_THEME_DESIGNER / ".tool" / "examples.json")
    palette_schema = input_schema["properties"]["palette"]

    assert "derive_palette" in input_schema["properties"]["action"]["enum"]
    assert palette_schema["additionalProperties"] is False
    assert palette_schema["required"] == ["background", "panel", "text", "accent"]
    assert all(
        palette_schema["properties"][field]["pattern"] == "^#[0-9A-Fa-f]{6}$"
        for field in palette_schema["required"]
    )
    assert any('"action":"derive_palette"' in example["content"] for example in examples)


def test_conversation_interaction_contract_only_exposes_send() -> None:
    input_schema = _read_json(
        _INTERACT_AI_CONVERSATION / ".tool" / "input.schema.json"
    )
    output_schema = _read_json(
        _INTERACT_AI_CONVERSATION / ".tool" / "output.schema.json"
    )
    assert input_schema["properties"]["action"]["enum"] == ["send"]
    assert all(
        item.get("properties", {}).get("action", {}).get("const") in (None, "send")
        for item in output_schema["oneOf"]
    )


def test_run_python_script_warns_when_auto_detach_moves_to_background(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_tool("run_python_script_warning", _RUN_PYTHON_SCRIPT)
    monkeypatch.setenv("TIANCE_WORKSPACE_ROOT", str(tmp_path))

    @contextmanager
    def fake_runtime(_workdir: Path, _extra_env: dict[str, str]):
        yield SimpleNamespace(dependency_site_packages=None)

    outcome = SimpleNamespace(
        command=("python", "script.py"),
        source={"kind": "inline"},
        run_mode="auto_detach",
        launch_status="started",
        process_state="running",
        pid=1234,
        still_running=True,
        exit_code=None,
        stdout="",
        stderr="",
        stdout_truncated=False,
        stderr_truncated=False,
        timeout_seconds=600,
        detach_after_seconds=10,
        execution_id="execution-123",
        execution_directory=tmp_path / "execution-123",
        stdout_log_path=tmp_path / "execution-123" / "stdout.log",
        stderr_log_path=tmp_path / "execution-123" / "stderr.log",
        timed_out=False,
    )
    monkeypatch.setattr(module, "prepared_runtime", fake_runtime)
    monkeypatch.setattr(module, "execute", lambda _request: outcome)

    result = module.run(
        {
            "script_text": "print('running')",
            "run_mode": "auto_detach",
        }
    )

    assert result["ok"] is True
    assert result["data"]["still_running"] is True
    assert result["warnings"] == [
        "脚本已转入后台运行；使用 python_process_manager 并传入 "
        "execution_id=execution-123 查看状态和日志。"
    ]


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_tool(module_name: str, tool_root: Path) -> ModuleType:
    main_path = tool_root / "program" / "main.py"
    program_dir = str(main_path.parent)
    sys.path.insert(0, program_dir)
    spec = spec_from_file_location(f"{module_name}_main_under_test", main_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载工具脚本：{main_path}")
    qualified_name = spec.name
    try:
        module = module_from_spec(spec)
        sys.modules[qualified_name] = module
        spec.loader.exec_module(module)
        return module
    except Exception:
        sys.modules.pop(qualified_name, None)
        raise
    finally:
        sys.path.remove(program_dir)
