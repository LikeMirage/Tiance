from __future__ import annotations

from json import dumps, loads
from pathlib import Path
import subprocess

from app.domain.llm.chat import ChatToolCall
from app.domain.tools import ToolMetadataSnapshot, ToolRegistryEntry
from app.services.tools.tool_execution import ToolExecutionContext, ToolExecutionService
from app.services.tools.tool_execution_results import TOOL_ARGUMENT_VALIDATION_FAILED
from app.services.tools.tool_metadata import load_tool


def test_dynamic_tool_executor_runs_enabled_dynamic_target(tmp_path):
    registry = _GatewayRegistry(tmp_path)
    completed_inputs: list[str] = []

    def command_runner(command, input_text, cwd, env, timeout_seconds):
        completed_inputs.append(input_text)
        return subprocess.CompletedProcess(
            command,
            returncode=0,
            stdout=dumps({"ok": True, "theme_id": "dark-gold"}),
            stderr="",
        )

    service = ToolExecutionService(
        registry,
        python_executable=Path("python"),
        command_runner=command_runner,
    )
    result = service.execute(
        _executor_call("theme_designer", {"action": "switch"}),
        context=ToolExecutionContext(enabled_tool_names=("theme_designer",)),
    )

    assert result.ok is True
    assert result.name == "execute_dynamic_tool"
    assert completed_inputs == ['{"action": "switch"}']
    payload = loads(result.content)
    assert payload["data"]["tool_name"] == "theme_designer"
    assert payload["data"]["result"]["theme_id"] == "dark-gold"


def test_dynamic_tool_executor_preserves_generic_rich_content(tmp_path):
    registry = _GatewayRegistry(tmp_path)
    rich_content = [
        {
            "type": "resource_link",
            "uri": "tiance-project:///exports/diagram.png",
            "name": "diagram.png",
            "mimeType": "image/png",
        }
    ]
    service = ToolExecutionService(
        registry,
        python_executable=Path("python"),
        command_runner=lambda *_args: subprocess.CompletedProcess(
            [],
            0,
            dumps(
                {
                    "ok": True,
                    "content": rich_content,
                    "structuredContent": {"kind": "diagram"},
                }
            ),
            "",
        ),
    )

    result = service.execute(
        _executor_call("theme_designer", {"action": "switch"}),
        context=ToolExecutionContext(enabled_tool_names=("theme_designer",)),
    )

    payload = loads(result.content)
    assert payload["content"] == rich_content
    assert payload["structuredContent"] == {"kind": "diagram"}


def test_dynamic_tool_executor_rejects_session_disabled_target(tmp_path):
    completed_commands: list[list[str]] = []
    service = ToolExecutionService(
        _GatewayRegistry(tmp_path),
        python_executable=Path("python"),
        command_runner=lambda command, *_args: completed_commands.append(command),
    )

    result = service.execute(
        _executor_call("theme_designer", {}),
        context=ToolExecutionContext(enabled_tool_names=("other_dynamic_tool",)),
    )

    assert result.ok is False
    assert result.error == "此工具已关闭。"
    assert completed_commands == []


def test_dynamic_tool_executor_rejects_non_dynamic_target(tmp_path):
    completed_commands: list[list[str]] = []
    service = ToolExecutionService(
        _GatewayRegistry(tmp_path),
        python_executable=Path("python"),
        command_runner=lambda command, *_args: completed_commands.append(command),
    )

    result = service.execute(
        _executor_call("read_file", {}),
        context=ToolExecutionContext(enabled_tool_names=("read_file",)),
    )

    assert result.ok is False
    assert result.error == "execute_dynamic_tool 只能执行动态加载工具。"
    assert completed_commands == []


