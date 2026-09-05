from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from json import loads
import os
from pathlib import Path
import threading
from types import ModuleType

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
def test_gui_action_tools_require_an_inspect_session_not_a_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TIANCE_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("TIANCE_PROJECT_ID", "project")
    monkeypatch.setenv("TIANCE_SESSION_ID", "session")
    missing_state = tmp_path / "missing-runtime-state.json"
    for name in ("gui_mouse", "gui_keyboard", "gui_batch"):
        module = _load_program(name)
        monkeypatch.setattr(module, "STATE_PATH", missing_state)
        result = module.run({})
        assert result["ok"] is False
        assert result["error_info"]["code"] == "GUI_RUNTIME_UNAVAILABLE"
