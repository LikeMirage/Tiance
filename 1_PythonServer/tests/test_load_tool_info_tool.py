from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType

from tests.formal_tool_paths import resolve_formal_tool_root


_LOAD_TOOL_INFO_MAIN = (
    resolve_formal_tool_root("load_tool_info")
    / "program/main.py"
)


def test_load_tool_info_reads_parameters_from_backend_api(monkeypatch):
    module = _load_tool_info_module()
    calls: list[tuple[str, str, dict | None, dict | None]] = []

    def fake_request_json(method, path, *, query=None, payload=None):
        calls.append((method, path, query, payload))
        if path == "/tools/catalog/read_text_file/parameters":
            return {
                "name": "read_text_file",
                "input_schema": {
                    "type": "object",
                    "required": ["file_path"],
                    "properties": {"file_path": {"type": "string"}},
                },
            }
        if path == "/tools/catalog/summaries":
            return {
                "count": 1,
                "items": [
                    {
                        "name": "read_text_file",
                        "display_name": "文本读取",
                        "description": "读取文件。",
                        "keywords": ["文件"],
                        "category": "基础工具",
                        "dynamic": True,
                        "parallel": False,
                        "parameter_names": ["file_path"],
                        "example_titles": ["读取全文"],
                    }
                ],
            }
        raise AssertionError(f"unexpected path: {path}")

    monkeypatch.setenv("TIANCE_PROJECT_ID", "project-1")
    monkeypatch.setenv("TIANCE_SESSION_ID", "session-1")
    monkeypatch.setattr(module, "_request_json", fake_request_json)

    result = module.run({"operation": "get_parameters", "tool_name": "read_text_file"})

    assert result["ok"] is True
    assert result["data"]["input_schema"]["required"] == ["file_path"]
    assert calls[0] == (
        "GET",
        "/tools/catalog/read_text_file/parameters",
        {"project_id": "project-1", "session_id": "session-1"},
        None,
    )


def test_load_tool_info_reads_examples_from_backend_api(monkeypatch):
    module = _load_tool_info_module()
    calls: list[tuple[str, str, dict | None, dict | None]] = []

    def fake_request_json(method, path, *, query=None, payload=None):
        calls.append((method, path, query, payload))
        return {
            "name": "read_text_file",
            "count": 1,
            "items": [
                {
                    "index": 2,
                    "title": "搜索关键词",
                    "content": '{"mode":"search"}',
                }
            ],
        }

    monkeypatch.setattr(module, "_request_json", fake_request_json)

    result = module.run(
        {
            "operation": "get_examples",
            "tool_name": "read_text_file",
            "example_indexes": [2],
            "example_titles": ["搜索关键词"],
        }
    )

    assert result["ok"] is True
    assert result["data"]["examples"] == [
        {
            "index": 2,
            "title": "搜索关键词",
            "content": '{"mode":"search"}',
        }
    ]
    assert calls == [
        (
            "POST",
            "/tools/catalog/read_text_file/examples/query",
            {},
            {
                "indexes": [2],
                "titles": ["搜索关键词"],
                "include_all": False,
            },
        )
    ]


def _load_tool_info_module() -> ModuleType:
    spec = spec_from_file_location("load_tool_info_main_under_test", _LOAD_TOOL_INFO_MAIN)
    if spec is None or spec.loader is None:
        raise RuntimeError("无法加载 load_tool_info 工具脚本。")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