def test_dynamic_tool_executor_uses_target_schema_validation(tmp_path):
    service = ToolExecutionService(
        _GatewayRegistry(tmp_path),
        python_executable=Path("python"),
        command_runner=lambda *_args: subprocess.CompletedProcess([], 0, "{}", ""),
    )

    result = service.execute(
        _executor_call("theme_designer", {}),
        context=ToolExecutionContext(enabled_tool_names=("theme_designer",)),
    )

    assert result.ok is False
    assert result.error == "工具参数校验失败：参数.action 为必填参数。"
    payload = loads(result.content)
    assert (
        payload["data"]["result"]["error_info"]["code"]
        == TOOL_ARGUMENT_VALIDATION_FAILED
    )


def _executor_call(tool_name: str, arguments: dict) -> ChatToolCall:
    return ChatToolCall(
        call_id="call-1",
        name="execute_dynamic_tool",
        arguments=dumps({"tool_name": tool_name, "arguments": arguments}),
    )


class _GatewayRegistry:
    def __init__(self, tmp_path: Path) -> None:
        self._roots = {
            "execute_dynamic_tool": _create_tool(
                tmp_path / "executor",
                name="execute_dynamic_tool",
                dynamic=False,
                runtime_type="internal",
                input_schema={
                    "type": "object",
                    "required": ["tool_name", "arguments"],
                    "properties": {
                        "tool_name": {"type": "string"},
                        "arguments": {"type": "object"},
                    },
                    "additionalProperties": False,
                },
            ),
            "theme_designer": _create_tool(
                tmp_path / "theme",
                name="theme_designer",
                dynamic=True,
                input_schema={
                    "type": "object",
                    "required": ["action"],
                    "properties": {"action": {"type": "string", "enum": ["switch"]}},
                    "additionalProperties": False,
                },
            ),
            "read_file": _create_tool(
                tmp_path / "reader",
                name="read_file",
                dynamic=False,
            ),
        }
        self._metadata = {
            name: _metadata(root)
            for name, root in self._roots.items()
        }

    def get_enabled_entry(self, tool_name: str):
        return self.get_entry(tool_name)

    def get_entry(self, tool_name: str):
        root = self._roots.get(tool_name)
        if root is None:
            return None
        return ToolRegistryEntry(
            project_id=f"folder_{tool_name}",
            category_id="toolset_1",
            category_name="基础工具",
            tool_name=tool_name,
            display_name=tool_name,
            description=tool_name,
            keywords=(),
            enabled=True,
            dynamic=tool_name == "theme_designer",
            root_path=str(root),
            runtime_entry="program/main.py",
            parameter_names=(),
            example_titles=(),
            indexed_at="now",
            updated_at="now",
        )

    def get_enabled_metadata(self, tool_name: str):
        return self._metadata.get(tool_name)


def _create_tool(
    root: Path,
    *,
    name: str,
    dynamic: bool,
    runtime_type: str = "python",
    input_schema: dict | None = None,
) -> Path:
    config_root = root / ".tool"
    program_root = root / "program"
    config_root.mkdir(parents=True)
    program_root.mkdir(parents=True)
    (config_root / "tool.json").write_text(
        dumps(
            {
                "name": name,
                "display_name": name,
                "description": name,
                "loading": {"dynamic": dynamic},
                "runtime": {
                    "type": runtime_type,
                    "entry": "program/main.py",
                    "timeout_seconds": 30,
                },
                "execution": {"parallel": True},
                "state": {"enabled": True},
            }
        ),
        encoding="utf-8",
    )
    (config_root / "input.schema.json").write_text(
        dumps(input_schema or {"type": "object", "properties": {}, "required": []}),
        encoding="utf-8",
    )
    (config_root / "output.schema.json").write_text("{}", encoding="utf-8")
    (config_root / "examples.json").write_text("[]", encoding="utf-8")
    (program_root / "main.py").write_text("print('{}')", encoding="utf-8")
    return root


def _metadata(root: Path) -> ToolMetadataSnapshot:
    loaded = load_tool(str(root))
    return ToolMetadataSnapshot(
        name=loaded.name,
        manifest=loaded.manifest,
        input_schema=loaded.input_schema,
        output_schema=loaded.output_schema,
        examples=loaded.examples,
    )
