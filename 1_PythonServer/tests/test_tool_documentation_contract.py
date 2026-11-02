"""Validate shipped documentation through the same metadata and argument readers."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.services.tools.tool_execution_arguments import validate_tool_arguments
from app.services.tools.tool_metadata import example_detail, load_tool

TOOLS_ROOT = Path(__file__).resolve().parents[2] / "Data/tools"
TOOL_PATHS = sorted(TOOLS_ROOT.glob("*/.tool/tool.json"))


def documentation_inputs(content: str):
    """Read embedded input objects, skipping explanatory text and expected results."""
    text = re.split(r"预期返回[：:]|预期输出[：:]", content, maxsplit=1)[0]
    decoder = json.JSONDecoder()
    offset = 0
    while offset < len(text):
        start = text.find("{", offset)
        if start < 0:
            return
        try:
            payload, length = decoder.raw_decode(text[start:])
        except ValueError:
            offset = start + 1
            continue
        offset = start + length
        if isinstance(payload, dict):
            yield payload


@pytest.mark.parametrize("manifest_path", TOOL_PATHS, ids=lambda p: p.parent.parent.name)
def test_shipped_instructions_are_readable_and_examples_match_schema(manifest_path):
    tool = load_tool(str(manifest_path.parent.parent))
    titles = set()
    for index, example in tool.examples:
        assert "input" not in example, (tool.name, "正文应保存于 content")
        detail = example_detail(index, example)
        assert detail.title and detail.content, (tool.name, index)
        assert detail.title not in titles, (tool.name, detail.title)
        titles.add(detail.title)
        for payload in documentation_inputs(detail.content):
            # Guides may quote objects returned by other tools, or partial fields.
            properties = tool.input_schema.get("properties", {})
            if payload and not (payload.keys() & properties.keys()):
                continue
            errors = validate_tool_arguments(payload, tool.input_schema)
            assert not errors, (tool.name, detail.title, errors)
            if tool.name == "run_python_script" and "script_text" in payload:
                compile(payload["script_text"], "<documented-script>", "exec")
            if tool.name == "safe_patch" and "patch_text" in payload:
                assert "\n@@" in payload["patch_text"], "补丁应含真实换行"
            if tool.name == "workspace_grep" and payload.get("regex"):
                assert re.search(payload["query"], "@router.get"), "正则不应多转义一层"


def test_dynamic_directory_counts_explicit_instruction_content():
    from app.domain.tools import ToolExampleDetail, ToolSummary
    from app.services.tools.chat_tool_injection import _dynamic_tool_directory_prompt
    from app.services.tools.dynamic_tool_prompt import dynamic_tool_directory_intro_lines
    from app.services.tools.tool_registry import _dynamic_injection_char_count

    def summary(name, dynamic=False):
        return ToolSummary(name=name, display_name=name, description="用途", category="测试",
                           dynamic=dynamic, parameter_names=(),
                           example_titles=("操作指南", "调用示例") if dynamic else ())

    target = summary("target", True)
    examples = (ToolExampleDetail(index=1, title="操作指南", content="完整操作说明", inject_content=True),
                ToolExampleDetail(index=2, title="调用示例", content="按需读取的内容", inject_content=False))
    prompt = _dynamic_tool_directory_prompt(
        (summary("load_tool_info"), summary("execute_dynamic_tool"), target), {"target": examples})
    prefix = "\n".join(dynamic_tool_directory_intro_lines()) + "\n"
    assert "完整操作说明" in prompt and "按需读取的内容" not in prompt
    assert _dynamic_injection_char_count(target, examples) == len(prompt.removeprefix(prefix))
