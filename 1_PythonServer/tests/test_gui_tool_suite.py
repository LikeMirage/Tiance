from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
import ctypes
from json import loads
import os
from pathlib import Path
import threading
from types import ModuleType, SimpleNamespace
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.services.tools.tool_execution_arguments import validate_tool_arguments
from app.services.tools.tool_metadata import load_tool


_ROOT = Path(__file__).resolve().parents[2]
_TOOLS = _ROOT / "Data" / "tools"
_TOOL_IDS = {
    "gui_runtime": "c7dd4066-37a6-4b1e-a67a-d39f0c6d4a21",
    "gui_inspect": "b0548165-4df0-45ff-8dd0-4f614db9812b",
    "gui_mouse": "08cb1494-bf1e-47a9-bbb5-add9c576db62",
    "gui_keyboard": "e587b268-479e-4513-bab8-f20a459d0b25",
    "gui_batch": "64893807-4ab4-432e-ae8d-f27e57ff7b54",
    "gui_uia": "2801cda8-2e87-4a50-969c-9e8067470834",
}


def _tool_root(name: str) -> Path:
    return _TOOLS / _TOOL_IDS[name]


def _schema(name: str) -> dict:
    return loads((_tool_root(name) / ".tool" / "input.schema.json").read_text(encoding="utf-8"))


def test_gui_visual_only_contract():
    context = {"gui_session_id": "gui_" + "a" * 32, "frame_id": 0}
    point = {**context, "view_id": "root", "cell_id": 1, "x": 0.5, "y": 0.5}
    mouse = {**point, "action": "click"}
    keyboard = {**context, "action": "type_text", "text": "测试文本"}
    batch = {**context, "actions": [{"type": "click", **{k: v for k, v in point.items() if k != "gui_session_id"}},
                                   {"type": "type_text", "text": "测试文本"}]}
    for name, arguments in (("gui_mouse", mouse), ("gui_keyboard", keyboard), ("gui_batch", batch)):
        assert validate_tool_arguments(arguments, _schema(name)) == []
    removed = [
        ("gui_inspect", {**context, "action": "elements"}),
        ("gui_mouse", {**context, "action": "click", "element_id": "old_reference"}),
        ("gui_mouse", {**mouse, "expected_elements": []}),
        ("gui_keyboard", {**keyboard, "element_id": "old_reference"}),
        ("gui_keyboard", {**keyboard, "action": "set_value"}),
        ("gui_batch", {**context, "actions": [{"type": "set_value", "text": "x"}]}),
        ("gui_batch", {**context, "actions": [{**batch["actions"][0], "postconditions": []}]}),
        ("gui_mouse", {**point, "action": "drag", "to": {"element_id": "old_reference"}}),
    ]
    for name, arguments in removed:
        assert validate_tool_arguments(arguments, _schema(name)), (name, arguments)
    assert not (_tool_root("gui_runtime") / "program" / "uia_bridge.ps1").exists()


def test_inspect_view_overlay_schema():
    schema = _schema("gui_inspect")
    view = {"action": "view", "gui_session_id": "gui_" + "a" * 32, "frame_id": 0, "view_id": "root"}
    for mode in ("labels+lines", "lines", "none"):
        assert validate_tool_arguments({**view, "overlay": mode}, schema) == []
    for arguments in ({**view, "overlay": "bad"}, {**view, "cell_id": 1},
                      {"action": "list_windows", "overlay": "none"},
                      {key: value for key, value in view.items() if key != "frame_id"}):
        assert validate_tool_arguments(arguments, schema)
    assert not validate_tool_arguments({"action": "activate", "gui_session_id": view["gui_session_id"],
                                        "activation_timeout_ms": 500}, schema)
    for args in ({"action": "start", "target": "screen", "activation_timeout_ms": 500},
                 {"action": "activate", "gui_session_id": view["gui_session_id"], "activation_timeout_ms": 0},
                 {"action": "activate", "gui_session_id": view["gui_session_id"], "hwnd": 123}):
        assert validate_tool_arguments(args, schema)


