from json import dumps, loads

from app.domain.llm.chat import ChatToolResult
from app.domain.tools import ToolRegistryEntry
from app.services.tools.tool_execution_results import TOOL_ARGUMENT_VALIDATION_FAILED
from app.services.tools.tool_result_guidance import ToolResultGuidanceService


def test_tool_result_guidance_suggests_parameters_for_dynamic_argument_validation():
    service = ToolResultGuidanceService(
        _FakeRegistryService(
            _tool_entry(
                tool_name="execute_dynamic_tool",
                display_name="动态工具执行",
                dynamic=False,
            ),
            _tool_entry(
                tool_name="parse_document",
                display_name="文档解析",
                dynamic=True,
            )
        )
    )

    result = service.add_failure_guidance(
        ChatToolResult(
            call_id="call-1",
            name="execute_dynamic_tool",
            arguments='{"tool_name":"parse_document","arguments":{}}',
            ok=False,
            content=dumps(
                {
                    "ok": False,
                    "error": "参数错误",
                    "data": {
                        "tool_name": "parse_document",
                        "arguments": {},
                        "result": {
                            "ok": False,
                            "error": "参数错误",
                            "error_info": {
                                "code": TOOL_ARGUMENT_VALIDATION_FAILED,
                            },
                            "assistant_hint": {"message": "旧引导"},
                        },
                    },
                },
                ensure_ascii=False,
            ),
            error="参数错误",
        )
    )

    payload = loads(result.content)
    assert payload["error"] == "参数错误"
    assert "assistant_hint" not in payload["data"]["result"]
    assert payload["assistant_hint"]["tool_name"] == "parse_document"
    assert payload["assistant_hint"]["dynamic"] is True
    assert payload["assistant_hint"]["suggested_tool"] == "load_tool_info"
    assert payload["assistant_hint"]["suggested_arguments"] == {
        "operation": "get_parameters",
        "tool_name": "parse_document",
    }
    assert "execute_dynamic_tool" in payload["assistant_hint"]["next_step"]


def test_tool_result_guidance_does_not_reload_parameters_for_dynamic_runtime_failure():
    service = ToolResultGuidanceService(
        _FakeRegistryService(
            _tool_entry(
                tool_name="execute_dynamic_tool",
                display_name="动态工具执行",
                dynamic=False,
            ),
            _tool_entry(
                tool_name="parse_document",
                display_name="文档解析",
                dynamic=True,
            ),
        )
    )

    result = service.add_failure_guidance(
        ChatToolResult(
            call_id="call-1",
            name="execute_dynamic_tool",
            arguments='{"tool_name":"parse_document","arguments":{"file_path":"missing.pdf"}}',
            ok=False,
            content=dumps(
                {
                    "ok": False,
                    "error": "文件不存在",
                    "data": {
                        "tool_name": "parse_document",
                        "arguments": {"file_path": "missing.pdf"},
                        "result": {
                            "ok": False,
                            "error": "文件不存在",
                        },
                    },
                },
                ensure_ascii=False,
            ),
            error="文件不存在",
        )
    )

    payload = loads(result.content)
    hint = payload["assistant_hint"]
    assert hint["tool_name"] == "parse_document"
    assert hint["error"] == "文件不存在"
    assert "suggested_tool" not in hint
    assert "load_tool_info" not in hint["next_step"]
    assert "execute_dynamic_tool" in hint["next_step"]


def test_tool_result_guidance_suggests_examples_for_static_tool_failure():
    service = ToolResultGuidanceService(
        _FakeRegistryService(
            _tool_entry(
                tool_name="run_command",
                display_name="命令行执行",
                dynamic=False,
                example_titles=("查看 Git 状态", "运行测试"),
            )
        )
    )

    result = service.add_failure_guidance(
        ChatToolResult(
            call_id="call-1",
            name="run_command",
            arguments='{"command":"bad"}',
            ok=False,
            content='{"ok":false,"error":"命令失败"}',
            error="命令失败",
        )
    )

    payload = loads(result.content)
    assert payload["assistant_hint"]["dynamic"] is False
    assert payload["assistant_hint"]["suggested_tool"] == "load_tool_info"
    assert payload["assistant_hint"]["suggested_arguments"] == {
        "operation": "get_examples",
        "tool_name": "run_command",
        "include_all_examples": True,
    }
    assert payload["assistant_hint"]["example_titles"] == ["查看 Git 状态", "运行测试"]


def test_tool_result_guidance_keeps_success_result_unchanged():
    service = ToolResultGuidanceService(_FakeRegistryService(None))
    result = ChatToolResult(
        call_id="call-1",
        name="run_command",
        arguments="{}",
        ok=True,
        content='{"ok":true}',
    )

    assert service.add_failure_guidance(result) is result


def test_tool_result_guidance_handles_missing_registry_entry():
    service = ToolResultGuidanceService(_FakeRegistryService(None))

    result = service.add_failure_guidance(
        ChatToolResult(
            call_id="call-1",
            name="missing_tool",
            arguments="{}",
            ok=False,
            content='{"ok":false,"error":"不存在"}',
            error="不存在",
        )
    )

    payload = loads(result.content)
    assert payload["assistant_hint"]["tool_name"] == "missing_tool"
    assert "没有找到该工具" in payload["assistant_hint"]["message"]


class _FakeRegistryService:
    def __init__(self, *entries: ToolRegistryEntry | None) -> None:
        self._entries = {
            entry.tool_name: entry
            for entry in entries
            if entry is not None
        }

    def get_enabled_entry(self, tool_name: str) -> ToolRegistryEntry | None:
        return self._entries.get(tool_name)


def _tool_entry(
    *,
    tool_name: str,
    display_name: str,
    dynamic: bool,
    example_titles: tuple[str, ...] = (),
) -> ToolRegistryEntry:
    return ToolRegistryEntry(
        project_id="tool_1",
        category_id="toolset_1",
        category_name="基础工具",
        tool_name=tool_name,
        display_name=display_name,
        description="工具说明。",
        keywords=(),
        enabled=True,
        dynamic=dynamic,
        root_path="C:/tool",
        runtime_entry="program/main.py",
        parameter_names=(),
        example_titles=example_titles,
        indexed_at="now",
        updated_at="now",
        parallel=False,
    )
