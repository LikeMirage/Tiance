"""Popup and optional UIA contracts; no input is sent to the user's desktop."""
import ctypes
import json
import queue
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.test_gui_tool_suite import (
    _load_overlay_helper, _load_program, _schema, _tool_root, mouse_preview_service, no_native_input,
)
from app.services.tools.tool_execution_arguments import validate_tool_arguments


def test_layered_capture_is_explicit_and_does_not_activate(mouse_preview_service, monkeypatch):
    helper, service, point, inputs, raw, rect = mouse_preview_service
    monkeypatch.setattr(service, "_detect_capture_mode", lambda: "exclude_from_capture")
    captures = []
    monkeypatch.setattr(helper.ImageGrab, "grab", lambda **kwargs: (captures.append(kwargs) or raw))
    service._capture_bbox(rect)
    assert captures == [{"bbox": helper.rect_ltrb(rect), "all_screens": True, "include_layered_windows": True}]
    assert not inputs


def test_explicit_untitled_hwnd_does_not_depend_on_enumeration(monkeypatch):
    helper = _load_overlay_helper()
    window = {"hwnd": 123, "title": "", "process_id": 7}
    monkeypatch.setattr(helper, "window_info", lambda hwnd, **kwargs: window)
    monkeypatch.setattr(helper, "visible_windows", lambda: pytest.fail("explicit HWND must not enumerate"))
    assert helper.resolve_window(123, None) == window


def test_window_start_does_not_activate_unless_requested(mouse_preview_service, monkeypatch):
    helper, service, point, inputs, raw, rect = mouse_preview_service
    monkeypatch.setattr(helper, "resolve_window", lambda *args: {"hwnd": 123, "title": ""})
    calls = []
    monkeypatch.setattr(helper, "activate_window", lambda *args, **kwargs: (calls.append(args) or True))
    def pid(hwnd, ptr):
        ctypes.cast(ptr, ctypes.POINTER(helper.wintypes.DWORD)).contents.value = 7
        return 1
    monkeypatch.setattr(helper.user32, "GetWindowThreadProcessId", pid)
    for activate in (None, False, True):
        args = {"action": "start", "target": "window", "hwnd": 123}
        if activate is not None:
            args["activate"] = activate
        result = service.inspect(args)
        assert result["ok"] and result["data"]["target"]["title"] == ""
    assert calls == [(123,)] and not inputs


def test_owned_popup_can_be_targeted_but_main_does_not_follow_dialog(mouse_preview_service, monkeypatch):
    helper, service, point, inputs, raw, rect = mouse_preview_service
    owners = {456: 123, 789: 456}
    monkeypatch.setattr(helper.user32, "GetWindow", lambda hwnd, kind: owners.get(hwnd, 0))
    assert helper.owned_by_window(789, 123)
    service._validate_window_target({"type": "window", "hwnd": 456, "process_id": 7})
    monkeypatch.setattr(helper.user32, "GetForegroundWindow", lambda: 456)
    with pytest.raises(helper.GuiError) as caught:
        service._validate_window_target({"type": "window", "hwnd": 123, "process_id": 7})
    assert caught.value.code == "TARGET_NOT_FOREGROUND"
    owners[123] = 789  # Malformed cycles must terminate.
    assert not helper.owned_by_window(456, 999)


def test_untitled_window_listing_and_paging(mouse_preview_service, monkeypatch):
    helper, service, *_ = mouse_preview_service
    monkeypatch.setattr(helper.user32, "IsWindowVisible", lambda hwnd: True)
    monkeypatch.setattr(helper.user32, "IsIconic", lambda hwnd: False)
    monkeypatch.setattr(helper, "window_cloak_state", lambda hwnd: (0, 0))
    monkeypatch.setattr(helper.user32, "EnumWindows", lambda callback, data: all(callback(n, data) for n in (123, 456)))
    monkeypatch.setattr(helper, "window_info", lambda hwnd: {"hwnd": hwnd, "title": "", "class_name": "Popup",
                        "process_id": 7, "owner_hwnd": 42, "rect": {"width": 100, "height": 100}})
    first = service.inspect({"action": "list_windows", "limit": 1})["data"]
    assert first["items"][0]["title"] == "" and first["total"] == 2
    assert not first["complete"] and first["next_offset"] == 1
    second = service.inspect({"action": "list_windows", "limit": 1, "offset": 1})["data"]
    assert second["items"][0]["hwnd"] == 456 and second["complete"]


