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
}


def _tool_root(name: str) -> Path:
    return _TOOLS / _TOOL_IDS[name]


def _schema(name: str) -> dict:
    return loads((_tool_root(name) / ".tool" / "input.schema.json").read_text(encoding="utf-8"))


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


def test_gui_tools_are_dynamic_serial_ui_control_tools() -> None:
    catalog = loads((_TOOLS / "catalog.json").read_text(encoding="utf-8"))
    catalog_ids = {item["project_id"] for item in catalog["projects"]}
    for name, project_id in _TOOL_IDS.items():
        loaded = load_tool(str(_tool_root(name)))
        permissions = loads((_tool_root(name) / ".tool" / "permissions.json").read_text(encoding="utf-8"))
        assert loaded.name == name
        assert loaded.manifest["loading"]["dynamic"] is True
        assert loaded.manifest["execution"]["parallel"] is False
        assert permissions["policies"]["ui_control"]["all"] == "allow"
        assert project_id in catalog_ids


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
        "grid": {"rows": 1, "columns": 1},
        "cells": [{"cell_id": 1, "rect_absolute": {"left": 100, "top": 200, "width": 100, "height": 80}}],
        "overlay_image": "frame_000/root_overlay.png",
        "image_size": {"width": 100, "height": 80},
        "zoom_scale_percent": 100,
    }
    frame = {
        "frame_id": 0,
        "capture_rect": {"left": 100, "top": 200, "width": 100, "height": 80},
        "views": {"root": view},
    }
    session = {"gui_session_id": "gui_" + "0" * 32, "target": {"type": "screen"}}

    class FakePreview:
        _view = staticmethod(helper.GuiService._view)
        _result_with_image = helper.GuiService._result_with_image
        external_mouse_events = 0
        external_keyboard_events = 0
        cancel_event = threading.Event()

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
        difference=0.0,
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
@pytest.mark.parametrize("first_scale,second_scale", [(100, 400), (400, 600), (800, 100)])
def test_nested_zoom_preview_and_input_share_physical_point(tmp_path: Path, first_scale: int, second_scale: int, monkeypatch: pytest.MonkeyPatch) -> None:
    helper = _load_overlay_helper()
    service = helper.GuiService.__new__(helper.GuiService)
    service.gui_root = tmp_path
    service.lock_id = "test_lock"
    service.external_mouse_events = service.external_keyboard_events = 0
    service.cancel_event = threading.Event()
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
    preview = service._preview_coordinate(session=session, frame=frame, arguments=point_args, screen_x=x, screen_y=y, difference=0, mouse_before=0, keyboard_before=0)
    with helper.Image.open(preview["image_path"]) as marked:
        assert marked.size == (round(2.01 * second_scale), round(1.5 * second_scale))
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
def test_target_cell_check_ignores_unrelated_animation_but_detects_target_changes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    helper = _load_overlay_helper()
    service = helper.GuiService.__new__(helper.GuiService)
    service.gui_root = tmp_path
    gui_id = "gui_" + "b" * 32
    source = {"left": 0, "top": 0, "width": 200, "height": 200}
    raw = helper.Image.new("RGB", (200, 200))
    session = {"gui_session_id": gui_id, "target": {"type": "screen"}, "frames": []}
    service._create_frame(session, reason="test", raw=raw, source_rect=source, grid_mode="fixed", grid_rows=2, grid_cols=2)
    animated = raw.copy()
    animated.paste((255, 255, 255), (150, 150, 200, 200))
    monkeypatch.setattr(service, "_capture_target", lambda target: (animated, source))
    assert service._preflight(session)[3] == 6.25
    assert service._preflight(session, [{"view_id": "root", "cell_id": 1}])[3] == 0
    animated.paste((255, 255, 255), (10, 10, 30, 30))
    assert service._preflight(session, [{"view_id": "root", "cell_id": 1}])[3] == 4


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

    for name in ("_mouse_move", "_mouse_click", "_mouse_drag", "_mouse_scroll", "_mouse_flag", "_key_event"):
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
        "keyboard": {"gui_session_id": point["gui_session_id"], "action": "press_key", "key": "a"},
        "batch": {"gui_session_id": point["gui_session_id"], "actions": [{"type": "press_key", "key": "a"}, {"type": "press_key", "key": "b"}]},
    }[method]
    if delay is not None:
        arguments["screenshot_delay_seconds"] = delay
    result = getattr(service, method)(arguments)
    expected = 1 if delay is None else delay
    assert events == [("capture", 0), ("wait", expected), ("capture", len(inputs))]
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
        with pytest.raises(helper.GuiError) as failure:
            future.result(timeout=1)
        assert failure.value.code == "GUI_RUNTIME_STOPPED"
    assert captured == [True]  # 只有操作前检查，退出后不再截图。
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
    assert result["data"]["operation"]["change_check_scope"] == "frame"
    with helper.Image.open(result["image_path"]) as image:
        start = result["data"]["marker"]
        assert image.getpixel((start["center_x"], start["center_y"])) == helper.COORDINATE_PREVIEW_COLOR
        marker = result["data"]["end_marker"]
        assert image.getpixel((marker["center_x"], marker["center_y"])) == (0, 220, 255)


@pytest.mark.skipif(os.name != "nt", reason="GUI工具只支持Windows")
@pytest.mark.parametrize("change", ["new_frame", "pixels", "window_move", "window_resize"])
def test_preview_expiry_never_inputs_and_returns_current_frame(mouse_preview_service, monkeypatch: pytest.MonkeyPatch, change: str) -> None:
    helper, service, point, inputs, raw, rect = mouse_preview_service
    if change.startswith("window"):
        session = service._load_session(point["gui_session_id"])
        session["target"] = {"type": "window", "hwnd": 42}
        service._save_session(session)
        monkeypatch.setattr(helper, "window_rect", lambda hwnd: rect.copy())
        monkeypatch.setattr(helper.user32, "GetForegroundWindow", lambda: 42)
    preview = service.mouse({**point, "action": "preview", "preview_action": "click"})
    if change == "new_frame":
        service._create_frame(service._load_session(point["gui_session_id"]), reason="refresh", raw=raw, source_rect=rect)
    elif change == "pixels":
        raw.paste((255, 255, 255), (5, 5, 100, 100))
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
    assert not result["data"]["interface_state"]["safe_to_continue"]
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