def _load_program(name: str) -> ModuleType:
    path = _tool_root(name) / "program" / "main.py"
    spec = spec_from_file_location(f"{name}_program_under_test", path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_overlay_helper() -> ModuleType:
    path = _tool_root("gui_runtime") / "program" / "overlay_helper.py"
    spec = spec_from_file_location("gui_overlay_helper_under_test", path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def no_native_input(monkeypatch):
    if os.name != "nt":
        yield
        return
    attempts = []
    def forbidden(*args):
        attempts.append(True)
        raise AssertionError("Tests must mock input; native SendInput is forbidden")
    monkeypatch.setattr(ctypes.windll.user32, "SendInput", forbidden)
    yield
    assert not attempts, "A test attempted to send input to the real desktop"


def test_gui_tools_are_static_serial_ui_control_tools() -> None:
    catalog = loads((_TOOLS / "catalog.json").read_text(encoding="utf-8"))
    catalog_ids = {item["project_id"] for item in catalog["projects"]}
    for name, project_id in _TOOL_IDS.items():
        loaded = load_tool(str(_tool_root(name)))
        permissions = loads((_tool_root(name) / ".tool" / "permissions.json").read_text(encoding="utf-8"))
        assert loaded.name == name
        assert loaded.manifest["loading"]["dynamic"] is False
        assert loaded.manifest["execution"]["parallel"] is False
        assert permissions["policies"]["ui_control"]["all"] == "allow"
        assert project_id in catalog_ids


@pytest.fixture
def runtime_start_probe(tmp_path, monkeypatch):
    import io
    module = _load_program("gui_runtime")
    state = {}
    class Child:
        pid = 1234
        returncode = None
        stdin = io.BytesIO()
        def poll(self):
            return self.returncode
        def terminate(self):
            state["terminated"] = True
            self.returncode = -15
        def wait(self, timeout):
            state["waited"] = True
            return self.returncode
    child = Child()
    def spawn(command, **kwargs):
        state["spawned"] = True
        state["lock_id"] = command[command.index("--lock-id") + 1]
        return child
    def saved_state():
        return {"schema_version": 1, "lock_id": state["lock_id"], "pid": child.pid,
                "status": "active", "port": 54321, "project_id": "project", "session_id": "session"}
    def status(*args):
        return {"ok": True, "data": {"active": True, "runtime_id": state["lock_id"], "pid": child.pid,
                "port": 54321, "project_id": "project", "session_id": "session",
                "input_mode": "blocked", "hooks_installed": True, "idle_timeout_seconds": 120}}
    monkeypatch.setattr(module, "STATE_PATH", tmp_path / "active-lock.json")
    monkeypatch.setattr(module, "CONTROL_ROOT", tmp_path)
    monkeypatch.setattr(module, "require_owned_state", lambda *args: None)
    monkeypatch.setattr(module.subprocess, "Popen", spawn)
    monkeypatch.setattr(module, "read_state", saved_state)
    monkeypatch.setattr(module, "process_alive", lambda pid: child.poll() is None)
    monkeypatch.setattr(module, "rpc_call", status)
    monkeypatch.setattr(module, "remove_state_if_matches", lambda *args: state.update(cleaned=True))
    yield module, state, child, tmp_path


@pytest.mark.parametrize("fault", ["read_denied", "rpc_failed", "inactive", "missing_hooks", "timeout"])
def test_start_failure_reaps_only_created_child(runtime_start_probe, monkeypatch, fault):
    module, state, child, workspace = runtime_start_probe
    if fault == "read_denied":
        def fail_read():
            raise PermissionError("simulated ACL denial")
        monkeypatch.setattr(module, "read_state", fail_read)
    elif fault == "rpc_failed":
        def fail_rpc(*args):
            raise module.ToolError("GUI_RUNTIME_UNAVAILABLE", "simulated disconnect")
        monkeypatch.setattr(module, "rpc_call", fail_rpc)
    elif fault in {"inactive", "missing_hooks"}:
        original_rpc = module.rpc_call
        def bad_status(*args):
            result = original_rpc(*args)
            result["data"]["active" if fault == "inactive" else "hooks_installed"] = False
            return result
        monkeypatch.setattr(module, "rpc_call", bad_status)
    else:
        monkeypatch.setattr(module, "STARTUP_TIMEOUT_SECONDS", -1)
    with pytest.raises(module.ToolError) as failure:
        module.start_lock(workspace, "project", "session")
    assert state["spawned"] and state.get("terminated") and state.get("waited")
    assert failure.value.details["pid"] == child.pid
    assert failure.value.details["process_alive"] is False
    assert failure.value.details["released"] is True


def test_start_success_confirms_child_and_requires_real_lock(runtime_start_probe):
    module, state, child, workspace = runtime_start_probe
    result = module.start_lock(workspace, "project", "session")
    assert result["ok"] and result["data"]["active"] and result["data"]["hooks_installed"]
    assert child.stdin.closed
    assert not state.get("terminated")


@pytest.mark.skipif(os.name != "nt", reason="Windows startup IPC integration")
def test_startup_confirmation_over_real_pipes_without_desktop_lock(tmp_path, monkeypatch):
    # Exercise the real child process, state file and authenticated RPC; replace only desktop hooks/windows.
    module = _load_program("gui_runtime")
    helper_path = _tool_root("gui_runtime") / "program/overlay_helper.py"
    entry = tmp_path / "headless_gui_helper.py"
    entry.write_text(
        "import importlib.util\n"
        f"spec=importlib.util.spec_from_file_location('headless_gui', {str(helper_path)!r})\n"
        "m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
        "service=m.GuiService(m.parse_args())\n"
        "service._create_windows=lambda:None\n"
        "service._destroy_windows=lambda:None\n"
        "service._detect_capture_mode=lambda:'exclude_from_capture'\n"
        "service._install_hooks=lambda:(setattr(service,'mouse_hook',1),setattr(service,'keyboard_hook',1))\n"
        "service._uninstall_hooks=lambda:(setattr(service,'mouse_hook',0),setattr(service,'keyboard_hook',0))\n"
        "raise SystemExit(service.run())\n", encoding="utf-8")
    monkeypatch.setattr(module, "CONTROL_ROOT", tmp_path / "control")
    monkeypatch.setattr(module, "STATE_PATH", tmp_path / "control/active-lock.json")
    monkeypatch.delenv("TIANCE_API_BASE_URL", raising=False)
    popen = module.subprocess.Popen
    processes = []
    def spawn(command, **kwargs):
        command = [str(entry) if item == str(helper_path) else item for item in command]
        process = popen(command, **kwargs)
        processes.append(process)
        return process
    monkeypatch.setattr(module.subprocess, "Popen", spawn)
    try:
        result = module.start_lock(tmp_path, "test-project", "test-session")
        assert result["ok"] and result["data"]["pid"] == processes[0].pid
        saved = module.read_state()
        assert module.rpc_call(saved, "status")["data"]["active"]
        assert module.rpc_call(saved, "unlock")["ok"]
        assert processes[0].wait(timeout=3) == 0
        assert not module.STATE_PATH.exists()
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=3)


@pytest.mark.parametrize("name", list(_TOOL_IDS))
def test_process_query_denied_is_unknown_not_dead(name, monkeypatch):
    module = _load_program(name)
    monkeypatch.setattr(module.kernel32, "OpenProcess", lambda *args: 0)
    monkeypatch.setattr(module.kernel32, "GetLastError", lambda: 5)
    with pytest.raises(module.ToolError) as failure:
        module.process_alive(1234)
    assert failure.value.code == "GUI_RUNTIME_PROCESS_STATUS_UNKNOWN"
    assert failure.value.details["active"] is None


def test_state_permission_preflight_prevents_child_creation(runtime_start_probe, monkeypatch):
    module, state, child, workspace = runtime_start_probe
    def denied(*args, **kwargs):
        raise PermissionError("simulated inherited ACL")
    monkeypatch.setattr(Path, "write_bytes", denied)
    with pytest.raises(module.ToolError) as failure:
        module.start_lock(workspace, "project", "session")
    assert failure.value.code == "GUI_RUNTIME_STATE_ACCESS_FAILED"
    assert failure.value.details["process_created"] is False
    assert not state.get("spawned")


def test_unreadable_state_is_never_deleted_as_if_owned(runtime_start_probe, monkeypatch):
    module, state, child, workspace = runtime_start_probe
    # Restore the actual cleanup function; the fixture otherwise spies on it.
    actual = _load_program("gui_runtime")
    monkeypatch.setattr(actual, "STATE_PATH", workspace / "active-lock.json")
    def denied():
        raise actual.ToolError("GUI_RUNTIME_STATE_ACCESS_FAILED", "denied")
    monkeypatch.setattr(actual, "read_state", denied)
    monkeypatch.setattr(Path, "unlink", lambda *args, **kwargs: pytest.fail("must not remove unverified state"))
    with pytest.raises(actual.ToolError):
        actual.remove_state_if_matches("a-different-lock")


def test_start_reports_unconfirmed_release_if_child_cannot_be_reaped(runtime_start_probe, monkeypatch):
    module, state, child, workspace = runtime_start_probe
    monkeypatch.setattr(module, "STARTUP_TIMEOUT_SECONDS", -1)
    def denied():
        raise PermissionError("termination denied")
    monkeypatch.setattr(child, "terminate", denied)
    with pytest.raises(module.ToolError) as failure:
        module.start_lock(workspace, "project", "session")
    assert failure.value.details["released"] is False
    assert failure.value.details["active"] is None
    assert failure.value.details["process_alive"] is True
    assert not state.get("cleaned")


def test_existing_inactive_runtime_is_not_claimed_as_success_or_killed(runtime_start_probe, monkeypatch):
    module, state, child, workspace = runtime_start_probe
    state["lock_id"] = "existing-lock"
    saved = module.read_state()
    saved["input_mode"] = "blocked"
    monkeypatch.setattr(module, "require_owned_state", lambda *args: saved)
    monkeypatch.setattr(module, "rpc_call", lambda *args: {"ok": True, "data": {"active": False}})
    with pytest.raises(module.ToolError) as failure:
        module.start_lock(workspace, "project", "session")
    assert failure.value.code == "GUI_LOCK_NOT_CONFIRMED"
    assert not state.get("spawned") and not state.get("terminated")


def test_atomic_state_replace_failure_preserves_destination(tmp_path, monkeypatch):
    helper = _load_overlay_helper()
    path = tmp_path / "active-lock.json"
    path.write_text('{"lock_id":"existing-lock"}', encoding="utf-8")
    def denied(*args):
        raise PermissionError("simulated replace denial")
    monkeypatch.setattr(helper.os, "replace", denied)
    with pytest.raises(PermissionError):
        helper.atomic_json(path, {"lock_id": "new-lock"})
    assert loads(path.read_text(encoding="utf-8")) == {"lock_id": "existing-lock"}
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("name", ["gui_inspect", "gui_mouse", "gui_keyboard", "gui_batch"])
def test_wrapper_permission_error_does_not_claim_unlocked(name, tmp_path, monkeypatch):
    module = _load_program(name)
    monkeypatch.setenv("TIANCE_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("TIANCE_PROJECT_ID", "project")
    monkeypatch.setenv("TIANCE_SESSION_ID", "session")
    def denied(*args, **kwargs):
        raise PermissionError("simulated ACL")
    monkeypatch.setattr(Path, "read_text", denied)
    result = module.run({})
    assert result["error_info"]["code"] == "GUI_RUNTIME_STATE_ACCESS_FAILED"
    assert result["error_info"]["details"]["active"] is None


def test_gui_coordinate_and_action_contracts_reject_incomplete_calls() -> None:
    gui_id = "gui_" + "0" * 32
    mouse_schema = _schema("gui_mouse")
    keyboard_schema = _schema("gui_keyboard")
    batch_schema = _schema("gui_batch")
    runtime_schema = _schema("gui_runtime")

    assert runtime_schema["properties"]["action"]["enum"] == ["start", "status", "stop"]
    assert "preview" in mouse_schema["properties"]["action"]["enum"]
    assert mouse_schema["properties"]["click_hold_ms"]["default"] == 80
    assert batch_schema["properties"]["actions"]["items"]["properties"]["click_hold_ms"]["default"] == 80

    assert validate_tool_arguments(
        {
            "action": "click",
            "gui_session_id": gui_id,
            "frame_id": 0,
            "view_id": "root",
            "cell_id": 1,
            "x": 0.5,
            "y": 0.5,
        },
        mouse_schema,
    ) == []
    assert validate_tool_arguments(
        {
            "action": "preview",
            "preview_action": "click",
            "gui_session_id": gui_id,
            "frame_id": 0,
            "view_id": "root",
            "cell_id": 1,
            "x": 0.5,
            "y": 0.5,
        },
        mouse_schema,
    ) == []
    assert validate_tool_arguments(
        {
            "action": "drag",
            "gui_session_id": gui_id,
            "frame_id": 0,
            "view_id": "root",
            "cell_id": 1,
            "x": 0.5,
            "y": 0.5,
        },
        mouse_schema,
    )
    assert validate_tool_arguments(
        {"action": "type_text", "gui_session_id": gui_id},
        keyboard_schema,
    )
    assert validate_tool_arguments(
        {"gui_session_id": gui_id, "actions": []},
        batch_schema,
    )


@pytest.mark.skipif(os.name != "nt", reason="GUI工具只支持Windows")
def test_click_hold_releases_mouse_button_when_interrupted() -> None:
    helper = _load_overlay_helper()

    class FakeMouse:
        _button = staticmethod(helper.GuiService._button)

        def __init__(self, *, interrupt: bool) -> None:
            self.interrupt = interrupt
            self.events: list[tuple] = []

        def _mouse_move(self, x: int, y: int, duration_ms: int) -> None:
            self.events.append(("move", x, y, duration_ms))

        def _mouse_flag(self, flag: int, data: int = 0, *, button: str | None = None, allow_cancelled: bool = False) -> None:
            self.events.append(("flag", flag, button, allow_cancelled))

        def _interruptible_sleep(self, seconds: float) -> None:
            self.events.append(("sleep", seconds))
            if self.interrupt:
                raise RuntimeError("cancelled")

    normal = FakeMouse(interrupt=False)
    helper.GuiService._mouse_click(normal, 10, 20, "left", 1, 120, 80)
    assert ("sleep", 0.08) in normal.events
    assert normal.events[-1] == ("flag", helper.MOUSEEVENTF_LEFTUP, "left", True)

    interrupted = FakeMouse(interrupt=True)
    with pytest.raises(RuntimeError, match="cancelled"):
        helper.GuiService._mouse_click(interrupted, 10, 20, "left", 1, 120, 80)
    assert interrupted.events[-1] == ("flag", helper.MOUSEEVENTF_LEFTUP, "left", True)


@pytest.mark.skipif(os.name != "nt", reason="GUI工具只支持Windows")
def test_coordinate_preview_marks_point_without_creating_frame(tmp_path: Path) -> None:
    helper = _load_overlay_helper()
    frame_folder = tmp_path / "frame_000"
    frame_folder.mkdir()
    overlay_path = frame_folder / "root_overlay.png"
    helper.Image.new("RGB", (100, 80), (20, 30, 40)).save(overlay_path)
    view = {
        "view_id": "root",
        "source_rect_absolute": {"left": 100, "top": 200, "width": 100, "height": 80},
        "parent_view_id": None,
        "overlay": {"requested": "none", "effective": "none", "labels_visible": False,
                    "labels_hidden_reason": None, "font_size_px": 0, "line_width_px": 0,
                    "numbering": "row_major_top_left_1_based"},
        "grid": {"rows": 1, "columns": 1},
        "cells": [{"cell_id": 1, "rect_absolute": {"left": 100, "top": 200, "width": 100, "height": 80}}],
        "overlay_image": "frame_000/root_overlay.png",
        "image_size": {"width": 100, "height": 80},
        "zoom_scale_percent": 100,
    }
    frame = {
        "frame_id": 0,
        "foreground_window": {"hwnd": 123, "process_id": 7, "exists": True},
        "capture_rect": {"left": 100, "top": 200, "width": 100, "height": 80},
        "views": {"root": view},
    }
    session = {"gui_session_id": "gui_" + "0" * 32, "target": {"type": "screen"}}

    class FakePreview:
        _view = staticmethod(helper.GuiService._view)
        _result_with_image = helper.GuiService._result_with_image
        _show_activity_view = helper.GuiService._show_activity_view
        _publish_activity = helper.GuiService._publish_activity
        external_mouse_events = 0
        external_keyboard_events = 0
        cancel_event = threading.Event()
        block_user_input = True

        @staticmethod
        def _session_dir(_gui_session_id: str) -> Path:
            return tmp_path

    result = helper.GuiService._preview_coordinate(
        FakePreview(),
        session=session,
        frame=frame,
        arguments={"view_id": "root", "cell_id": 1, "x": 0.25, "y": 0.375},
        screen_x=125,
        screen_y=250,
        mouse_before=0,
        keyboard_before=0,
    )

    assert result["data"]["frame_id"] == 0
    assert result["data"]["performed"] is False
    assert result["data"]["previewed"] is True
    assert result["data"]["selected_coordinate"]["screen_x"] == 125
    preview_path = Path(result["image_path"])
    assert preview_path.parent == frame_folder
    with helper.Image.open(preview_path) as preview:
        assert preview.getpixel((25, 50)) == helper.COORDINATE_PREVIEW_COLOR


@pytest.mark.skipif(os.name != "nt", reason="GUI工具只支持Windows")
def test_gui_tools_require_explicit_lock_and_never_relock_after_user_exit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TIANCE_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("TIANCE_PROJECT_ID", "project")
    monkeypatch.setenv("TIANCE_SESSION_ID", "session")
    missing_state = tmp_path / "missing-runtime-state.json"
    for name in ("gui_inspect", "gui_mouse", "gui_keyboard", "gui_batch"):
        module = _load_program(name)
        monkeypatch.setattr(module, "STATE_PATH", missing_state)
        result = module.run({})
        assert result["ok"] is False
        assert result["error_info"]["code"] == "GUI_LOCK_REQUIRED"


@pytest.mark.skipif(os.name != "nt", reason="GUI工具只支持Windows")
@pytest.mark.parametrize("first_scale,second_scale,expected_size", [(100, 400, (401, 299)), (400, 600, (802, 599)), (800, 100, (402, 300))])
def test_nested_zoom_preview_and_input_share_physical_point(tmp_path: Path, first_scale: int, second_scale: int, expected_size: tuple[int, int], monkeypatch: pytest.MonkeyPatch) -> None:
    helper = _load_overlay_helper()
    service = helper.GuiService.__new__(helper.GuiService)
    service.gui_root = tmp_path
    service.lock_id = "test_lock"
    service.external_mouse_events = service.external_keyboard_events = 0
    service.cancel_event = threading.Event()
    service.block_user_input = True
    service.held_mouse_buttons = set()
    gui_id = "gui_" + "a" * 32
    folder = service._session_dir(gui_id)
    folder.mkdir()
    raw = helper.Image.linear_gradient("L").resize((802, 602)).convert("RGB")
    source = {"left": -500, "top": -300, "width": 802, "height": 602}
    session = {"gui_session_id": gui_id, "lock_id": service.lock_id, "status": "active", "target": {"type": "screen"}, "frames": []}
    service._create_frame(session, reason="test", raw=raw, source_rect=source, grid_mode="fixed", grid_rows=2, grid_cols=2)
    first = service.inspect({"action": "zoom", "gui_session_id": gui_id, "frame_id": 0, "view_id": "root", "cell_id": 4, "grid_mode": "fixed", "grid_rows": 2, "grid_cols": 2, "zoom_scale_percent": first_scale})
    second = service.inspect({"action": "zoom", "gui_session_id": gui_id, "frame_id": 0, "view_id": first["data"]["view_id"], "cell_id": 2, "grid_mode": "fixed", "grid_rows": 2, "grid_cols": 2, "zoom_scale_percent": second_scale})
    session = service._load_session(gui_id)
    point_args = {"frame_id": 0, "view_id": second["data"]["view_id"], "cell_id": 3, "x": 0.3, "y": 0.7}
    frame, x, y = service._resolve_point(session, point_args)
    assert (x, y) == (131, 98)
    view = frame["views"][point_args["view_id"]]
    assert view["source_rect_absolute"] == {"left": 101, "top": 1, "width": 201, "height": 150}
    with helper.Image.open(folder / view["raw_image"]) as cropped:
        assert cropped.size == (201, 150)
        assert cropped.tobytes() == raw.crop((601, 301, 802, 451)).tobytes()
    preview = service._preview_coordinate(session=session, frame=frame, arguments=point_args, screen_x=x, screen_y=y, mouse_before=0, keyboard_before=0)
    with helper.Image.open(preview["image_path"]) as marked:
        first_view = frame["views"][first["data"]["view_id"]]
        assert marked.size == expected_size
        assert marked.width <= first_view["image_size"]["width"]
        assert marked.height <= first_view["image_size"]["height"]
        marker = preview["data"]["marker"]
        assert marked.getpixel((marker["center_x"], marker["center_y"])) == helper.COORDINATE_PREVIEW_COLOR
        assert int(marker["center_x"] * 201 / marked.width) + 101 == x
        assert int(marker["center_y"] * 150 / marked.height) + 1 == y
    sent = []
    monkeypatch.setattr(service, "_virtual_metrics", lambda: (-500, -300, 3000, 2000))
    monkeypatch.setattr(service, "_send_input", lambda event: sent.append(event))
    service.marker = 123
    service._mouse_move_event(x, y)
    assert sent[0].mi.dx * 3000 // 65536 - 500 == x
    assert sent[0].mi.dy * 2000 // 65536 - 300 == y


@pytest.mark.skipif(os.name != "nt", reason="GUI工具只支持Windows")
def test_lock_blocks_all_user_mouse_input_and_only_escape_exits(monkeypatch: pytest.MonkeyPatch) -> None:
    helper = _load_overlay_helper()
    service = helper.GuiService.__new__(helper.GuiService)
    service.marker = 123
    service.mouse_hook = service.keyboard_hook = 0
    service.block_user_input = True
    service.external_mouse_events = service.external_keyboard_events = 0
    service.blocked_mouse_events = service.blocked_keyboard_events = 0
    service.held_mouse_buttons = set()
    stopped = []
    service.request_stop = stopped.append
    monkeypatch.setattr(helper.user32, "CallNextHookEx", lambda *args: 47)
    mouse = helper.MSLLHOOKSTRUCT(pt=helper.POINT(120, 220), dwExtraInfo=0)
    address = ctypes.addressof(mouse)
    assert service._mouse_hook(0, helper.WM_MOUSEMOVE, address) == 1
    assert service._mouse_hook(0, 0x020A, address) == 1  # WM_MOUSEWHEEL
    assert service._mouse_hook(0, helper.WM_LBUTTONDOWN, address) == 1
    assert stopped == []
    assert service._mouse_hook(0, helper.WM_LBUTTONUP, address) == 1
    assert stopped == []
    mouse.dwExtraInfo = 123
    assert service._mouse_hook(0, helper.WM_LBUTTONUP, address) == 47
    assert stopped == []
    assert service.external_mouse_events == 0
    assert service.blocked_mouse_events == 4
    key = helper.KBDLLHOOKSTRUCT(vkCode=helper.VK_CODES["esc"])
    key.dwExtraInfo = 123
    assert service._keyboard_hook(0, helper.WM_KEYUP, ctypes.addressof(key)) == 47
    assert stopped == []
    key.dwExtraInfo = 0
    assert service._keyboard_hook(0, helper.WM_KEYDOWN, ctypes.addressof(key)) == 1
    assert service._keyboard_hook(0, helper.WM_KEYUP, ctypes.addressof(key)) == 1
    assert stopped[-1] == "user_escape"
    assert service.external_keyboard_events == 0
    assert service.blocked_keyboard_events == 2


@pytest.mark.skipif(os.name != "nt", reason="GUI工具只支持Windows")
def test_preflight_keeps_geometry_check_without_taking_screenshot(mouse_preview_service, monkeypatch):
    helper, service, point, inputs, raw, rect = mouse_preview_service
    session = service._load_session(point["gui_session_id"])
    monkeypatch.setattr(service, "_capture_target", lambda target: pytest.fail("preflight must not capture pixels"))
    assert service._preflight(session)[1] == rect
    rect["width"] += 1
    with pytest.raises(helper.GuiError) as failure:
        service._preflight(session)
    assert failure.value.code == "TARGET_GEOMETRY_CHANGED" and not inputs


@pytest.mark.skipif(os.name != "nt", reason="GUI工具只支持Windows")
def test_grid_rejects_empty_pixel_cells_and_move_verifies_actual_pointer(monkeypatch: pytest.MonkeyPatch) -> None:
    helper = _load_overlay_helper()
    with pytest.raises(helper.GuiError, match="原始屏幕像素"):
        helper.build_cells({"left": 0, "top": 0, "width": 3, "height": 3}, 4, 4)
    service = helper.GuiService.__new__(helper.GuiService)
    monkeypatch.setattr(helper.user32, "GetCursorPos", lambda point: 0)
    with pytest.raises(helper.GuiError) as failure:
        service._verify_mouse_position(500, 500)
    assert failure.value.code == "POINTER_POSITION_MISMATCH"


@pytest.fixture
def mouse_preview_service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    helper = _load_overlay_helper()
    service = helper.GuiService(SimpleNamespace(workspace=str(tmp_path), state_file=str(tmp_path / "active.json"), lock_id="lock_test", token="test", marker=123, project_id="project", session_id="session"))
    gui_id = "gui_" + "a" * 32
    raw = helper.Image.new("RGB", (400, 300), (20, 30, 40))
    rect = {"left": 100, "top": 200, "width": 400, "height": 300}
    session = {"gui_session_id": gui_id, "lock_id": service.lock_id, "status": "active", "target": {"type": "screen"}, "frames": []}
    monkeypatch.setattr(service, "_native_focus", lambda: 123)
    monkeypatch.setattr(helper.user32, "GetForegroundWindow", lambda: 123)
    monkeypatch.setattr(helper, "foreground_window", lambda: {"hwnd": int(helper.user32.GetForegroundWindow()),
                         "process_id": 7, "exists": True, "title": "Test window", "rect": rect.copy()})
    monkeypatch.setattr(helper, "window_diagnostics", lambda hwnd: {"hwnd": hwnd, "process_id": 7, "exists": True})
    monkeypatch.setattr(service, "_target_rect", lambda target: rect.copy())
    monkeypatch.setattr(helper, "drag_window_snapshot", lambda excluded: [
        {"hwnd": 123, "pid": 7, "thread_id": 8, "rect": rect.copy()},
    ])
    monkeypatch.setattr(helper.user32, "WindowFromPoint", lambda point: 123)
    monkeypatch.setattr(helper.user32, "GetAncestor", lambda hwnd, flags: hwnd)
    raw.info["drag_windows"] = helper.drag_window_snapshot([])
    service._create_frame(session, reason="test", raw=raw, source_rect=rect, grid_mode="fixed", grid_rows=2, grid_cols=2)
    monkeypatch.setattr(service, "_capture_target", lambda target: (raw, rect.copy()))
    # 此fixture只验证动作合同；等待时钟由专门的取消测试覆盖。
    monkeypatch.setattr(service, "_interruptible_sleep", lambda seconds: None)
    inputs = []

    def spy(name):
        def execute(*args, **kwargs):
            inputs.append((name, args, kwargs))
            service.input_events_sent += 1
        return execute

    for name in ("_mouse_move", "_mouse_click", "_mouse_drag", "_mouse_scroll", "_mouse_flag", "_key_event", "_send_input"):
        monkeypatch.setattr(service, name, spy(name))
    point = {"gui_session_id": gui_id, "frame_id": 0, "view_id": "root", "cell_id": 1, "x": 0.3, "y": 0.6}
    try:
        yield helper, service, point, inputs, raw, rect
    finally:
        service.server_socket.close()


@pytest.mark.parametrize("tool", ["gui_mouse", "gui_keyboard", "gui_batch"])
def test_screenshot_delay_schema(tool) -> None:
    field = _schema(tool)["properties"]["screenshot_delay_seconds"]
    assert (field["type"], field["minimum"], field["maximum"], field["default"]) == ("number", 0, 30, 1)


@pytest.mark.parametrize("method", ["mouse", "keyboard", "batch"])
@pytest.mark.parametrize("delay", [None, 0, 2.5, 30])
def test_action_waits_once_before_final_capture(mouse_preview_service, monkeypatch, method, delay) -> None:
    _helper, service, point, inputs, raw, rect = mouse_preview_service
    events = []
    monkeypatch.setattr(service, "_interruptible_sleep", lambda seconds: events.append(("wait", seconds)))
    monkeypatch.setattr(service, "_capture_target", lambda target: (events.append(("capture", len(inputs))) or (raw, rect.copy())))
    monkeypatch.setattr(service, "_press_key", lambda *args: inputs.append(("key", args)))
    arguments = {
        "mouse": {**point, "action": "click"},
        "keyboard": {"gui_session_id": point["gui_session_id"], "frame_id": 0, "action": "press_key", "key": "a"},
        "batch": {"gui_session_id": point["gui_session_id"], "frame_id": 0, "actions": [{"type": "press_key", "key": "a"}, {"type": "press_key", "key": "b"}]},
    }[method]
    if delay is not None:
        arguments["screenshot_delay_seconds"] = delay
    result = getattr(service, method)(arguments)
    expected = 1 if delay is None else delay
    assert events == [("wait", expected), ("capture", len(inputs))]
    assert inputs and result["data"]["screenshot_delay_seconds"] == expected


@pytest.mark.parametrize("method", ["mouse", "keyboard", "batch"])
@pytest.mark.parametrize("delay", [-1, 31, True, "1", float("nan"), float("inf")])
def test_invalid_delay_rejected_before_input(mouse_preview_service, method, delay) -> None:
    helper, service, point, inputs, _raw, _rect = mouse_preview_service
    with pytest.raises(helper.GuiError) as failure:
        getattr(service, method)({**point, "action": "click", "screenshot_delay_seconds": delay})
    assert failure.value.code == "INVALID_ARGUMENT" and inputs == []


def test_preview_freezes_delay_without_waiting_or_repeating(mouse_preview_service, monkeypatch) -> None:
    _helper, service, point, inputs, _raw, _rect = mouse_preview_service
    waits = []
    monkeypatch.setattr(service, "_interruptible_sleep", waits.append)
    preview = service.mouse({**point, "action": "preview", "preview_action": "click", "screenshot_delay_seconds": 2.5})
    assert waits == [] and inputs == []
    assert preview["data"]["operation"]["screenshot_delay_seconds"] == 2.5
    execute = {"action": "execute_preview", "preview_id": preview["data"]["preview_id"]}
    service.mouse(execute)
    service.mouse(execute)
    assert waits == [2.5]


def test_escape_cancels_screenshot_wait_without_capturing(mouse_preview_service, monkeypatch) -> None:
    helper, service, point, _inputs, raw, rect = mouse_preview_service
    waiting = threading.Event()
    captured = []
    monkeypatch.setattr(service, "_capture_target", lambda target: (captured.append(True) or (raw, rect)))
    def wait(seconds):
        assert seconds == 30
        waiting.set()
        helper.GuiService._interruptible_sleep(service, seconds)
    monkeypatch.setattr(service, "_interruptible_sleep", wait)
    monkeypatch.setattr(helper.user32, "PostThreadMessageW", lambda *args: 1)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(service.mouse, {**point, "action": "click", "screenshot_delay_seconds": 30})
        assert waiting.wait(2)
        key = helper.KBDLLHOOKSTRUCT(vkCode=helper.VK_CODES["esc"])
        service._keyboard_hook(0, helper.WM_KEYUP, ctypes.addressof(key))
        result = future.result(timeout=1)
        assert result["data"]["execution_status"] == "completed"
        assert result["data"]["observation_error"]["code"] == "GUI_RUNTIME_STOPPED"
        assert not result["data"]["interface_state"]["lock_active"]
    assert captured == []  # 退出后不再截图，但已经执行的点击仍准确报告。
    with pytest.raises(helper.GuiError):
        helper.GuiService._interruptible_sleep(service, 0)


def test_mouse_preview_schema_and_examples_are_explicit() -> None:
    schema = _schema("gui_mouse")
    point = {"gui_session_id": "gui_" + "a" * 32, "frame_id": 0, "view_id": "root", "cell_id": 1, "x": 0.5, "y": 0.5}
    execute = {"action": "execute_preview", "preview_id": "preview_" + "a" * 32 + "_" + "b" * 32}
    assert not validate_tool_arguments(execute, schema)
    assert validate_tool_arguments({**execute, "x": 0.1}, schema)
    assert validate_tool_arguments({"action": "preview", **point}, schema)
    assert validate_tool_arguments({"action": "preview", "preview_action": "drag", **point}, schema)
    for example in loads((_tool_root("gui_mouse") / ".tool/examples.json").read_text(encoding="utf-8")):
        assert not validate_tool_arguments(loads(example["content"]), schema), example["title"]


@pytest.mark.skipif(os.name != "nt", reason="GUI工具只支持Windows")
@pytest.mark.parametrize("action,options", [
    ("move", {"duration_ms": 50}),
    ("click", {}),
    ("click", {"button": "right", "clicks": 2, "click_hold_ms": 130, "modifiers": ["ctrl"]}),
    ("drag", {"to": {"view_id": "root", "cell_id": 4, "x": 0.5, "y": 0.5}, "duration_ms": 100}),
    ("scroll", {"direction": "down", "notches": 2}),
    ("mouse_down", {"button": "left"}),
    ("mouse_up", {"button": "left"}),
])
def test_preview_freezes_full_mouse_action_and_retries_do_not_execute_again(mouse_preview_service, action, options) -> None:
    helper, service, point, inputs, _raw, _rect = mouse_preview_service
    preview = service.mouse({"action": "preview", "preview_action": action, **point, **options})
    data = preview["data"]
    assert data["preview_status"] == "pending"
    assert data["frame_id"] == 0 and not data["performed"] and inputs == []
    assert data["operation"]["action"] == action
    for key in helper.MOUSE_ACTION_OPTIONS[action]:
        assert data["operation"][key] == options.get(key, helper.MOUSE_ACTION_DEFAULTS[key])
    for key, default in helper.MOUSE_ACTION_DEFAULTS.items():
        assert default == _schema("gui_mouse")["properties"][key]["default"]
    execute = {"action": "execute_preview", "preview_id": data["preview_id"]}
    result = service.mouse(execute)
    assert result["ok"] and result["data"]["performed"]
    assert result["data"]["execution_status"] == "completed"
    assert result["data"]["frame_id"] == 1
    assert result["data"]["action"]["type"] == action
    if action == "click":
        called = next(item for item in inputs if item[0] == "_mouse_click")
        assert called[1][2:] == (data["operation"]["button"], data["operation"]["clicks"], data["operation"]["interval_ms"], data["operation"]["click_hold_ms"])
    count = len(inputs)
    repeated = service.mouse(execute)
    assert repeated["data"]["preview_reused"] and len(inputs) == count
    assert repeated["image_path"] == result["image_path"]


@pytest.mark.skipif(os.name != "nt", reason="GUI工具只支持Windows")
def test_preview_drag_between_zoom_views_shows_both_endpoints(mouse_preview_service) -> None:
    helper, service, point, inputs, _raw, _rect = mouse_preview_service
    for cell in (1, 4):
        service.inspect({"action": "zoom", "gui_session_id": point["gui_session_id"], "frame_id": 0, "view_id": "root", "cell_id": cell})
    result = service.mouse({**point, "action": "preview", "preview_action": "drag", "view_id": "1", "cell_id": 1, "to": {"view_id": "4", "cell_id": 1, "x": 0.5, "y": 0.5}})
    assert result["data"]["view_id"] == "root" and inputs == []
    assert "change_check_scope" not in result["data"]["operation"]
    with helper.Image.open(result["image_path"]) as image:
        start = result["data"]["marker"]
        assert image.getpixel((start["center_x"], start["center_y"])) == helper.COORDINATE_PREVIEW_COLOR
        marker = result["data"]["end_marker"]
        assert image.getpixel((marker["center_x"], marker["center_y"])) == (0, 220, 255)


@pytest.mark.parametrize("mode", ["direct", "preview", "batch"])
def test_drag_ignores_unrelated_pixels_and_returns_new_screenshot(mouse_preview_service, monkeypatch, mode):
    helper, service, point, inputs, raw, rect = mouse_preview_service
    changed = helper.Image.new("RGB", raw.size, "white")
    monkeypatch.setattr(service, "_capture_target", lambda target: (changed, rect.copy()))
    item = {**point, "action": "drag", "to": {"view_id": "root", "cell_id": 4, "x": 0.5, "y": 0.5}}
    # Action control no longer compares screenshot pixels.
    comparisons = []
    original_difference = helper.image_difference_percent
    monkeypatch.setattr(helper, "image_difference_percent", lambda a, b: (comparisons.append(True) or original_difference(a, b)))
    if mode == "preview":
        result = service.mouse({**item, "action": "preview", "preview_action": "drag"})
        assert comparisons == [] and inputs == []
        result = service.mouse({"action": "execute_preview", "preview_id": result["data"]["preview_id"]})
    elif mode == "batch":
        result = service.batch({**point, "actions": [{**item, "type": "drag"}]})
    else:
        result = service.mouse(item)
    assert result["data"]["performed"] and result["data"]["frame_id"] == 1
    assert Path(result["image_path"]).is_file()
    assert [item[0] for item in inputs] == ["_mouse_drag"]
    assert comparisons == []
    details = result["data"]["action"]
    if mode == "batch":
        details = details["actions"][0]
    assert "change_check_scope" not in details


@pytest.mark.parametrize("mode", ["direct", "preview", "batch"])
@pytest.mark.parametrize("change", ["move", "resize", "pid", "thread", "closed", "occluded", "hit", "missing", "stale", "cancelled"])
def test_drag_changed_origin_never_sends_input(mouse_preview_service, monkeypatch, mode, change):
    helper, service, point, inputs, _raw, rect = mouse_preview_service
    item = {**point, "action": "drag", "to": {"view_id": "root", "cell_id": 4, "x": 0.5, "y": 0.5}}
    if mode == "preview":
        preview = service.mouse({**item, "action": "preview", "preview_action": "drag"})
    windows = [{"hwnd": 123, "pid": 7, "thread_id": 8, "rect": rect.copy()}]
    if change == "move":
        windows[0]["rect"]["left"] += 1
    elif change == "resize":
        windows[0]["rect"]["width"] += 1
    elif change in {"pid", "thread"}:
        windows[0]["pid" if change == "pid" else "thread_id"] += 1
    elif change == "closed":
        windows.clear()
    elif change == "occluded":
        windows.insert(0, {"hwnd": 456, "pid": 9, "thread_id": 10, "rect": rect.copy()})
    elif change == "hit":
        monkeypatch.setattr(helper.user32, "WindowFromPoint", lambda point: 456)
    elif change == "cancelled":
        service.cancel_event.set()
    else:
        session = service._load_session(point["gui_session_id"])
        if change == "stale":
            session["latest_frame_id"] = 1
        else:
            session["frames"][0].pop("drag_windows")
        service._save_session(session)
    monkeypatch.setattr(helper, "drag_window_snapshot", lambda excluded: windows)
    try:
        if mode == "preview":
            result = service.mouse({"action": "execute_preview", "preview_id": preview["data"]["preview_id"]})
        elif mode == "batch":
            result = service.batch({**point, "actions": [{**item, "type": "drag"}, {"type": "press_key", "key": "enter"}]})
        else:
            result = service.mouse(item)
    except helper.GuiError as exc:
        assert exc.code in {"DRAG_ORIGIN_CHANGED", "DRAG_ORIGIN_OCCLUDED", "DRAG_ORIGIN_UNCONFIRMED", "STALE_FRAME", "GUI_RUNTIME_STOPPED"}
        if mode == "batch" and change not in {"stale", "cancelled"}:
            assert exc.details["completed_actions"] == 0
    else:
        assert mode == "preview" and not result.get("data", {}).get("performed", False)
    assert inputs == []


def test_drag_rechecks_origin_after_moving_pointer_before_button_down(mouse_preview_service, monkeypatch):
    helper, service, point, inputs, _raw, _rect = mouse_preview_service
    monkeypatch.setattr(service, "_mouse_drag", helper.GuiService._mouse_drag.__get__(service))
    def move(*args):
        monkeypatch.setattr(helper.user32, "WindowFromPoint", lambda point: 456)
    monkeypatch.setattr(service, "_mouse_move", move)
    with pytest.raises(helper.GuiError, match="起点实际命中"):
        service.mouse({**point, "action": "drag", "to": {"view_id": "root", "cell_id": 4, "x": 0.5, "y": 0.5}})
    assert inputs == []


def test_drag_frame_preserves_capture_time_window_evidence(mouse_preview_service, monkeypatch):
    helper, service, point, _inputs, raw, rect = mouse_preview_service
    monkeypatch.setattr(service, "_target_rect", lambda target: rect.copy())
    def capture(bbox):
        # A popup appears just after the pixels were acquired, before saving the frame.
        monkeypatch.setattr(helper, "drag_window_snapshot", lambda excluded: [
            {"hwnd": 456, "pid": 9, "thread_id": 10, "rect": rect.copy()},
        ])
        return raw.copy()
    monkeypatch.setattr(service, "_capture_bbox", capture)
    image, captured_rect = helper.GuiService._capture_target(service, {"type": "screen"})
    session = service._load_session(point["gui_session_id"])
    frame, _ = service._create_frame(session, reason="test", raw=image, source_rect=captured_rect)
    assert frame["drag_windows"][0]["hwnd"] == 123
    with pytest.raises(helper.GuiError) as failure:
        service._check_drag_origin(frame, 160, 260)
    assert failure.value.code == "DRAG_ORIGIN_CHANGED"


@pytest.fixture
def native_physical_gui():
    helper = _load_overlay_helper()
    with helper.physical_coordinates():
        yield helper


@pytest.mark.skipif(
    os.name != "nt" or os.environ.get("TIANCE_TEST_GUI_NATIVE") != "1",
    reason="Set TIANCE_TEST_GUI_NATIVE=1 for native desktop hit-testing",
)
def test_native_drag_origin_ignores_own_overlay_and_detects_untitled_occluder(tmp_path, monkeypatch, native_physical_gui):
    # Show only small, nonactivating test windows; never install hooks or inject input.
    helper = native_physical_gui
    service = helper.GuiService(SimpleNamespace(workspace=str(tmp_path), state_file=str(tmp_path / "active.json"),
        lock_id="lock_test", token="test", marker=123, project_id="project", session_id="session"))
    rect = {"left": 40, "top": 80, "width": 320, "height": 200}
    monkeypatch.setattr(helper, "monitor_rects", lambda: [rect])
    native = helper.user32
    handles = []
    def create():
        hwnd = native.CreateWindowExW(helper.WS_EX_TOPMOST | helper.WS_EX_NOACTIVATE | helper.WS_EX_TOOLWINDOW,
            "BUTTON", "", helper.WS_POPUP, rect["left"], rect["top"], rect["width"], rect["height"], 0, 0, 0, None)
        assert hwnd
        handles.append(hwnd)
        native.ShowWindow(hwnd, helper.SW_SHOWNOACTIVATE)
        return hwnd
    try:
        original = create()
        frame = {"drag_windows": helper.drag_window_snapshot([])}
        assert service._check_drag_origin(frame, 100, 180)["hwnd"] == original
        service._create_windows()
        # Hit-test from the same worker-thread arrangement used by GUI RPC handling.
        def check_origin():
            with helper.physical_coordinates():
                return service._check_drag_origin(frame, 100, 180)

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(check_origin)
            while not future.done():
                message = helper.wintypes.MSG()
                while native.PeekMessageW(ctypes.byref(message), 0, 0, 0, 1):
                    native.TranslateMessage(ctypes.byref(message))
                    native.DispatchMessageW(ctypes.byref(message))
                threading.Event().wait(0.01)
            assert future.result()["hwnd"] == original
        create()  # An untitled popup is still a real occluder.
        with pytest.raises(helper.GuiError) as failure:
            service._check_drag_origin(frame, 100, 180)
        assert failure.value.code == "DRAG_ORIGIN_OCCLUDED"
    finally:
        service._destroy_windows()
        for hwnd in reversed(handles):
            native.DestroyWindow(hwnd)
        if getattr(service, "overlay_class", None):
            native.UnregisterClassW.argtypes = [helper.wintypes.LPCWSTR, helper.wintypes.HINSTANCE]
            native.UnregisterClassW(service.overlay_class, helper.kernel32.GetModuleHandleW(None))
        service.server_socket.close()


def test_pixel_changes_do_not_block_click_or_mixed_batch(mouse_preview_service, monkeypatch):
    helper, service, point, inputs, raw, rect = mouse_preview_service
    changed = helper.Image.new("RGB", raw.size, "white")
    monkeypatch.setattr(service, "_capture_target", lambda target: (changed, rect.copy()))
    result = service.batch({**point, "actions": [
        {**point, "type": "drag", "to": {"view_id": "root", "cell_id": 4, "x": 0.5, "y": 0.5}},
        {**point, "type": "click"},
    ]})
    assert result["data"]["performed"] and len(inputs) == 2
    # Use the new frame; another pixel change still does not block the click.
    monkeypatch.setattr(service, "_capture_target", lambda target: (raw, rect.copy()))
    result = service.mouse({**point, "frame_id": 1, "action": "click"})
    assert result["data"]["performed"] and len(inputs) == 3


@pytest.mark.skipif(os.name != "nt", reason="GUI工具只支持Windows")
@pytest.mark.parametrize("change", ["new_frame", "window_move", "window_resize"])
def test_preview_expiry_never_inputs_and_returns_current_frame(mouse_preview_service, monkeypatch: pytest.MonkeyPatch, change: str) -> None:
    helper, service, point, inputs, raw, rect = mouse_preview_service
    if change.startswith("window"):
        session = service._load_session(point["gui_session_id"])
        session["target"] = {"type": "window", "hwnd": 42, "process_id": 7}
        service._save_session(session)
        monkeypatch.setattr(helper, "window_rect", lambda hwnd: rect.copy())
        monkeypatch.setattr(helper.user32, "GetForegroundWindow", lambda: 42)
    preview = service.mouse({**point, "action": "preview", "preview_action": "click"})
    if change == "new_frame":
        service._create_frame(service._load_session(point["gui_session_id"]), reason="refresh", raw=raw, source_rect=rect)
    elif change == "window_move":
        rect["left"] += 10
    else:
        rect["width"] += 10
        monkeypatch.setattr(service, "_capture_target", lambda target: (raw.resize((410, 300)), rect.copy()))
    result = service.mouse({"action": "execute_preview", "preview_id": preview["data"]["preview_id"]})
    assert result["data"]["preview_status"] == "expired"
    assert not result["data"]["performed"] and inputs == []
    assert result["data"]["execution_status"] == "not_started"
    assert result["data"]["frame_id"] > 0 and Path(result["image_path"]).is_file()


@pytest.mark.skipif(os.name != "nt", reason="GUI工具只支持Windows")
def test_preview_concurrent_claim_uses_existing_serial_execution_boundary(mouse_preview_service) -> None:
    _helper, service, point, inputs, _raw, _rect = mouse_preview_service
    preview = service.mouse({**point, "action": "preview", "preview_action": "click"})
    request = {"token": service.token, "project_id": service.project_id, "session_id": service.session_id, "method": "mouse", "payload": {"action": "execute_preview", "preview_id": preview["data"]["preview_id"]}}
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(service._dispatch, [request, request]))
    assert len([item for item in inputs if item[0] == "_mouse_click"]) == 1
    assert sorted(result["data"]["preview_reused"] for result in results) == [False, True]


@pytest.mark.skipif(os.name != "nt", reason="GUI工具只支持Windows")
@pytest.mark.parametrize("after_input", [False, True])
def test_preview_failure_preserves_execution_progress_and_never_replays(mouse_preview_service, monkeypatch: pytest.MonkeyPatch, after_input: bool) -> None:
    helper, service, point, inputs, _raw, _rect = mouse_preview_service
    preview = service.mouse({**point, "action": "preview", "preview_action": "click"})
    execute = {"action": "execute_preview", "preview_id": preview["data"]["preview_id"]}

    def interrupted(*args):
        inputs.append("attempt")
        if after_input:
            service.input_events_sent += 2
        raise helper.GuiError("USER_INPUT_INTERRUPTED", "检测到外部输入")

    monkeypatch.setattr(service, "_mouse_click", interrupted)
    result = service.mouse(execute)
    assert not result["ok"]
    assert result["data"]["performed"] is after_input
    assert result["data"]["execution_status"] == ("partial" if after_input else "not_started")
    assert result["data"]["interface_state"]["observation_only"]
    assert Path(result["image_path"]).is_file()
    repeated = service.mouse(execute)
    assert repeated["data"]["preview_reused"] and inputs == ["attempt"]


@pytest.mark.skipif(os.name != "nt", reason="GUI工具只支持Windows")
def test_preview_completed_input_with_failed_result_capture_is_not_repeated(mouse_preview_service, monkeypatch: pytest.MonkeyPatch) -> None:
    helper, service, point, inputs, _raw, _rect = mouse_preview_service
    preview = service.mouse({**point, "action": "preview", "preview_action": "click"})

    def failed_capture(**kwargs):
        raise helper.GuiError("CAPTURE_FAILED", "截图失败")

    monkeypatch.setattr(service, "_finish_action", failed_capture)
    execute = {"action": "execute_preview", "preview_id": preview["data"]["preview_id"]}
    result = service.mouse(execute)
    assert not result["ok"] and result["data"]["execution_status"] == "completed"
    assert service.mouse(execute)["data"]["preview_reused"] and len(inputs) == 1


@pytest.mark.skipif(os.name != "nt", reason="GUI工具只支持Windows")
def test_preview_rejects_overrides_foreign_owner_invalid_id_and_unsettled_claim(mouse_preview_service) -> None:
    helper, service, point, inputs, _raw, _rect = mouse_preview_service
    preview = service.mouse({**point, "action": "preview", "preview_action": "click"})
    execute = {"action": "execute_preview", "preview_id": preview["data"]["preview_id"]}
    for invalid in ({**execute, "x": 0.9}, {**execute, "preview_id": "../outside"}):
        with pytest.raises(helper.GuiError):
            service.mouse(invalid)
    with pytest.raises(helper.GuiError):
        service._dispatch({"token": service.token, "project_id": "other", "session_id": service.session_id, "method": "mouse", "payload": execute})
    path = service._session_dir(point["gui_session_id"]) / "previews" / f"{execute['preview_id']}.json"
    record = helper.read_json(path)
    record["status"] = "executing"
    helper.atomic_json(path, record)
    with pytest.raises(helper.GuiError) as failure:
        service.mouse(execute)
    assert failure.value.code == "PREVIEW_ALREADY_CLAIMED"
    assert inputs == []


@pytest.mark.skipif(os.name != "nt", reason="GUI工具只支持Windows")
def test_mouse_wrapper_keeps_failed_action_image_and_progress(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_program("gui_mouse")
    helper = _load_overlay_helper()
    image = tmp_path / ".Tiance/gui-temp/gui_test/failed.png"
    image.parent.mkdir(parents=True)
    helper.Image.new("RGB", (20, 20)).save(image)
    response = {"ok": False, "error": "interrupted", "error_info": {"code": "USER_INPUT_INTERRUPTED"}, "data": {"execution_status": "partial", "performed": True}, "image_path": str(image)}
    monkeypatch.setattr(module, "context_and_state", lambda: (tmp_path, {}))
    monkeypatch.setattr(module, "call_helper", lambda state, payload: response)
    result = module.run({})
    assert not result["ok"] and result["data"]["execution_status"] == "partial"
    assert result["content"][0]["type"] == "resource_link"


@pytest.mark.skipif(os.name != "nt", reason="GUI工具只支持Windows")
@pytest.mark.parametrize("size,dpi", [((1440, 900), 96), ((1920, 1080), 144), ((1080, 1920), 192)])
def test_lock_overlay_keeps_working_area_transparent(size, dpi):
    helper = _load_overlay_helper()
    image = helper.render_lock_overlay(*size, dpi)
    width, height = size
    alpha = image.getchannel("A")
    assert image.mode == "RGBA" and image.size == size
    # No full-screen dimming/grid/watermark; the entire interior below the notice is clear.
    edge = round(30 * dpi / 96)
    assert alpha.crop((edge, round(80 * dpi / 96), width - edge, height - edge)).getbbox() is None
    assert alpha.getpixel((0, height // 2)) > alpha.getpixel((round(8 * dpi / 96), height // 2)) > 0
    assert alpha.getpixel((width // 2, round(30 * dpi / 96))) > 0
    background = helper.Image.new("RGBA", size, (230, 240, 250, 255))
    composed = helper.Image.alpha_composite(background, image)
    assert composed.getpixel((width // 2, height // 2)) == background.getpixel((width // 2, height // 2))


def test_lock_overlay_uploads_to_hidden_native_window_and_releases_gdi(monkeypatch):
    helper = _load_overlay_helper()
    service = helper.GuiService.__new__(helper.GuiService)
    service.window_proc = helper.WNDPROC(service._window_proc)
    service.overlay_windows = []
    service.cancel_event = threading.Event()
    service.lock_started_at = None
    service.last_notice_second = 0
    monkeypatch.setattr(helper, "monitor_rects", lambda: [{"left": -900, "top": -600, "width": 640, "height": 400}])
    monkeypatch.setattr(helper.user32, "ShowWindow", lambda *args: True)
    helper.user32.GetWindow.argtypes = [helper.wintypes.HWND, helper.wintypes.UINT]
    helper.user32.GetWindow.restype = helper.wintypes.HWND
    deleted = []
    delete_dc = helper.gdi32.DeleteDC
    def track_delete(dc):
        deleted.append(dc)
        return delete_dc(dc)
    monkeypatch.setattr(helper.gdi32, "DeleteDC", track_delete)
    try:
        service._create_windows()
        hwnd = service.overlay_windows[0]
        child = helper.user32.GetWindow(hwnd, 5)  # GW_CHILD
        assert child
        service._exclude_window_from_capture(hwnd)
        assert not helper.user32.IsWindowVisible(hwnd)
        assert len(deleted) == 2  # Static glow and independently updated notice.
        notice = service.overlay_notices[0][0]
        host_bounds, notice_bounds = helper.wintypes.RECT(), helper.wintypes.RECT()
        assert helper.user32.GetWindowRect(hwnd, ctypes.byref(host_bounds))
        assert helper.user32.GetWindowRect(notice, ctypes.byref(notice_bounds))
        assert notice_bounds.top == host_bounds.top
        assert notice_bounds.left == host_bounds.left + (640 - (notice_bounds.right - notice_bounds.left)) // 2
        # Exercise native WM_TIMER delivery and a real small-layer upload, while
        # all test windows stay hidden and no input hooks are installed.
        updates, stops = [], []
        update = service._update_lock_notice
        def track_notice(hwnd, rect, elapsed):
            updates.append(elapsed)
            update(hwnd, rect, elapsed)
        monkeypatch.setattr(service, "_update_lock_notice", track_notice)
        monkeypatch.setattr(service, "request_stop", stops.append)
        service.lock_started_at = helper.time.monotonic() - 60
        service._start_overlay_timer()
        deadline = helper.time.monotonic() + 3
        while not updates and not stops and helper.time.monotonic() < deadline:
            message = helper.wintypes.MSG()
            if helper.user32.PeekMessageW(ctypes.byref(message), hwnd, helper.WM_TIMER, helper.WM_TIMER, 1):
                helper.user32.DispatchMessageW(ctypes.byref(message))
            else:
                threading.Event().wait(0.01)
        assert not stops and updates and updates[0] >= 60
        assert len(deleted) == 3
        # Exercise the new layers in the real window message loop, still hidden.
        rect = {"left": -800, "top": -450, "width": 320, "height": 200}
        observation = {"gui_session_id": "gui_test", "frame_id": 0, "view_id": "1", "depth": 1,
                       "valid": True, "source_rect_absolute": rect, "grid": {"rows": 2, "columns": 2},
                       "cells": helper.build_cells(rect, 2, 2)}
        service._publish_activity(observation=observation, pointer={"x": -650, "y": -350, "phase": "pressed"},
                                  action={"tool": "mouse", "name": "click", "phase": "completed"})
        message = helper.wintypes.MSG()
        assert helper.user32.PeekMessageW(ctypes.byref(message), hwnd, helper.WM_APP_ACTIVITY, helper.WM_APP_ACTIVITY, 1)
        helper.user32.DispatchMessageW(ctypes.byref(message))
        assert not stops and len(deleted) == 6  # Grid, small pointer, notice.
        pointer = service.overlay_pointers[0][0]
        pointer_bounds = helper.wintypes.RECT()
        assert helper.user32.GetWindowRect(pointer, ctypes.byref(pointer_bounds))
        dpi = helper.user32.GetDpiForWindow(pointer)
        _, pad = helper.render_activity_pointer(dpi, {"phase": "pressed"})
        assert (pointer_bounds.left + pad, pointer_bounds.top + pad) == (-650, -350)
        assert helper.user32.GetAncestor(pointer, 2) == hwnd
        assert not helper.user32.IsWindowVisible(pointer)
        service._exclude_window_from_capture(hwnd)
        monkeypatch.setattr(helper.user32, "UpdateLayeredWindow", lambda *args: False)
        with pytest.raises(helper.GuiError) as failure:
            service._update_overlay(child, {"left": 0, "top": 0, "width": 640, "height": 400})
        assert failure.value.code == "OVERLAY_RENDER_FAILED"
        assert len(deleted) == 7
    finally:
        service._destroy_windows()
        assert not service.overlay_windows
        helper.user32.UnregisterClassW.argtypes = [helper.wintypes.LPCWSTR, helper.wintypes.HINSTANCE]
        helper.user32.UnregisterClassW(service.overlay_class, helper.kernel32.GetModuleHandleW(None))


def test_capture_mode_does_not_toggle_overlay_or_compare_live_animation(monkeypatch: pytest.MonkeyPatch) -> None:
    helper = _load_overlay_helper()
    service = helper.GuiService.__new__(helper.GuiService)
    changes = []
    service._show_overlays = changes.append
    rect = {"left": 0, "top": 0, "width": 100, "height": 100, "primary": True}
    monkeypatch.setattr(helper, "monitor_rects", lambda: [rect])
    frames = iter([helper.Image.new("RGB", (100, 100), "red"), helper.Image.new("RGB", (100, 100), "blue")])
    captures = []

    def capture(**kwargs):
        captures.append(kwargs)
        return next(frames)

    def composition_enabled(pointer):
        ctypes.cast(pointer, ctypes.POINTER(helper.wintypes.BOOL)).contents.value = True
        return 0

    monkeypatch.setattr(helper.ImageGrab, "grab", capture)
    monkeypatch.setattr(helper.dwmapi, "DwmIsCompositionEnabled", composition_enabled)
    assert service._detect_capture_mode() == "exclude_from_capture"
    assert captures == []
    assert changes == []


def test_gui_examples_match_current_input_contracts():
    for name in _TOOL_IDS:
        loaded = load_tool(str(_tool_root(name)))
        for _, example in loaded.examples:
            assert validate_tool_arguments(loads(example["content"]), loaded.input_schema) == [], (name, example["title"])


@pytest.mark.parametrize("owner_result", ["different_run", "disconnected"])
def test_owner_end_or_change_releases_even_during_action(mouse_preview_service, monkeypatch, owner_result):
    helper, service, *_ = mouse_preview_service
    monkeypatch.setattr(helper.user32, "PostThreadMessageW", lambda *args: True)
    service.owner_status_url = "test://owner"
    service.owner_run_id = "original_run"
    def read():
        if owner_result == "disconnected":
            raise OSError("disconnected")
        return owner_result
    monkeypatch.setattr(service, "_read_owner_run", read)
    with service.service_lock:
        watcher = threading.Thread(target=service._watch_lifecycle)
        watcher.start()
        watcher.join(2)
        assert not watcher.is_alive()
    assert service.cancel_event.is_set()
    assert service.stop_reason in {"owner_run_changed", "owner_stopped_or_disconnected"}


@pytest.mark.parametrize("advance", ["click", "refresh"])
def test_zoom_view_from_previous_frame_reports_recovery(mouse_preview_service, advance):
    helper, service, point, inputs, _raw, _rect = mouse_preview_service
    old_zoom = service.inspect({**point, "action": "zoom", "grid_mode": "fixed", "grid_rows": 2, "grid_cols": 2})
    if advance == "click":
        latest = service.mouse({**point, "action": "click"})
    else:
        latest = service.inspect({"action": "refresh", "gui_session_id": point["gui_session_id"]})
    frame_id = latest["data"]["frame_id"]
    input_count = len(inputs)
    with pytest.raises(helper.GuiError) as failure:
        service.inspect({**point, "action": "zoom", "frame_id": frame_id,
                         "view_id": old_zoom["data"]["view_id"]})
    assert failure.value.code == "VIEW_NOT_FOUND"
    assert failure.value.details == {
        "frame_id": frame_id, "requested_view_id": old_zoom["data"]["view_id"],
        "available_view_ids": ["root"],
    }
    assert "root" in failure.value.message
    assert len(inputs) == input_count
    session = service._load_session(point["gui_session_id"])
    assert session["latest_frame_id"] == frame_id
    assert list(session["frames"][-1]["views"]) == ["root"]
    recovered = service.inspect({**point, "action": "zoom", "frame_id": frame_id, "view_id": "root"})
    assert recovered["data"]["frame_id"] == frame_id


def test_zoom_cell_selection_uses_source_grid_and_reports_valid_cells(mouse_preview_service):
    helper, service, point, inputs, _raw, _rect = mouse_preview_service
    selection = {k: point[k] for k in ("gui_session_id", "frame_id", "view_id")}
    with pytest.raises(helper.GuiError) as failure:
        service.inspect({**selection, "action": "zoom", "cell_ids": [1, 2, 4, 5, 7, 8],
                         "grid_mode": "fixed", "grid_rows": 3, "grid_cols": 3})
    assert failure.value.code == "CELL_NOT_FOUND"
    assert failure.value.details == {
        "view_id": "root", "requested_cell_id": 5,
        "grid": {"rows": 2, "columns": 2}, "available_cell_ids": [1, 2, 3, 4],
    }
    assert inputs == []
    session = service._load_session(point["gui_session_id"])
    assert list(session["frames"][-1]["views"]) == ["root"]
    recovered = service.inspect({**selection, "action": "zoom", "cell_ids": [1, 2],
                                 "grid_mode": "fixed", "grid_rows": 3, "grid_cols": 3})
    assert recovered["data"]["grid"] == {"rows": 3, "columns": 3}
    assert recovered["data"]["source_rect_absolute"] == {
        "left": 100, "top": 200, "width": 400, "height": 150,
    }


def test_rectangle_zoom_preserves_preview_and_grid(mouse_preview_service):
    helper, service, point, inputs, raw, rect = mouse_preview_service
    preview = service.mouse({**point, "action": "preview", "preview_action": "click"})
    zoom = service.inspect({**{k: point[k] for k in ("gui_session_id", "frame_id", "view_id")},
                            "action": "zoom", "cell_ids": [1, 2], "grid_mode": "fixed",
                            "grid_rows": 4, "grid_cols": 5})
    assert zoom["data"]["frame_id"] == 0
    session = service._load_session(point["gui_session_id"])
    assert session["frames"][0]["views"][zoom["data"]["view_id"]]["source_rect_absolute"] == {
        "left": 100, "top": 200, "width": 400, "height": 150}
    assert session["grid_settings"]["grid_rows"] == 2
    with pytest.raises(helper.GuiError) as failure:
        service.inspect({**point, "action": "zoom", "cell_ids": [1, 2, 3]})
    assert failure.value.code == "NON_RECTANGULAR_SELECTION"
    executed = service.mouse({"action": "execute_preview", "preview_id": preview["data"]["preview_id"]})
    assert executed["data"]["performed"] and len(inputs) == 1
    session = service._load_session(point["gui_session_id"])
    assert len(session["frames"][-1]["views"]["root"]["cells"]) == 4
    service.inspect({"action": "refresh", "gui_session_id": point["gui_session_id"],
                     "grid_mode": "fixed", "grid_rows": 3, "grid_cols": 5})
    service.inspect({"action": "refresh", "gui_session_id": point["gui_session_id"]})
    session = service._load_session(point["gui_session_id"])
    assert len(session["frames"][-1]["views"]["root"]["cells"]) == 15


def test_idle_status_busy_action_and_pending_work(mouse_preview_service, monkeypatch):
    helper, service, point, inputs, raw, rect = mouse_preview_service
    service.last_activity = 100
    service.idle_timeout_seconds = 20
    monkeypatch.setattr(helper.user32, "PostThreadMessageW", lambda *args: True)
    service.status()
    assert service.last_activity == 100
    with service.service_lock:
        thread = threading.Thread(target=service._check_idle, args=(121,))
        thread.start()
        thread.join(1)
        assert not service.cancel_event.is_set()
    service._check_idle(119)
    assert not service.cancel_event.is_set()
    service._check_idle(121)
    assert service.cancel_event.is_set() and service.stop_reason == "idle_timeout"
    with pytest.raises(helper.GuiError) as failure:
        service._dispatch({"token": service.token, "project_id": service.project_id,
                           "session_id": service.session_id, "method": "mouse",
                           "payload": {**point, "action": "click"}})
    assert failure.value.code == "GUI_RUNTIME_STOPPED"
    assert inputs == []


@pytest.mark.parametrize("stage", ["starting", "active"])
def test_helper_state_write_failure_always_releases_hooks(mouse_preview_service, monkeypatch, stage):
    helper, service, *_ = mouse_preview_service
    events = []
    write = service._write_active_state
    def publish(status, **kwargs):
        if status in {stage, "failed"}:
            raise PermissionError("simulated state write ACL")
        return write(status, **kwargs)
    def install():
        events.append("install")
        service.mouse_hook = service.keyboard_hook = 321
    def uninstall():
        events.append("uninstall")
        service.mouse_hook = service.keyboard_hook = 0
    monkeypatch.setattr(service, "_write_active_state", publish)
    monkeypatch.setattr(service, "_detect_capture_mode", lambda: "exclude_from_capture")
    monkeypatch.setattr(service, "_create_windows", lambda: events.append("overlay"))
    monkeypatch.setattr(service, "_install_hooks", install)
    monkeypatch.setattr(service, "_uninstall_hooks", uninstall)
    monkeypatch.setattr(service, "_destroy_windows", lambda: events.append("destroy"))
    assert service.run() == 1
    assert not service.mouse_hook and not service.keyboard_hook
    assert events[-2:] == ["uninstall", "destroy"]
    assert ("install" in events) == (stage == "active")


@pytest.mark.parametrize("reason", ["caller_exit", "confirmation_timeout"])
def test_unconfirmed_start_releases_on_caller_exit_or_timeout(mouse_preview_service, monkeypatch, reason):
    import io
    helper, service, *_ = mouse_preview_service
    monkeypatch.setattr(helper.user32, "PostThreadMessageW", lambda *args: True)
    service.startup_confirmed.clear()
    if reason == "caller_exit":
        monkeypatch.setattr(helper.sys, "stdin", io.StringIO(""))
        service._receive_startup_confirmation()
        assert service.stop_reason == "startup_caller_disconnected"
    else:
        service.startup_deadline = 0
        service._watch_lifecycle()
        assert service.stop_reason == "startup_confirmation_timeout"
    assert service.cancel_event.is_set()


def test_activate_window_refreshes_frame_and_expires_preview(mouse_preview_service, monkeypatch):
    helper, service, point, inputs, raw, rect = mouse_preview_service
    session = service._load_session(point["gui_session_id"])
    session["target"] = {"type": "window", "hwnd": 123, "process_id": 7}
    service._save_session(session)
    foreground = [123]
    def pid(hwnd, pointer):
        ctypes.cast(pointer, ctypes.POINTER(helper.wintypes.DWORD)).contents.value = 7
        return 1
    monkeypatch.setattr(helper.user32, "GetWindowThreadProcessId", pid)
    monkeypatch.setattr(helper.user32, "IsWindow", lambda hwnd: True)
    monkeypatch.setattr(helper.user32, "GetForegroundWindow", lambda: foreground[0])
    monkeypatch.setattr(helper, "window_rect", lambda hwnd: rect.copy())
    preview = service.mouse({**point, "action": "preview", "preview_action": "click"})
    foreground[0] = 456
    def activate(hwnd, **kwargs):
        foreground[0] = hwnd
        return True
    monkeypatch.setattr(helper, "activate_window", activate)
    result = service.inspect({"action": "activate", "gui_session_id": point["gui_session_id"]})
    assert result["data"]["frame_id"] == 1 and foreground[0] == 123
    assert service._load_session(point["gui_session_id"])["grid_settings"]["grid_rows"] == 2
    expired = service.mouse({"action": "execute_preview", "preview_id": preview["data"]["preview_id"]})
    assert not expired["ok"] and expired["error_info"]["code"] == "STALE_FRAME"
    assert inputs == []


def test_screen_capture_survives_unknown_focus_but_keyboard_does_not(mouse_preview_service, monkeypatch):
    helper, service, point, inputs, raw, rect = mouse_preview_service
    def unavailable():
        raise helper.GuiError("GUI_FOCUS_UNAVAILABLE", "focus unavailable", {"winerror": 5})
    monkeypatch.setattr(service, "_native_focus", unavailable)
    session = service._load_session(point["gui_session_id"])
    frame, image = service._create_frame(session, reason="focus_missing", raw=raw, source_rect=rect)
    assert image.exists() and frame["focus_window"] is None
    assert frame["focus_error"]["details"]["winerror"] == 5
    result = service._result_with_image(summary="test", session=session, frame=frame,
                                       view=frame["views"]["root"], image_path=image)
    assert result["ok"] and result["data"]["focus"]["hwnd"] is None and result["warnings"]
    with pytest.raises(helper.GuiError) as failure:
        service.keyboard({"action": "press_key", "key": "enter", "gui_session_id": point["gui_session_id"],
                          "frame_id": frame["frame_id"]})
    assert failure.value.code == "GUI_FOCUS_UNAVAILABLE"
    assert inputs == []


def test_window_list_omits_shell_cloaked_windows(monkeypatch):
    helper = _load_overlay_helper()
    monkeypatch.setattr(helper.user32, "EnumWindows", lambda callback, data: callback(123, data))
    monkeypatch.setattr(helper.user32, "IsWindowVisible", lambda hwnd: True)
    monkeypatch.setattr(helper.user32, "IsIconic", lambda hwnd: False)
    monkeypatch.setattr(helper.user32, "GetWindowTextLengthW", lambda hwnd: 4)
    monkeypatch.setattr(helper.user32, "GetWindowTextW", lambda hwnd, buf, size: setattr(buf, "value", "Test"))
    monkeypatch.setattr(helper, "window_rect", lambda hwnd: {"left": 0, "top": 0, "width": 100, "height": 80})
    def cloaked(hwnd, attribute, output, size):
        ctypes.cast(output, ctypes.POINTER(helper.wintypes.DWORD)).contents.value = 2
        return 0
    monkeypatch.setattr(helper.dwmapi, "DwmGetWindowAttribute", cloaked)
    assert helper.visible_windows() == []


@pytest.fixture
def activation_probe(monkeypatch):
    helper = _load_overlay_helper()
    clock = [0.0]
    calls = []
    foreground = [456]
    target = {"hwnd": 123, "exists": True, "visible": True, "minimized": False,
              "cloaked": 0, "process_id": 7, "thread_id": 8}
    monkeypatch.setattr(helper, "window_diagnostics", lambda hwnd: dict(target) if hwnd == 123 else {"hwnd": hwnd})
    monkeypatch.setattr(helper, "desktop_diagnostics", lambda: {"input": {"name": "Default"}})
    monkeypatch.setattr(helper.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(helper.time, "sleep", lambda value: clock.__setitem__(0, clock[0] + value))
    monkeypatch.setattr(helper.user32, "GetForegroundWindow", lambda: foreground[0])
    def pid(hwnd, output):
        if output is not None:
            ctypes.cast(output, ctypes.POINTER(helper.wintypes.DWORD)).contents.value = 7
        return 8
    monkeypatch.setattr(helper.user32, "GetWindowThreadProcessId", pid)
    monkeypatch.setattr(helper.kernel32, "GetCurrentThreadId", lambda: 8)
    monkeypatch.setattr(helper.user32, "IsIconic", lambda hwnd: target["minimized"])
    monkeypatch.setattr(helper.user32, "ShowWindowAsync", lambda hwnd, how: calls.append("restore") or True)
    monkeypatch.setattr(helper.user32, "BringWindowToTop", lambda hwnd: calls.append("top") or True)
    monkeypatch.setattr(helper.user32, "SetForegroundWindow", lambda hwnd: calls.append("activate") or True)
    return helper, clock, calls, foreground, target


def test_activation_waits_for_delayed_foreground_without_restoring_maximized(activation_probe, monkeypatch):
    helper, clock, calls, foreground, target = activation_probe
    monkeypatch.setattr(helper.user32, "GetForegroundWindow", lambda: 123 if clock[0] >= 0.12 else 456)
    assert helper.activate_window(123, timeout_ms=500)
    assert 0.12 <= clock[0] < 0.5
    assert calls == ["top", "activate"]


def test_activation_timeout_reports_actual_state_without_accepting_wrong_window(activation_probe):
    helper, clock, calls, foreground, target = activation_probe
    with pytest.raises(helper.GuiError) as caught:
        helper.activate_window(123, timeout_ms=100)
    assert caught.value.code == "WINDOW_ACTIVATION_FAILED"
    details = caught.value.details
    assert details["foreground_after"]["hwnd"] == 456
    assert details["set_foreground_returned"] is True
    assert details["timeout_ms"] == 100 and clock[0] == 0.1
    assert details["desktops"]["input"]["name"] == "Default"


@pytest.mark.parametrize("condition", ["cloaked", "cancelled"])
def test_activation_does_not_touch_cloaked_or_cancelled_target(activation_probe, condition):
    helper, clock, calls, foreground, target = activation_probe
    cancel = threading.Event()
    if condition == "cloaked":
        target["cloaked"] = 2
    else:
        cancel.set()
    with pytest.raises(helper.GuiError) as caught:
        helper.activate_window(123, cancel_event=cancel)
    assert caught.value.code == ("WINDOW_CLOAKED" if condition == "cloaked" else "GUI_RUNTIME_STOPPED")
    assert calls == []


def test_activation_cancel_during_confirmation_stops_wait(activation_probe, monkeypatch):
    helper, clock, calls, foreground, target = activation_probe
    cancel = threading.Event()
    monkeypatch.setattr(cancel, "wait", lambda seconds: cancel.set())
    with pytest.raises(helper.GuiError) as caught:
        helper.activate_window(123, cancel_event=cancel)
    assert caught.value.code == "GUI_RUNTIME_STOPPED"
    assert calls.count("activate") == 1


def test_nonkeyboard_batch_survives_focus_query_failure_and_keyboard_stops(mouse_preview_service, monkeypatch):
    helper, service, point, inputs, raw, rect = mouse_preview_service
    def unavailable():
        raise helper.GuiError("GUI_FOCUS_UNAVAILABLE", "focus unavailable")
    monkeypatch.setattr(service, "_native_focus", unavailable)
    monkeypatch.setattr(service, "_execute_batch_item", lambda session, item: {"type": item["type"]})
    args = {"gui_session_id": point["gui_session_id"], "frame_id": 0,
            "actions": [{"type": "wait", "duration_ms": 0}, {"type": "wait", "duration_ms": 0}]}
    assert service.batch(args)["ok"]
    args["frame_id"] = 1
    args["actions"][1] = {"type": "press_key", "key": "enter"}
    with pytest.raises(helper.GuiError) as caught:
        service.batch(args)
    assert caught.value.code == "GUI_FOCUS_UNAVAILABLE"
    assert caught.value.details["completed_actions"] == 1
    assert inputs == []


@pytest.mark.parametrize("focus", [None, 0])
def test_unknown_or_absent_focus_never_authorizes_untargeted_keyboard(mouse_preview_service, monkeypatch, focus):
    helper, service, point, inputs, raw, rect = mouse_preview_service
    monkeypatch.setattr(service, "_native_focus", lambda: 0)
    with pytest.raises(helper.GuiError) as caught:
        frame = service._load_session(point["gui_session_id"])["frames"][0]
        frame["focus_window"] = focus
        service._check_keyboard_target(frame)
    assert caught.value.code == "GUI_FOCUS_UNAVAILABLE" and not inputs


def test_keyboard_accepts_child_focus_change_but_rejects_other_window(mouse_preview_service, monkeypatch):
    helper, service, point, inputs, raw, rect = mouse_preview_service
    monkeypatch.setattr(service, "_send_input", lambda event, **kwargs: inputs.append(event))
    args = {"gui_session_id": point["gui_session_id"], "action": "type_text", "text": "hello"}
    with pytest.raises(helper.GuiError) as caught:
        service.keyboard(args)
    assert caught.value.code == "STALE_FRAME"
    monkeypatch.setattr(helper.user32, "GetForegroundWindow", lambda: 999)
    monkeypatch.setattr(service, "_native_focus", lambda: 456)
    with pytest.raises(helper.GuiError) as caught:
        service.keyboard({**args, "frame_id": 0})
    assert caught.value.code == "GUI_FOCUS_CHANGED" and not inputs
    assert caught.value.details["foreground_window"]["hwnd"] == 999
    monkeypatch.setattr(helper.user32, "GetForegroundWindow", lambda: 123)
    result = service.keyboard({**args, "frame_id": 0})
    assert result["data"]["performed"] and result["data"]["frame_id"] == 1
    assert inputs


@pytest.mark.parametrize("failure_kind", ["screen", "closed", "pid_changed", "activation_failed"])
def test_activate_refuses_invalid_target(mouse_preview_service, monkeypatch, failure_kind):
    helper, service, point, inputs, raw, rect = mouse_preview_service
    session = service._load_session(point["gui_session_id"])
    if failure_kind != "screen":
        session["target"] = {"type": "window", "hwnd": 123, "process_id": 7}
    service._save_session(session)
    def pid(hwnd, pointer):
        ctypes.cast(pointer, ctypes.POINTER(helper.wintypes.DWORD)).contents.value = 8 if failure_kind == "pid_changed" else 7
        return 1
    monkeypatch.setattr(helper.user32, "GetWindowThreadProcessId", pid)
    monkeypatch.setattr(helper.user32, "IsWindow", lambda hwnd: failure_kind != "closed")
    monkeypatch.setattr(helper, "activate_window", lambda hwnd, **kwargs: False)
    with pytest.raises(helper.GuiError) as failure:
        service.inspect({"action": "activate", "gui_session_id": point["gui_session_id"]})
    assert failure.value.code == {"screen": "WINDOW_TARGET_REQUIRED", "closed": "WINDOW_NOT_AVAILABLE",
                                  "pid_changed": "WINDOW_IDENTITY_CHANGED", "activation_failed": "WINDOW_ACTIVATION_FAILED"}[failure_kind]
    assert service._load_session(point["gui_session_id"])["latest_frame_id"] == 0
    assert inputs == []


def test_tool_disconnect_releases_control(mouse_preview_service, monkeypatch):
    import socket
    helper, service, *_ = mouse_preview_service
    monkeypatch.setattr(helper.user32, "PostThreadMessageW", lambda *args: True)
    left, right = socket.socketpair()
    try:
        right.close()
        service._watch_connection(left, threading.Event())
        assert service.cancel_event.is_set()
        assert service.stop_reason == "tool_connection_lost"
    finally:
        left.close()


def test_batch_continues_after_own_pixel_changes(mouse_preview_service, monkeypatch):
    helper, service, point, inputs, raw, rect = mouse_preview_service
    def click(*args):
        inputs.append(args)
        raw.paste((255, 255, 255), (0, 0, 400, 300))
        service.input_events_sent += 1
    monkeypatch.setattr(service, "_mouse_click", click)
    result = service.batch({"gui_session_id": point["gui_session_id"], "frame_id": 0,
                            "actions": [{**{k: v for k, v in point.items() if k != "gui_session_id"}, "type": "click"}] * 2})
    assert result["data"]["execution_status"] == "completed"
    assert result["data"]["completed_actions"] == 2 and len(inputs) == 2


@pytest.mark.parametrize("method", ["mouse", "keyboard", "batch", "preview"])
@pytest.mark.parametrize("failure_code", ["WINDOW_NOT_AVAILABLE", "CAPTURE_FAILED"])
def test_completed_action_survives_observation_failure(mouse_preview_service, monkeypatch, method, failure_code):
    helper, service, point, inputs, raw, rect = mouse_preview_service
    if failure_code == "WINDOW_NOT_AVAILABLE":
        session = service._load_session(point["gui_session_id"])
        session["target"] = {"type": "window", "hwnd": 123, "process_id": 7}
        service._save_session(session)
    args = {
        "mouse": {**point, "action": "click"},
        "keyboard": {**point, "action": "type_text", "text": "isolated text"},
        "batch": {**point, "actions": [{**point, "type": "click"}, {"type": "press_key", "key": "enter"}]},
    }
    if method == "preview":
        preview = service.mouse({**point, "action": "preview", "preview_action": "click"})
        arguments = {"action": "execute_preview", "preview_id": preview["data"]["preview_id"]}
    else:
        arguments = args[method]
    def capture_failed(target):
        raise helper.GuiError(failure_code, "目标已关闭" if failure_code == "WINDOW_NOT_AVAILABLE" else "截图失败")
    monkeypatch.setattr(service, "_capture_target", capture_failed)
    result = getattr(service, "mouse" if method == "preview" else method)(arguments)
    assert result["ok"] and result["data"]["performed"] and inputs
    assert result["data"]["execution_status"] == "completed"
    assert result["data"]["observation_status"] == "unavailable"
    assert result["data"]["observation_error"]["code"] == failure_code
    assert result["data"]["frame_id"] is None and "image_path" not in result
    session = service._load_session(point["gui_session_id"])
    assert session["latest_frame_id"] == -1
    sent = len(inputs)
    with pytest.raises(helper.GuiError) as stale:
        service.mouse({**point, "action": "click"})
    assert stale.value.code == "STALE_FRAME" and len(inputs) == sent
    if method == "batch":
        assert result["data"]["completed_actions"] == 2
    if method == "preview":
        repeated = service.mouse(arguments)
        assert repeated["data"]["preview_reused"] and len(inputs) == sent
        assert repeated["data"]["execution_status"] == "completed"
    # A failed screenshot does not prevent explicit refresh from recovering.
    monkeypatch.setattr(service, "_capture_target", lambda target: (raw, rect.copy()))
    recovered = service.inspect({"action": "refresh", "gui_session_id": point["gui_session_id"]})
    assert recovered["data"]["frame_id"] == 1


def test_action_returns_new_foreground_without_changing_target(mouse_preview_service, monkeypatch):
    helper, service, point, inputs, raw, rect = mouse_preview_service
    session = service._load_session(point["gui_session_id"])
    session["target"] = {"type": "window", "hwnd": 123, "process_id": 7}
    service._save_session(session)
    original = service._mouse_click
    def popup(*args):
        original(*args)
        monkeypatch.setattr(helper.user32, "GetForegroundWindow", lambda: 456)
    monkeypatch.setattr(service, "_mouse_click", popup)
    result = service.mouse({**point, "action": "click"})
    assert result["data"]["execution_status"] == "completed"
    assert result["data"]["foreground_changed"]
    assert result["data"]["foreground_window"]["hwnd"] == 456
    assert result["data"]["foreground_window"]["title"] == "Test window"
    assert result["data"]["target"]["hwnd"] == 123
    with pytest.raises(helper.GuiError) as failure:
        service.keyboard({**point, "frame_id": 1, "action": "press_key", "key": "enter"})
    assert failure.value.code == "TARGET_NOT_FOREGROUND"
    assert failure.value.details["foreground_window"]["hwnd"] == 456
    assert len(inputs) == 1


@pytest.mark.parametrize("target", ["screen", "window"])
def test_batch_stops_at_new_window_and_preserves_completed_steps(mouse_preview_service, monkeypatch, target):
    helper, service, point, inputs, raw, rect = mouse_preview_service
    if target == "window":
        session = service._load_session(point["gui_session_id"])
        session["target"] = {"type": "window", "hwnd": 123, "process_id": 7}
        service._save_session(session)
    original = service._mouse_click
    def popup(*args):
        original(*args)
        monkeypatch.setattr(helper.user32, "GetForegroundWindow", lambda: 456)
    monkeypatch.setattr(service, "_mouse_click", popup)
    with pytest.raises(helper.GuiError) as failure:
        service.batch({**point, "actions": [{**point, "type": "click"}, {"type": "press_key", "key": "enter"}]})
    detail = failure.value.details
    assert detail["execution_status"] == "partial" and detail["performed"]
    assert detail["completed_actions"] == 1 and detail["failed_action_index"] == 1
    assert detail["foreground_window"]["hwnd"] == 456 and len(inputs) == 1
    assert service._load_session(point["gui_session_id"])["latest_frame_id"] == -1


@pytest.mark.parametrize("name", ["gui_mouse", "gui_keyboard", "gui_batch"])
def test_action_wrapper_preserves_completion_when_image_is_missing(tmp_path, monkeypatch, name):
    program = _load_program(name)
    response = {"ok": True, "data": {"execution_status": "completed", "performed": True,
                                    "frame_id": 1, "observation_status": "captured"},
                "image_path": str(tmp_path / ".Tiance/gui-temp/missing.png")}
    monkeypatch.setattr(program, "context_and_state", lambda: (tmp_path, {}))
    monkeypatch.setattr(program, "call_helper", lambda *args: response)
    result = program.run({})
    assert result["ok"] and result["data"]["execution_status"] == "completed"
    assert result["data"]["observation_status"] == "unavailable" and result["warnings"]
    assert result["data"]["frame_id"] is None


def test_action_contract_removes_pixel_blocking_parameters():
    point = {"gui_session_id": "gui_" + "a" * 32, "frame_id": 0, "view_id": "root", "cell_id": 1, "x": 0.5, "y": 0.5}
    calls = {"gui_mouse": {**point, "action": "click"},
             "gui_keyboard": {"gui_session_id": point["gui_session_id"], "frame_id": 0, "action": "press_key", "key": "enter"},
             "gui_batch": {"gui_session_id": point["gui_session_id"], "frame_id": 0, "actions": [{"type": "press_key", "key": "enter"}]}}
    for name, args in calls.items():
        assert validate_tool_arguments(args, _schema(name)) == []
        for removed in ("change_check_scope", "change_threshold_percent"):
            assert removed not in _schema(name)["properties"]
            assert validate_tool_arguments({**args, removed: 0.5}, _schema(name))
    assert "change_threshold_percent" in _schema("gui_inspect")["properties"]  # Explicit wait still compares images.


def test_action_state_write_failure_reports_completion_and_stops_queue(mouse_preview_service, monkeypatch):
    helper, service, point, inputs, raw, rect = mouse_preview_service
    def fail_save(session):
        raise OSError("state file unavailable")
    monkeypatch.setattr(service, "_save_session", fail_save)
    monkeypatch.setattr(service, "request_stop", lambda reason: service.cancel_event.set())
    result = service.mouse({**point, "action": "click"})
    assert result["ok"] and result["data"]["execution_status"] == "completed" and len(inputs) == 1
    assert result["data"]["observation_error"]["code"] == "GUI_STATE_WRITE_FAILED"
    assert service.cancel_event.is_set() and not result["data"]["interface_state"]["lock_active"]
    with pytest.raises(helper.GuiError) as failure:
        service._dispatch({"token": service.token, "project_id": service.project_id, "session_id": service.session_id,
                           "method": "mouse", "payload": {**point, "action": "click"}})
    assert failure.value.code == "GUI_RUNTIME_STOPPED" and len(inputs) == 1


@pytest.mark.skipif(os.name != "nt", reason="GUI工具只支持Windows")
@pytest.mark.parametrize("unsupported", ["old_windows", "composition_disabled", "affinity_rejected"])
def test_unsupported_capture_exclusion_fails_without_hiding_overlay(monkeypatch: pytest.MonkeyPatch, unsupported: str) -> None:
    helper = _load_overlay_helper()
    service = helper.GuiService.__new__(helper.GuiService)

    def forbidden_toggle(*args):
        pytest.fail("不支持截图排除时不得通过隐藏覆盖层继续操作")

    def disabled_composition(pointer):
        ctypes.cast(pointer, ctypes.POINTER(helper.wintypes.BOOL)).contents.value = False
        return 0

    monkeypatch.setattr(helper.user32, "ShowWindow", forbidden_toggle)
    if unsupported == "old_windows":
        monkeypatch.setattr(helper.sys, "getwindowsversion", lambda: SimpleNamespace(build=18363))
    elif unsupported == "composition_disabled":
        monkeypatch.setattr(helper.dwmapi, "DwmIsCompositionEnabled", disabled_composition)
    else:
        monkeypatch.setattr(helper.user32, "SetWindowDisplayAffinity", lambda hwnd, affinity: 0)
    with pytest.raises(helper.GuiError) as failure:
        if unsupported == "affinity_rejected":
            service._exclude_window_from_capture(42)
        else:
            service._detect_capture_mode()
    assert failure.value.code == "CAPTURE_EXCLUSION_UNAVAILABLE"