@pytest.fixture
def uia_service(mouse_preview_service, monkeypatch):
    helper, service, point, inputs, raw, rect = mouse_preview_service
    monkeypatch.setattr(helper, "window_info", lambda hwnd, **kwargs: {"hwnd": hwnd, "title": "", "process_id": 7})
    # Load the dedicated adapter without starting its worker.
    with pytest.raises(helper.GuiError):
        service.uia({"action": "invalid", "gui_session_id": point["gui_session_id"]})
    adapter = service.uia_adapter
    records = [{"runtime_id": "1,2,3", "process_id": 7, "name": "输入框", "automation_id": "input",
                "control_type": "ControlType.Edit", "class_name": "Edit", "value": "原内容", "patterns": ["Value"]},
               {"runtime_id": "1,2,4", "process_id": 7, "name": "确定", "automation_id": "ok",
                "control_type": "ControlType.Button", "class_name": "Button", "patterns": ["Invoke"]}]
    calls = []
    def query(request, timeout):
        calls.append(request)
        if request["operation"] == "inspect":
            return {"ok": True, "elements": records}
        if request["operation"] == "read":
            return {"ok": True, "element": {**records[0], "value": "更新内容"}}
        return {"ok": True, "execution_status": "completed"}
    monkeypatch.setattr(adapter, "_query", query)
    yield helper, service, adapter, point, records, calls
    adapter.close()


def test_uia_paging_and_references_survive_visual_refresh(uia_service):
    helper, service, adapter, point, records, calls = uia_service
    args = {"action": "inspect", "gui_session_id": point["gui_session_id"], "limit": 1}
    first = service.uia(args)["data"]
    second = service.uia({**args, "snapshot_id": first["snapshot_id"], "offset": 1})["data"]
    assert first["total"] == 2 and not first["complete"] and second["complete"]
    assert len(calls) == 1 and second["elements"][0]["name"] == "确定"
    service.inspect({"action": "refresh", "gui_session_id": point["gui_session_id"]})
    read = service.uia({"action": "read", "gui_session_id": point["gui_session_id"], "element_id": first["elements"][0]["element_id"]})
    assert read["data"]["value"] == "更新内容"


@pytest.mark.parametrize("action", ["invoke", "set_value", "select", "toggle", "expand", "collapse", "focus"])
def test_uia_actions_use_own_contract_and_shared_result(uia_service, action):
    helper, service, adapter, point, records, calls = uia_service
    first = service.uia({"action": "inspect", "gui_session_id": point["gui_session_id"]})["data"]
    args = {"action": action, "gui_session_id": point["gui_session_id"], "element_id": first["elements"][0]["element_id"]}
    if action == "set_value":
        args["text"] = "新值"
    result = service.uia(args)
    assert calls[-1]["operation"] == action
    assert result["data"]["execution_status"] == "completed" and result["data"]["observation_status"] == "captured"
    assert result["data"]["action"]["method"] == "UIAutomation" and result["data"]["frame_id"] == 1


@pytest.mark.parametrize("status", ["not_started", "unknown"])
def test_uia_failure_keeps_uncertainty_and_does_not_retry(uia_service, monkeypatch, status):
    helper, service, adapter, point, records, calls = uia_service
    first = service.uia({"action": "inspect", "gui_session_id": point["gui_session_id"]})["data"]
    attempted = []
    def fail(request, timeout):
        attempted.append(True)
        raise helper.GuiError("UIA_TIMEOUT", "test", {"execution_status": status})
    monkeypatch.setattr(adapter, "_query", fail)
    with pytest.raises(helper.GuiError) as caught:
        service.uia({"action": "invoke", "gui_session_id": point["gui_session_id"], "element_id": first["elements"][0]["element_id"]})
    assert caught.value.details["execution_status"] == status and len(attempted) == 1
    assert service._load_session(point["gui_session_id"])["latest_frame_id"] == (-1 if status == "unknown" else 0)


