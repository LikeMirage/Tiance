from json import dumps, loads
from pathlib import Path
import shutil
import sys
from time import monotonic
import pytest

from app.domain.llm.chat import ChatToolCall
from app.services.tools.tool_execution import ToolExecutionContext, ToolExecutionService
from app.services.tools.tool_execution_arguments import validate_tool_arguments
from app.services.tools.tool_metadata import load_tool
from tests.test_tool_execution import _FakeRegistry


SOURCE = Path(__file__).resolve().parents[2] / "Data/tools/15a29fd6-f2da-5877-93b7-6052a5364e67"


@pytest.mark.parametrize("tool_seconds,command_seconds,error", [
    (1, None, "工具执行超时"),
    (1, 120, "工具执行超时"),
    (10, 1, "COMMAND_TIMEOUT"),
])
def test_command_timeout_does_not_override_manifest_deadline(tmp_path, tool_seconds, command_seconds, error):
    tool = tmp_path / "command-tool"
    shutil.copytree(SOURCE / ".tool", tool / ".tool")
    shutil.copytree(SOURCE / "program", tool / "program", ignore=shutil.ignore_patterns("__pycache__"))
    manifest_path = tool / ".tool/tool.json"
    manifest = loads(manifest_path.read_text(encoding="utf-8"))
    manifest["runtime"]["timeout_seconds"] = tool_seconds
    manifest_path.write_text(dumps(manifest), encoding="utf-8")
    started_marker = tmp_path / "started"
    command = (
        "import pathlib,time;"
        f"pathlib.Path({str(started_marker)!r}).write_text('started');"
        "print('before-timeout',flush=True);time.sleep(20)"
    )
    arguments = {"argv": [sys.executable, "-c", command]}
    if command_seconds is not None:
        arguments["timeout_seconds"] = command_seconds
    metadata = load_tool(str(tool))
    assert not validate_tool_arguments(arguments, metadata.input_schema)
    assert validate_tool_arguments({**arguments, "timeout_seconds": 10000}, metadata.input_schema)
    for _, example in metadata.examples:
        assert not validate_tool_arguments(loads(example["content"]), metadata.input_schema)
    service = ToolExecutionService(_FakeRegistry(tool), python_executable=Path(sys.executable))
    started = monotonic()
    result = service.execute(
        ChatToolCall(call_id="deadline-test", name="run_command", arguments=dumps(arguments)),
        context=ToolExecutionContext(workspace_root=str(tmp_path)),
    )
    assert started_marker.exists(), result
    assert not result.ok
    assert error in str(result.error)
    if error == "COMMAND_TIMEOUT":
        output = loads(result.content)
        assert output["data"]["status"] == "timeout"
        assert output["data"]["stdout"].strip() == "before-timeout"
    assert monotonic() - started < 8
