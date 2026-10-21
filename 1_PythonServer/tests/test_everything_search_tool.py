from importlib.util import module_from_spec, spec_from_file_location
import csv
import json
from pathlib import Path
from types import SimpleNamespace
import pytest

from app.services.tools.tool_execution_arguments import validate_tool_arguments
from app.services.tools.tool_metadata import load_tool

ROOT = Path(__file__).resolve().parents[2] / "Data/tools/17c0794d-80c1-4670-aa7c-e678f917409d"

@pytest.fixture
def tool(tmp_path, monkeypatch):
    spec = spec_from_file_location("everything_tool_test", ROOT / "program/main.py")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "STATE", tmp_path / "state")
    return module


def test_registration_and_examples():
    loaded = load_tool(str(ROOT))
    assert loaded.name == "everything_search"
    assert loaded.manifest["loading"]["dynamic"] is False
    assert not loaded.manifest["execution"]["parallel"]
    schema = json.loads((ROOT / ".tool/input.schema.json").read_text(encoding="utf-8"))
    for example in json.loads((ROOT / ".tool/examples.json").read_text(encoding="utf-8")):
        assert not validate_tool_arguments(json.loads(example["content"]), schema)
    assert validate_tool_arguments({"action": "search"}, schema)
    assert validate_tool_arguments({"action": "status", "query": "*"}, schema)
    assert validate_tool_arguments({"action": "search", "query": "*", "page_size": 5001}, schema)


def test_status_and_invalid_input_do_not_create_state(tool, monkeypatch):
    monkeypatch.setattr(tool, "running", lambda cfg: False)
    monkeypatch.setattr(tool, "es", lambda *a, **kw: SimpleNamespace(returncode=8))
    monkeypatch.setattr(tool, "database_loaded", lambda **kw: pytest.fail("未运行时不能查询索引"))
    assert tool.run({"action": "status"})["data"]["active"] is False
    assert tool.run({"action": "stop"})["ok"]
    assert not tool.STATE.exists()
    for args in [
        {"query": ""}, {"query": "*", "page_size": True},
        {"query": "*", "offset": -1}, {"query": "*", "base_path": "relative"},
        {"query": "*", "offset": 0xFFFFFFFF},
    ]:
        assert not tool.run({"action": "search", **args})["ok"]
    assert not tool.STATE.exists()


@pytest.mark.parametrize("code", [1, 4, 7, 9])
def test_command_errors_not_reported_as_empty_success(tool, monkeypatch, code):
    monkeypatch.setattr(tool, "es", lambda *a, **k: SimpleNamespace(returncode=code))
    result = tool.run({"action": "status"})
    assert result["error_info"]["details"]["exit_code"] == code


def test_missing_instance_only_code_eight(tool, monkeypatch):
    monkeypatch.setattr(tool, "es", lambda *a, **k: SimpleNamespace(returncode=8))
    assert not tool.running(tool.config())


@pytest.mark.parametrize("rows,size,offset,more,next_offset", [
    ([["C:\\资料,a.pdf", "12"], ["C:\\空目录", ""], ["C:\\z.pdf", "0"]], 2, 0, True, 2),
    ([["C:\\z.pdf", "0"]], 2, 2, False, None),
    ([], 2, 3, False, None),
])
def test_pagination_unicode_and_index_metadata(tool, monkeypatch, rows, size, offset, more, next_offset):
    monkeypatch.setattr(tool, "ensure_running", lambda cfg: False)
    monkeypatch.setattr(tool, "database_loaded", lambda **kw: True)
    def fake_es(args, cfg, **kw):
        assert kw["search_text"] == '-exit | "中文 文件"'
        assert kw["timeout"] == cfg["query_timeout_seconds"]
        assert args[args.index("-timeout") + 1] == "1"
        assert args[args.index("-viewport-offset") + 1] == str(offset)
        assert args[args.index("-viewport-count") + 1] == str(size + 1)
        with Path(args[args.index("-export-csv") + 1]).open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["Filename", "Size"])
            writer.writerows(rows)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(tool, "es", fake_es)
    result = tool.run({"action": "search", "query": '-exit | "中文 文件"', "page_size": size, "offset": offset})
    assert result["ok"], result
    data = result["data"]
    assert data["has_more"] == more and data["next_offset"] == next_offset
    assert data["count"] == min(len(rows), size)
    assert data["items"] == [{"path": p, "size_bytes": int(s) if s else None, "type": "file" if s else "directory"} for p, s in rows[:size]]
    assert not list(tool.STATE.glob("query_*"))


def test_uac_decline_is_explicit_and_no_search(tool, monkeypatch):
    monkeypatch.setattr(tool, "running", lambda cfg: False)
    def deny():
        raise tool.ToolError("ELEVATION_DECLINED", "Windows管理员授权被取消")
    monkeypatch.setattr(tool, "launch_elevated", deny)
    result = tool.run({"action": "search", "query": "*"})
    assert result["error_info"]["code"] == "ELEVATION_DECLINED"


def test_existing_instance_reused_and_stop_target_is_named(tool, monkeypatch):
    monkeypatch.setattr(tool, "running", lambda cfg: True)
    monkeypatch.setattr(tool, "launch_elevated", lambda: pytest.fail("不应重复提权"))
    assert not tool.ensure_running(tool.config())
    calls = []
    monkeypatch.setattr(tool, "es", lambda args, cfg: calls.append(args) or SimpleNamespace(returncode=0))
    assert tool.run({"action": "stop"})["ok"] and calls == [["-exit"]]


