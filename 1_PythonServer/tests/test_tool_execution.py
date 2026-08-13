from __future__ import annotations

from json import dumps, loads
from pathlib import Path
import os
import subprocess
import sys
import threading
import time

from app.domain.llm.chat import ChatToolCall
from app.domain.tools import ToolMetadataSnapshot, ToolRegistryEntry
from app.core.config import get_settings
from app.services.tools.tool_execution import ToolExecutionContext, ToolExecutionService
from app.services.tools.tool_execution_runtime import (
    ToolExecutionCancellation,
    resolve_backend_api_base_url,
    run_command,
    runtime_timeout_seconds,
)
from app.services.tools.host_capability_access import (
    HostCapability,
    HostCapabilityAccessService,
)
from app.services.tools.tool_metadata import load_tool


def test_tool_execution_runs_python_entry_with_json_stdin(tmp_path, monkeypatch):
    monkeypatch.setenv("TIANCE_API_HOST", "127.0.0.2")
    monkeypatch.setenv("TIANCE_API_PORT", "19000")
    monkeypatch.setenv("APPDATA", "C:/Users/test/AppData/Roaming")
    monkeypatch.setenv("LOCALAPPDATA", "C:/Users/test/AppData/Local")
    tool_root = _create_tool_root(tmp_path)
    completed_commands: list[tuple[list[str], str, Path, dict[str, str], int]] = []

    def command_runner(command, input_text, cwd, env, timeout_seconds):
        completed_commands.append((command, input_text, cwd, env, timeout_seconds))
        return subprocess.CompletedProcess(
            command,
            returncode=0,
            stdout=dumps({"ok": True, "content": "done"}, ensure_ascii=False),
            stderr="",
        )

    service = ToolExecutionService(
        _FakeRegistry(tool_root),
        python_executable=Path("python"),
        command_runner=command_runner,
    )

    result = service.execute(
        ChatToolCall(
            call_id="call-1",
            name="read_text_file",
            arguments='{"file_path":"C:/work/app.py"}',
        ),
        context=ToolExecutionContext(
            workspace_root=str(tmp_path),
            project_id="project-1",
            session_id="session-1",
            provider_id="provider-1",
            model_id="model-1",
            input_modalities=("text", "image"),
        ),
    )

    assert result.ok is True
    assert result.content == '{"ok":true,"content":"done"}'
    assert completed_commands[0][1] == '{"file_path": "C:/work/app.py"}'
    assert completed_commands[0][2] == tmp_path
    assert completed_commands[0][4] == 12
    assert "TIANCE_WORKSPACE_ROOT" in completed_commands[0][3]
    assert Path(completed_commands[0][3]["TIANCE_TOOLS_ROOT"]) == (
        get_settings().tools_data_path.resolve(strict=False)
    )
    assert completed_commands[0][3]["TIANCE_PROJECT_ID"] == "project-1"
    assert completed_commands[0][3]["TIANCE_SESSION_ID"] == "session-1"
    assert completed_commands[0][3]["TIANCE_API_BASE_URL"] == "http://127.0.0.2:19000/api"
    assert completed_commands[0][3]["APPDATA"] == "C:/Users/test/AppData/Roaming"
    assert completed_commands[0][3]["LOCALAPPDATA"] == "C:/Users/test/AppData/Local"
    assert loads(completed_commands[0][3]["TIANCE_MODEL_CONTEXT"]) == {
        "provider_id": "provider-1",
        "model_id": "model-1",
        "input_modalities": ["image", "text"],
    }
    command = completed_commands[0][0]
    assert command[:2] == ["python", "-c"]
    assert str(tool_root / "program") in command
    assert str(tool_root / "dependencies" / "py313" / "site-packages") in command
    assert any(
        "runtime" in path and "python-packages" in path and "backend" in path
        for path in command
    )
    assert str(tool_root / "program") in completed_commands[0][3]["PYTHONPATH"]
    assert "TIANCE_HOST_CAPABILITY_TOKEN" not in completed_commands[0][3]


