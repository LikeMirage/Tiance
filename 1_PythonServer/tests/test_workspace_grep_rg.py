from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys
from types import ModuleType

from tests.formal_tool_paths import resolve_formal_tool_root


_WORKSPACE_GREP_MAIN = (
    resolve_formal_tool_root("workspace_grep")
    / "program/main.py"
)


def test_workspace_grep_uses_ripgrep_and_keeps_match_shape(monkeypatch, tmp_path):
    module = _load_module()
    source = tmp_path / "src" / "main.py"
    source.parent.mkdir()
    source.write_text("before\nToolExecutionService()\nafter\n", encoding="utf-8")
    ignored = tmp_path / "node_modules" / "ignored.py"
    ignored.parent.mkdir()
    ignored.write_text("ToolExecutionService()\n", encoding="utf-8")
    monkeypatch.setenv("TIANCE_WORKSPACE_ROOT", str(tmp_path))

    result = module.run(
        {
            "query": "toolexecutionservice",
            "include_globs": ["**/*.py"],
            "context_lines": 1,
        }
    )

    assert result["ok"] is True
    assert result["data"]["engine"] == "ripgrep"
    assert result["data"]["truncated"] is False
    assert len(result["data"]["matches"]) == 1
    assert result["data"]["matches"][0] == {
        "file": "src/main.py",
        "path": str(source),
        "line": 2,
        "column": 1,
        "text": "ToolExecutionService()",
        "before": ["before"],
        "after": ["after"],
    }


def test_workspace_grep_regex_reports_character_column_for_unicode(monkeypatch, tmp_path):
    module = _load_module()
    source = tmp_path / "unicode.py"
    source.write_text("中文前缀 ToolExecutionService\n", encoding="utf-8")
    monkeypatch.setenv("TIANCE_WORKSPACE_ROOT", str(tmp_path))

    result = module.run(
        {
            "query": "ToolExecution(Service|Context)",
            "regex": True,
            "case_sensitive": True,
        }
    )

    assert result["ok"] is True
    assert result["data"]["matches"][0]["column"] == 6


def test_workspace_grep_treats_no_match_as_success(monkeypatch, tmp_path):
    module = _load_module()
    (tmp_path / "notes.txt").write_text("hello\n", encoding="utf-8")
    monkeypatch.setenv("TIANCE_WORKSPACE_ROOT", str(tmp_path))

    result = module.run({"query": "missing"})

    assert result["ok"] is True
    assert result["data"]["matches"] == []
    assert result["data"]["truncated"] is False


def test_workspace_grep_rejects_invalid_regex(monkeypatch, tmp_path):
    module = _load_module()
    (tmp_path / "notes.txt").write_text("hello\n", encoding="utf-8")
    monkeypatch.setenv("TIANCE_WORKSPACE_ROOT", str(tmp_path))

    result = module.run({"query": "(", "regex": True})

    assert result["ok"] is False
    assert result["error_info"]["code"] == "INVALID_REGEX"


def test_workspace_grep_enforces_total_match_limit(monkeypatch, tmp_path):
    module = _load_module()
    (tmp_path / "many.txt").write_text("hit\nhit\nhit\n", encoding="utf-8")
    monkeypatch.setenv("TIANCE_WORKSPACE_ROOT", str(tmp_path))

    result = module.run({"query": "hit", "max_matches": 2})

    assert result["ok"] is True
    assert len(result["data"]["matches"]) == 2
    assert result["data"]["truncated"] is True
    assert result["warnings"] == ["结果达到 max_matches，已截断。"]


def test_workspace_grep_rejects_base_path_outside_workspace(monkeypatch, tmp_path):
    module = _load_module()
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    monkeypatch.setenv("TIANCE_WORKSPACE_ROOT", str(workspace))

    result = module.run({"query": "text", "base_path": str(outside)})

    assert result["ok"] is False
    assert result["error_info"]["code"] == "PATH_OUTSIDE_WORKSPACE"


def test_workspace_grep_supports_explicit_gbk_with_context(monkeypatch, tmp_path):
    module = _load_module()
    source = tmp_path / "legacy.txt"
    source.write_bytes("前一行\r\n中文目标\r\n后一行\r\n".encode("gbk"))
    monkeypatch.setenv("TIANCE_WORKSPACE_ROOT", str(tmp_path))

    result = module.run(
        {
            "query": "中文",
            "encoding": "gbk",
            "context_lines": 1,
        }
    )

    assert result["ok"] is True
    assert result["data"]["encoding"] == "gbk"
    assert result["data"]["matches"][0]["text"] == "中文目标"
    assert result["data"]["matches"][0]["before"] == ["前一行"]
    assert result["data"]["matches"][0]["after"] == ["后一行"]


def test_workspace_grep_reports_missing_binary(monkeypatch, tmp_path):
    module = _load_module()
    monkeypatch.setenv("TIANCE_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setattr(
        module.ripgrep_runner,
        "RG_BINARY",
        tmp_path / "missing-rg.exe",
    )

    result = module.run({"query": "text"})

    assert result["ok"] is False
    assert result["error_info"]["code"] == "DEPENDENCY_MISSING"


def _load_module() -> ModuleType:
    program_dir = str(_WORKSPACE_GREP_MAIN.parent)
    sys.path.insert(0, program_dir)
    spec = spec_from_file_location("workspace_grep_main_under_test", _WORKSPACE_GREP_MAIN)
    if spec is None or spec.loader is None:
        raise RuntimeError("无法加载 workspace_grep 工具脚本。")
    try:
        module = module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(program_dir)