def test_es_uses_named_instance_and_private_settings(tool, monkeypatch):
    seen = []
    monkeypatch.setattr(tool.subprocess, "run", lambda argv, **kwargs: seen.append((argv, kwargs)) or SimpleNamespace(returncode=0))
    tool.es(["-exit"], tool.config())
    args, kwargs = seen[0]
    assert args[1:] == ["-instance", tool.INSTANCE, "-exit"]
    assert kwargs["env"]["APPDATA"] == str(tool.STATE / "client-settings")
    assert not kwargs.get("shell")


def test_snapshot_limits_match_schema(tool):
    cfg = tool.config()
    schema = json.loads((ROOT / ".tool/input.schema.json").read_text(encoding="utf-8"))
    field = schema["properties"]["page_size"]
    assert cfg["default_page_size"] == field["default"]
    assert cfg["max_page_size"] == field["maximum"]


def test_raw_search_preserves_syntax_and_cannot_become_es_option(tool, monkeypatch):
    seen = []
    monkeypatch.setattr(tool.subprocess, "run", lambda argv, **kwargs: seen.append((argv, kwargs)) or SimpleNamespace(returncode=0))
    query = 'ext:json | "中文 文件" -exit -export-csv C:\\unexpected.csv'
    tool.es(["-n", "3"], tool.config(), search_text=query)
    command, kwargs = seen[0]
    assert command.endswith(" -search* " + query)
    assert not kwargs.get("shell")


@pytest.mark.parametrize("ready", [True, False])
def test_status_distinguishes_running_and_index_ready(tool, monkeypatch, ready):
    monkeypatch.setattr(tool, "es", lambda *a, **kw: SimpleNamespace(returncode=0, stdout=b"1.4.1.1032\r\n"))
    monkeypatch.setattr(tool, "database_loaded", lambda **kw: ready)
    result = tool.run({"action": "status"})
    assert result["ok"]
    assert result["data"]["active"] is True
    assert result["data"]["index_ready"] is ready
    assert result["data"]["everything_version"] == "1.4.1.1032"
    assert not tool.STATE.exists()


def test_index_wait_times_out_without_submitting_search(tool, monkeypatch):
    cfg = {**tool.config(), "startup_timeout_seconds": 0.01, "poll_interval_seconds": 0.001}
    monkeypatch.setattr(tool, "ensure_running", lambda cfg: False)
    monkeypatch.setattr(tool, "database_loaded", lambda **kw: False)
    monkeypatch.setattr(tool, "es", lambda *a, **kw: pytest.fail("索引未就绪时不应发出查询"))
    with pytest.raises(tool.ToolError) as error:
        tool.search({"query": "*"}, cfg)
    assert error.value.code == "INDEX_NOT_READY"
    assert not tool.STATE.exists()


def test_index_wait_resumes_when_ready(tool, monkeypatch):
    states = iter([False, False, True])
    monkeypatch.setattr(tool, "database_loaded", lambda **kw: next(states))
    tool.wait_for_index({**tool.config(), "poll_interval_seconds": 0.001})


def test_status_ipc_failure_is_not_reported_as_loading(tool, monkeypatch):
    monkeypatch.setattr(tool, "es", lambda *a, **kw: SimpleNamespace(returncode=0, stdout=b"1.4.1.1032"))
    def unresponsive(**kw):
        raise tool.ToolError("IPC_UNRESPONSIVE", "Everything未响应索引状态查询。")
    monkeypatch.setattr(tool, "database_loaded", unresponsive)
    result = tool.run({"action": "status"})
    assert not result["ok"]
    assert result["error_info"]["code"] == "IPC_UNRESPONSIVE"


def test_database_loaded_uses_named_instance_and_bounded_ipc(tool, monkeypatch):
    class NativeCall:
        def __init__(self, fn):
            self.fn = fn
        def __call__(self, *args):
            return self.fn(*args)
    calls = []
    def find_window(name, title):
        assert name == f"EVERYTHING_TASKBAR_NOTIFICATION_({tool.INSTANCE})"
        return 123
    def send(hwnd, message, command, arg, flags, milliseconds, value):
        assert (hwnd, message, command, arg) == (123, 0x0400, 401, 0)
        assert milliseconds == 250
        calls.append(True)
        value._obj.value = 1
        return 1
    fake = SimpleNamespace(FindWindowW=NativeCall(find_window), SendMessageTimeoutW=NativeCall(send))
    monkeypatch.setattr(tool.ctypes, "WinDLL", lambda *a, **kw: fake)
    assert tool.database_loaded(timeout_seconds=0.25)
    assert calls == [True]


@pytest.mark.parametrize("query,expected", [("content:needle", "SEARCH_TIMEOUT"), (None, "COMMAND_TIMEOUT")])
def test_timeout_reports_correct_phase(tool, monkeypatch, query, expected):
    import subprocess
    def timeout(*a, **kw):
        raise subprocess.TimeoutExpired(a[0], kw["timeout"])
    monkeypatch.setattr(tool.subprocess, "run", timeout)
    with pytest.raises(tool.ToolError) as error:
        tool.es([], tool.config(), timeout=0.01, search_text=query)
    assert error.value.code == expected
    assert error.value.details["timeout_seconds"] == 0.01