def test_network_search_receives_process_scoped_capability_grant(tmp_path):
    tool_root = _create_tool_root(tmp_path, tool_name="network_search")
    access = HostCapabilityAccessService()
    issued_token: str | None = None

    def command_runner(command, input_text, cwd, env, timeout_seconds):
        nonlocal issued_token
        issued_token = env.get("TIANCE_HOST_CAPABILITY_TOKEN")
        assert issued_token
        grant = access.authorize(issued_token, HostCapability.WEB_SEARCH)
        assert grant is not None
        assert grant.tool_name == "network_search"
        assert grant.tool_call_id == "call-search"
        assert grant.provider_id == "provider-1"
        assert grant.model_id == "model-1"
        return subprocess.CompletedProcess(
            command,
            returncode=0,
            stdout=dumps({"ok": True}, ensure_ascii=False),
            stderr="",
        )

    service = ToolExecutionService(
        _FakeRegistry(tool_root),
        python_executable=Path("python"),
        command_runner=command_runner,
        host_capability_access=access,
    )

    result = service.execute(
        ChatToolCall(
            call_id="call-search",
            name="network_search",
            arguments='{"query":"latest update"}',
        ),
        context=ToolExecutionContext(
            project_id="project-1",
            session_id="session-1",
            provider_id="provider-1",
            model_id="model-1",
        ),
    )

    assert result.ok is True
    assert issued_token is not None
    assert access.authorize(issued_token, HostCapability.WEB_SEARCH) is None


def test_network_search_capability_grant_follows_model_switch(tmp_path):
    tool_root = _create_tool_root(tmp_path, tool_name="network_search")
    access = HostCapabilityAccessService()
    observed_contexts: list[tuple[str, str]] = []
    issued_tokens: list[str] = []

    def command_runner(command, input_text, cwd, env, timeout_seconds):
        token = env.get("TIANCE_HOST_CAPABILITY_TOKEN")
        assert token
        issued_tokens.append(token)
        grant = access.authorize(token, HostCapability.WEB_SEARCH)
        assert grant is not None
        observed_contexts.append((grant.provider_id, grant.model_id))
        return subprocess.CompletedProcess(
            command,
            returncode=0,
            stdout=dumps({"ok": True}, ensure_ascii=False),
            stderr="",
        )

    service = ToolExecutionService(
        _FakeRegistry(tool_root),
        python_executable=Path("python"),
        command_runner=command_runner,
        host_capability_access=access,
    )

    for call_id, provider_id, model_id in (
        ("call-openai", "openai", "gpt-5.6"),
        ("call-volcengine", "volcengine", "doubao-seed-2-0-pro"),
    ):
        result = service.execute(
            ChatToolCall(
                call_id=call_id,
                name="network_search",
                arguments='{"query":"latest update"}',
            ),
            context=ToolExecutionContext(
                project_id="project-1",
                session_id="session-1",
                provider_id=provider_id,
                model_id=model_id,
            ),
        )
        assert result.ok is True

    assert observed_contexts == [
        ("openai", "gpt-5.6"),
        ("volcengine", "doubao-seed-2-0-pro"),
    ]
    assert all(
        access.authorize(token, HostCapability.WEB_SEARCH) is None
        for token in issued_tokens
    )


def test_tool_runtime_timeout_has_no_hidden_upper_limit():
    assert runtime_timeout_seconds(1200) == 1200
    assert runtime_timeout_seconds(0) == 1


def test_tool_runtime_cancellation_stops_owned_foreground_process(tmp_path):
    cancellation = ToolExecutionCancellation()
    completed: list[subprocess.CompletedProcess[str]] = []

    def execute() -> None:
        completed.append(
            run_command(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                "",
                tmp_path,
                os.environ.copy(),
                60,
                cancellation=cancellation,
            )
        )

    thread = threading.Thread(target=execute)
    thread.start()
    time.sleep(0.2)
    cancellation.cancel()
    thread.join(timeout=5)

    assert not thread.is_alive()
    assert completed[0].returncode != 0
    assert completed[0].stderr == "工具执行已取消。"


def test_tool_runtime_stops_process_when_output_exceeds_capture_limit(tmp_path):
    completed = run_command(
        [sys.executable, "-c", "print('x' * 100000)"],
        "",
        tmp_path,
        os.environ.copy(),
        30,
        max_capture_bytes=1024,
    )

    assert completed.returncode != 0
    assert completed.stdout == ""
    assert completed.stderr == "工具输出超过安全上限，执行已终止。"


