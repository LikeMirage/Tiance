from importlib.util import module_from_spec, spec_from_file_location
from types import ModuleType
from tests.formal_tool_paths import resolve_formal_tool_root
_LOAD_TOOL_INFO_MAIN = resolve_formal_tool_root("load_tool_info") / "program/main.py"


def test_load_tool_info_reads_parameters_from_host_bridge(monkeypatch):
    module = _load_tool_info_module()
    calls = []
    def call(capability, payload, *, timeout_seconds):
        calls.append((capability, payload))
        return {"input_schema": {"required": ["file_path"]}, "summary": {
            "name": "read_text_file", "display_name": "文本读取", "description": "读取文件。",
            "category": "基础工具", "dynamic": True, "parallel": False,
            "parameter_names": ["file_path"], "example_titles": ["读取全文"]}}
    monkeypatch.setattr(module, "call_host_capability", call)
    result = module.run({"operation": "get_parameters", "tool_name": "read_text_file"})
    assert result["ok"] is True
    assert result["data"]["input_schema"]["required"] == ["file_path"]
    assert "keywords" not in result["data"]
    assert calls == [("tool_catalog", {"operation": "get_parameters", "tool_name": "read_text_file"})]


def test_load_tool_info_reads_examples_from_host_bridge(monkeypatch):
    module = _load_tool_info_module()
    calls = []
    def call(capability, payload, *, timeout_seconds):
        calls.append((capability, payload))
        return {"items": [{"index": 2, "title": "搜索关键词", "content": '{"mode":"search"}'}]}
    monkeypatch.setattr(module, "call_host_capability", call)
    result = module.run({"operation": "get_examples", "tool_name": "read_text_file",
        "example_indexes": [2], "example_titles": ["搜索关键词"]})
    assert result["ok"] is True
    assert result["data"]["examples"] == [{"index": 2, "title": "搜索关键词", "content": '{"mode":"search"}'}]
    assert calls == [("tool_catalog", {"operation": "get_examples", "tool_name": "read_text_file",
        "indexes": [2], "titles": ["搜索关键词"], "include_all": False})]


def _load_tool_info_module() -> ModuleType:
    spec = spec_from_file_location("load_tool_info_main_under_test", _LOAD_TOOL_INFO_MAIN)
    if spec is None or spec.loader is None:
        raise RuntimeError("无法加载 load_tool_info 工具脚本。")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