def test_uia_schema_examples_and_observe_contract():
    examples = json.loads((_tool_root("gui_uia") / ".tool/examples.json").read_text(encoding="utf-8"))
    for example in examples:
        assert validate_tool_arguments(json.loads(example["content"]), _schema("gui_uia")) == []
    valid = {"action": "start", "target": "window", "hwnd": 123, "activate": False}
    assert validate_tool_arguments(valid, _schema("gui_inspect")) == []
    assert validate_tool_arguments({**valid, "activation_timeout_ms": 2000}, _schema("gui_inspect"))
    assert validate_tool_arguments({**valid, "activate": True, "activation_timeout_ms": 2000}, _schema("gui_inspect")) == []


@pytest.mark.parametrize("failure", ["blocked_write", "cancel", "broken_pipe"])
def test_uia_transport_can_interrupt_pipe_writes(uia_service, monkeypatch, failure):
    helper, service, adapter, *_ = uia_service
    released = threading.Event()
    def write(payload):
        if failure == "broken_pipe":
            raise BrokenPipeError()
        if failure == "cancel":
            service.cancel_event.set()
        released.wait(1)
    adapter.process = SimpleNamespace(stdin=SimpleNamespace(write=write, flush=lambda: None))
    adapter.responses = queue.Queue()
    monkeypatch.setattr(adapter, "_start", lambda: None)
    monkeypatch.setattr(adapter, "close", released.set)
    with pytest.raises(helper.GuiError) as caught:
        type(adapter)._query(adapter, {"operation": "invoke"}, .05)
    assert caught.value.details["execution_status"] == "unknown"
    assert released.is_set()
    assert caught.value.code == {"blocked_write": "UIA_TIMEOUT", "cancel": "GUI_RUNTIME_STOPPED",
                                 "broken_pipe": "UIA_WORKER_STOPPED"}[failure]


@pytest.mark.parametrize("stage", ["connect", "send", "receive", "invalid_response"])
def test_uia_wrapper_preserves_uncertain_rpc_outcome(monkeypatch, stage):
    module = _load_program("gui_uia")
    class Connection:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def settimeout(self, value): pass
        def sendall(self, data):
            if stage == "send": raise BrokenPipeError()
        def recv(self, count):
            if stage == "receive": raise ConnectionError()
            return b'bad json\n'
    def connect(*args, **kwargs):
        if stage == "connect": raise ConnectionError()
        return Connection()
    monkeypatch.setattr(module.socket, "create_connection", connect)
    with pytest.raises(module.ToolError) as caught:
        module.call_helper({"port": 1234}, {"action": "invoke"})
    assert caught.value.details["execution_status"] == ("not_started" if stage == "connect" else "unknown")


def test_uia_dispatch_uses_existing_lock_ownership_and_cancellation(uia_service):
    helper, service, adapter, point, *_ = uia_service
    request = {"token": service.token, "project_id": service.project_id, "session_id": service.session_id,
               "method": "uia", "payload": {"action": "inspect", "gui_session_id": point["gui_session_id"]}}
    assert service._dispatch(request)["ok"]
    for change, code in (({"session_id": "other"}, "GUI_RUNTIME_OWNED_BY_OTHER_SESSION"),
                         ({"token": "other"}, "GUI_RUNTIME_AUTH_FAILED")):
        with pytest.raises(helper.GuiError) as caught:
            service._dispatch({**request, **change})
        assert caught.value.code == code
    service.cancel_event.set()
    with pytest.raises(helper.GuiError) as caught:
        service._dispatch(request)
    assert caught.value.code == "GUI_RUNTIME_STOPPED"


def test_uia_cleanup_failure_cannot_skip_input_unlock(mouse_preview_service, monkeypatch):
    helper, service, *_ = mouse_preview_service
    events = []
    def fail(*args, **kwargs): raise RuntimeError("test cleanup failure")
    service.uia_adapter = SimpleNamespace(close=fail)
    monkeypatch.setattr(service, "_detect_capture_mode", lambda: "exclude_from_capture")
    monkeypatch.setattr(service, "_write_active_state", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("test state failure")))
    monkeypatch.setattr(service, "_uninstall_hooks", lambda: events.append("unlock"))
    monkeypatch.setattr(service, "_release_held_inputs", lambda: events.append("release"))
    monkeypatch.setattr(service, "_destroy_windows", lambda: events.append("destroy"))
    monkeypatch.setattr(service, "_cleanup_gui_sessions", lambda: events.append("cleanup"))
    with pytest.raises(RuntimeError, match="test cleanup failure"):
        service.run()
    assert events == ["unlock", "release", "destroy", "cleanup"]