def test_tool_runtime_keeps_explicitly_detached_work_after_tool_returns(tmp_path):
    marker = tmp_path / "background-finished.txt"
    child_code = (
        "import pathlib,time; time.sleep(0.3); "
        f"pathlib.Path({str(marker)!r}).write_text('done', encoding='utf-8')"
    )
    parent_code = (
        "import subprocess,sys; "
        f"subprocess.Popen([sys.executable, '-c', {child_code!r}], "
        "stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, "
        "creationflags=(subprocess.DETACHED_PROCESS if sys.platform == 'win32' else 0), "
        "start_new_session=(sys.platform != 'win32')); "
        "print('{\"ok\":true}')"
    )

    completed = run_command(
        [sys.executable, "-c", parent_code],
        "",
        tmp_path,
        os.environ.copy(),
        30,
    )
    deadline = time.monotonic() + 5
    while not marker.exists() and time.monotonic() < deadline:
        time.sleep(0.05)

    assert completed.returncode == 0
    assert marker.read_text(encoding="utf-8") == "done"


def test_tool_runtime_api_base_url_uses_connectable_local_host(monkeypatch):
    monkeypatch.setenv("TIANCE_API_HOST", "0.0.0.0")
    monkeypatch.setenv("TIANCE_API_PORT", "18080")

    assert resolve_backend_api_base_url("/api") == "http://127.0.0.1:18080/api"


def test_tool_execution_env_does_not_inherit_unrelated_process_values(tmp_path, monkeypatch):
    monkeypatch.setenv("TIANCE_PRIVATE_TOKEN", "secret")
    monkeypatch.setenv("PYTHONPATH", "C:/ambient/pythonpath")
    tool_root = _create_tool_root(tmp_path)
    completed_envs: list[dict[str, str]] = []

    def command_runner(command, input_text, cwd, env, timeout_seconds):
        completed_envs.append(env)
        return subprocess.CompletedProcess(
            command,
            returncode=0,
            stdout=dumps({"ok": True}, ensure_ascii=False),
            stderr="",
        )

    service = ToolExecutionService(
        _FakeRegistry(tool_root),
        python_executable=Path("python"),
        command_runner=command_runner,
    )

    result = service.execute(
        ChatToolCall(call_id="call-1", name="read_text_file", arguments="{}"),
        context=ToolExecutionContext(workspace_root=str(tmp_path)),
    )

    assert result.ok is True
    assert "TIANCE_PRIVATE_TOKEN" not in completed_envs[0]
    assert "C:/ambient/pythonpath" not in completed_envs[0]["PYTHONPATH"]


def test_tool_execution_rejects_invalid_arguments(tmp_path):
    service = ToolExecutionService(
        _FakeRegistry(_create_tool_root(tmp_path)),
        python_executable=Path("python"),
        command_runner=lambda *_args: subprocess.CompletedProcess([], returncode=0, stdout="{}", stderr=""),
    )

    result = service.execute(
        ChatToolCall(call_id="call-1", name="read_text_file", arguments="[1]"),
        context=ToolExecutionContext(),
    )

    assert result.ok is False
    assert result.error == "工具参数必须是 JSON 对象。"


def test_tool_execution_rejects_tool_missing_from_registry(tmp_path):
    service = ToolExecutionService(
        _FakeRegistry(_create_tool_root(tmp_path)),
        python_executable=Path("python"),
        command_runner=lambda *_args: subprocess.CompletedProcess([], returncode=0, stdout="{}", stderr=""),
    )

    result = service.execute(
        ChatToolCall(call_id="call-1", name="unknown_tool", arguments="{}"),
        context=ToolExecutionContext(),
    )

    assert result.ok is False
    assert result.error == "工具 'unknown_tool' 不存在。"


def test_tool_execution_validates_arguments_against_input_schema(tmp_path):
    tool_root = _create_tool_root(
        tmp_path,
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["file_path", "mode"],
            "properties": {
                "file_path": {"type": "string", "minLength": 1},
                "mode": {"type": "string", "enum": ["metadata", "lines"]},
                "max_chars": {"type": "integer", "minimum": 100, "maximum": 1000},
            },
        },
    )
    completed_commands: list[list[str]] = []

    def command_runner(command, *_args):
        completed_commands.append(command)
        return subprocess.CompletedProcess(command, returncode=0, stdout="{}", stderr="")

    service = ToolExecutionService(
        _FakeRegistry(tool_root),
        python_executable=Path("python"),
        command_runner=command_runner,
    )

    result = service.execute(
        ChatToolCall(
            call_id="call-1",
            name="read_text_file",
            arguments='{"file_path":"C:/work/app.py","mode":"full","extra":true,"max_chars":10}',
        ),
        context=ToolExecutionContext(),
    )

    assert result.ok is False
    assert result.error is not None
    assert result.error.startswith("工具参数校验失败：")
    assert "参数.mode 必须是 metadata, lines 之一。" in result.error
    assert "参数.extra 不是允许的参数。" in result.error
    assert "参数.max_chars 不能小于 100。" in result.error
    assert completed_commands == []


def test_tool_execution_reports_all_schema_errors(tmp_path):
    required_names = [f"field_{index}" for index in range(6)]
    tool_root = _create_tool_root(
        tmp_path,
        input_schema={
            "type": "object",
            "required": required_names,
            "properties": {name: {"type": "string"} for name in required_names},
        },
    )
    service = ToolExecutionService(
        _FakeRegistry(tool_root),
        python_executable=Path("python"),
        command_runner=lambda *_args: subprocess.CompletedProcess([], returncode=0, stdout="{}", stderr=""),
    )

    result = service.execute(
        ChatToolCall(call_id="call-1", name="read_text_file", arguments="{}"),
        context=ToolExecutionContext(),
    )

    assert result.ok is False
    assert result.error is not None
    for name in required_names:
        assert f"参数.{name} 为必填参数。" in result.error


def test_tool_execution_reports_all_enum_values(tmp_path):
    enum_values = [f"mode_{index}" for index in range(25)]
    tool_root = _create_tool_root(
        tmp_path,
        input_schema={
            "type": "object",
            "properties": {
                "mode": {"type": "string", "enum": enum_values},
            },
        },
    )
    service = ToolExecutionService(
        _FakeRegistry(tool_root),
        python_executable=Path("python"),
        command_runner=lambda *_args: subprocess.CompletedProcess([], returncode=0, stdout="{}", stderr=""),
    )

    result = service.execute(
        ChatToolCall(call_id="call-1", name="read_text_file", arguments='{"mode":"unknown"}'),
        context=ToolExecutionContext(),
    )

    assert result.ok is False
    assert result.error is not None
    assert "mode_0" in result.error
    assert "mode_24" in result.error


def test_tool_execution_reports_required_schema_parameters(tmp_path):
    tool_root = _create_tool_root(
        tmp_path,
        input_schema={
            "type": "object",
            "required": ["file_path"],
            "properties": {
                "file_path": {"type": "string"},
            },
        },
    )
    service = ToolExecutionService(
        _FakeRegistry(tool_root),
        python_executable=Path("python"),
        command_runner=lambda *_args: subprocess.CompletedProcess([], returncode=0, stdout="{}", stderr=""),
    )

    result = service.execute(
        ChatToolCall(call_id="call-1", name="read_text_file", arguments="{}"),
        context=ToolExecutionContext(),
    )

    assert result.ok is False
    assert result.error == "工具参数校验失败：参数.file_path 为必填参数。"


def test_tool_execution_reports_closed_tool_when_registry_entry_is_disabled(tmp_path):
    service = ToolExecutionService(
        _FakeRegistry(_create_tool_root(tmp_path), entry_enabled=False),
        python_executable=Path("python"),
        command_runner=lambda *_args: subprocess.CompletedProcess([], returncode=0, stdout="{}", stderr=""),
    )

    result = service.execute(
        ChatToolCall(call_id="call-1", name="read_text_file", arguments="{}"),
        context=ToolExecutionContext(),
    )

    assert result.ok is False
    assert result.error == "此工具已关闭。"


def test_tool_execution_rechecks_tool_manifest_enabled_flag(tmp_path):
    tool_root = _create_tool_root(tmp_path, enabled=False)
    completed_commands: list[list[str]] = []

    def command_runner(command, *_args):
        completed_commands.append(command)
        return subprocess.CompletedProcess(command, returncode=0, stdout="{}", stderr="")

    service = ToolExecutionService(
        _FakeRegistry(tool_root),
        python_executable=Path("python"),
        command_runner=command_runner,
    )

    result = service.execute(
        ChatToolCall(call_id="call-1", name="read_text_file", arguments="{}"),
        context=ToolExecutionContext(),
    )

    assert result.ok is False
    assert result.error == "此工具已关闭。"
    assert completed_commands == []


def test_tool_execution_injects_program_and_tool_dependency_paths(tmp_path):
    tool_root = _create_tool_root(tmp_path)
    program_root = tool_root / "program"
    dependency_root = tool_root / "dependencies" / "py313" / "site-packages"
    fake_package_root = dependency_root / "fake_tool_dependency"
    fake_package_root.mkdir(parents=True)
    (fake_package_root / "__init__.py").write_text('VALUE = "dependency-ok"\n', encoding="utf-8")
    (program_root / "helper.py").write_text(
        'def read_value():\n    return "program-ok"\n',
        encoding="utf-8",
    )
    (program_root / "main.py").write_text(
        """from tiance_runtime import run_tool
from fake_tool_dependency import VALUE
from helper import read_value


def run(payload):
    return {
        "ok": True,
        "dependency": VALUE,
        "helper": read_value(),
        "payload": payload,
    }


if __name__ == "__main__":
    run_tool(run)
""",
        encoding="utf-8",
    )

    service = ToolExecutionService(
        _FakeRegistry(tool_root),
        python_executable=Path(sys.executable),
    )

    result = service.execute(
        ChatToolCall(call_id="call-1", name="read_text_file", arguments='{"value":3}'),
        context=ToolExecutionContext(workspace_root=str(tmp_path)),
    )

    assert result.ok is True
    assert loads(result.content) == {
        "ok": True,
        "dependency": "dependency-ok",
        "helper": "program-ok",
        "payload": {"value": 3},
    }


def _create_tool_root(
    tmp_path,
    *,
    enabled: bool = True,
    input_schema: dict | None = None,
    tool_name: str = "read_text_file",
) -> Path:
    tool_root = tmp_path / "tool"
    config_root = tool_root / ".tool"
    program_root = tool_root / "program"
    config_root.mkdir(parents=True)
    program_root.mkdir(parents=True)
    (config_root / "tool.json").write_text(
        dumps(
            {
                "name": tool_name,
                "display_name": "文本读取",
                "description": "读取文件。",
                "runtime": {
                    "type": "python",
                    "entry": "program/main.py",
                    "timeout_seconds": 12,
                },
                "state": {
                    "enabled": enabled,
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (config_root / "input.schema.json").write_text(
        dumps(input_schema or {"type": "object", "properties": {}, "required": []}, ensure_ascii=False),
        encoding="utf-8",
    )
    (config_root / "output.schema.json").write_text(
        dumps({"type": "object", "properties": {}, "required": []}, ensure_ascii=False),
        encoding="utf-8",
    )
    (config_root / "examples.json").write_text("[]", encoding="utf-8")
    (program_root / "main.py").write_text("print('ok')", encoding="utf-8")
    return tool_root


class _FakeRegistry:
    def __init__(self, tool_root: Path, *, entry_enabled: bool = True) -> None:
        self._tool_root = tool_root
        self._entry_enabled = entry_enabled
        loaded_tool = load_tool(str(tool_root))
        self._metadata = ToolMetadataSnapshot(
            name=loaded_tool.name,
            manifest=loaded_tool.manifest,
            input_schema=loaded_tool.input_schema,
            output_schema=loaded_tool.output_schema,
            examples=loaded_tool.examples,
        )
        self._tool_name = loaded_tool.name

    def get_enabled_entry(self, tool_name: str):
        if tool_name != self._tool_name or not self._entry_enabled:
            return None
        return self.get_entry(tool_name)

    def get_entry(self, tool_name: str):
        if tool_name != self._tool_name:
            return None
        return ToolRegistryEntry(
            project_id="tool_1",
            category_id="toolset_1",
            category_name="基础工具",
            tool_name=tool_name,
            display_name="文本读取",
            description="读取文件。",
            keywords=(),
            enabled=self._entry_enabled,
            dynamic=False,
            root_path=str(self._tool_root),
            runtime_entry="program/main.py",
            parameter_names=(),
            example_titles=(),
            indexed_at="now",
            updated_at="now",
        )

    def get_enabled_metadata(self, tool_name: str):
        if tool_name != self._tool_name or not self._entry_enabled:
            return None
        return self._metadata

    def get_metadata(self, tool_name: str):
        if tool_name != self._tool_name:
            return None
        return self._metadata
