"""Annotation geometry, persistence, contracts and hidden native display lifecycle."""
from importlib.util import module_from_spec, spec_from_file_location
import json
import ctypes
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

from PIL import Image
import pytest

from app.services.tools.tool_execution_arguments import validate_tool_arguments
from app.services.tools.tool_metadata import load_tool
from app.services.tools.tool_execution_runtime import build_python_command, build_tool_python_paths


ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "Data/tools/ebaa5668-e092-4a81-b787-5097190fe0a6"
PROGRAM = TOOL / "program"
GUI_ID = "gui_" + "a" * 32


def load(path, name):
    spec = spec_from_file_location(name, path)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def modules(monkeypatch):
    monkeypatch.syspath_prepend(str(PROGRAM))
    import annotation_store
    return annotation_store


@pytest.fixture
def store(tmp_path, modules):
    engine = load(ROOT / "Data/tools/c7dd4066-37a6-4b1e-a67a-d39f0c6d4a21/program/overlay_helper.py", "annotation_source_engine")
    folder = tmp_path / ".Tiance/gui-temp" / GUI_ID
    (folder / "frame_000").mkdir(parents=True)
    rect = {"left": -100, "top": 40, "width": 400, "height": 200}
    cropped = {"left": 50, "top": 90, "width": 100, "height": 50}
    Image.new("RGB", (400, 200), (25, 25, 25)).save(folder / "frame_000/root_raw.png")
    views = {"root": {"cells": engine.build_cells(rect, 2, 2), "raw_image": "frame_000/root_raw.png"},
             "child": {"cells": engine.build_cells(cropped, 2, 2), "raw_image": "frame_000/child_raw.png"}}
    modules.atomic_json(folder / "session.json", {"gui_session_id": GUI_ID, "project_id": "p", "lock_id": "old-lock",
        "status": "closed", "target": {"type": "screen"}, "latest_frame_id": -1,
        "frames": [{"frame_id": 0, "capture_rect": rect, "views": views}]})
    return modules.AnnotationStore(tmp_path, "p")


def draw(store, specifications):
    return store.apply({"action": "draw", "gui_session_id": GUI_ID, "frame_id": 0, "annotations": specifications})


def test_annotation_tool_is_registered_and_examples_match_generic_validator():
    tool = load_tool(str(TOOL))
    assert tool.name == "gui_annotate"
    assert tool.manifest["execution"]["parallel"] is False
    assert tool.manifest["loading"]["dynamic"] is False
    assert TOOL.name in {p["project_id"] for p in json.loads((ROOT / "Data/tools/catalog.json").read_text(encoding="utf-8"))["projects"]}
    for _, example in tool.examples:
        assert validate_tool_arguments(json.loads(example["content"]), tool.input_schema) == []


def test_grid_merge_irregular_selection_and_persisted_geometry(store):
    response = draw(store, [{"type": "grid", "cell_ids": [1, 2]}, {"type": "grid", "cell_ids": [1, 4]}])
    first, second = response["data"]["groups"][0]["annotations"]
    assert first["geometry"]["rects"] == [{"left": -100, "top": 40, "width": 400, "height": 100}]
    assert len(second["geometry"]["rects"]) == 2
    assert first["color"] == "#FF0000" and first["size_px"] == 2
    assert store.load(GUI_ID)["annotations"][0]["annotation_id"] == first["annotation_id"]
    assert Path(response["image_path"]).is_file()
    assert response["data"]["preview_basis"] == "saved_frame"


def test_nested_view_coordinates_match_gui_bottom_left_contract(store):
    response = draw(store, [{"type": "arrow", "tail": {"cell_id": 1, "view_id": "child", "x": 0, "y": 1},
                            "head": {"cell_id": 4, "view_id": "child", "x": 1, "y": 0}, "size": 3},
                           {"type": "text", "position": {"cell_id": 1, "x": 0, "y": 1}, "text": "第一行\n第二行", "size": 18}])
    arrow, text = response["data"]["groups"][0]["annotations"]
    assert arrow["geometry"] == {"tail": {"x": 50, "y": 90}, "head": {"x": 149, "y": 139}}
    assert text["geometry"]["position"] == {"x": -100, "y": 40}
    assert text["text"] == "第一行\n第二行"
    with Image.open(response["image_path"]) as image:
        assert image.getpixel((249, 99)) == (255, 0, 0)


def test_partial_update_preserves_identity_and_closed_display(store):
    response = draw(store, [{"type": "grid", "cell_ids": [1]}])
    annotation_id = response["data"]["annotation_ids"][0]
    store.apply({"action": "close"})
    store.apply({"action": "update", "gui_session_id": GUI_ID, "updates": [{"annotation_id": annotation_id, "color": "blue", "size": 7}]})
    state = store.load(GUI_ID)
    assert not state["display_open"]
    item = state["annotations"][0]
    assert item["annotation_id"] == annotation_id
    assert item["cell_ids"] == [1] and item["color"] == "#0000FF" and item["size_px"] == 7
    store.apply({"action": "show", "gui_session_id": GUI_ID})
    assert store.load(GUI_ID)["display_open"]
    store.apply({"action": "delete", "gui_session_id": GUI_ID, "annotation_ids": [annotation_id]})
    assert store.load(GUI_ID)["annotations"] == []
    assert not store.load(GUI_ID)["display_open"]
    assert (store.folder(GUI_ID) / "frame_000/root_raw.png").exists()


def test_invalid_batch_is_atomic_and_irrelevant_edit_fields_are_rejected(store, modules):
    draw(store, [{"type": "grid", "cell_ids": [1]}])
    previous = (store.folder(GUI_ID) / "annotations.json").read_bytes()
    with pytest.raises(modules.AnnotationError):
        draw(store, [{"type": "grid", "cell_ids": [2]}, {"type": "grid", "cell_ids": [99]}])
    assert (store.folder(GUI_ID) / "annotations.json").read_bytes() == previous
    annotation_id = store.load(GUI_ID)["annotations"][0]["annotation_id"]
    with pytest.raises(modules.AnnotationError):
        store.apply({"action": "update", "gui_session_id": GUI_ID, "updates": [{"annotation_id": annotation_id, "text": "wrong shape"}]})
    assert (store.folder(GUI_ID) / "annotations.json").read_bytes() == previous


def test_foreign_project_and_path_escape_are_rejected(store, modules):
    with pytest.raises(modules.AnnotationError):
        store.folder("../../outside")
    with pytest.raises(modules.AnnotationError):
        modules.AnnotationStore(store.root.parents[1], "foreign").load(GUI_ID)
    gui = store.gui(GUI_ID)
    gui["frames"][0]["views"]["root"]["raw_image"] = "../../outside.png"
    modules.atomic_json(store.folder(GUI_ID) / "session.json", gui)
    response = draw(store, [{"type": "grid", "cell_ids": [1]}])
    assert response["warnings"] and "image_path" not in response


def test_lock_cleanup_and_inspect_close_retain_all_gui_files(tmp_path):
    engine = load(ROOT / "Data/tools/c7dd4066-37a6-4b1e-a67a-d39f0c6d4a21/program/overlay_helper.py", "annotation_retention_engine")
    service = engine.GuiService.__new__(engine.GuiService)
    service.gui_root = tmp_path
    service.lock_id = "lock"
    service.created_gui_sessions = {GUI_ID}
    session = {"gui_session_id": GUI_ID, "lock_id": "lock", "status": "active", "frames": []}
    service._save_session(session)
    image = service._session_dir(GUI_ID) / "image.png"
    image.write_bytes(b"saved")
    service._cleanup_gui_sessions()
    assert image.read_bytes() == b"saved"
    assert engine.read_json(image.parent / "session.json")["status"] == "closed"
    session["status"] = "active"
    service._save_session(session)
    service.created_gui_sessions.add(GUI_ID)
    result = service.inspect({"action": "close", "gui_session_id": GUI_ID})
    assert result["data"]["data_retained"] and image.exists()
    with pytest.raises(engine.GuiError):
        service._load_session(GUI_ID)


@pytest.mark.skipif(os.name != "nt", reason="Native Windows windows")
def test_hidden_native_layer_styles_upload_and_close_button(modules):
    import native_layer as native
    called = []
    layer = native.NativeLayer(lambda: called.append(True))
    rect = {"left": 0, "top": 0, "width": 80, "height": 50}
    try:
        layer.overlay = layer.create(rect)
        layer.button = layer.create(rect, button=True)
        layer.upload(layer.overlay, rect, Image.new("RGBA", (80, 50), (255, 0, 0, 100)))
        get_style = native.api(native.user32, "GetWindowLongPtrW", [native.W.HWND, native.C.c_int], native.C.c_ssize_t)
        assert get_style(layer.overlay, -20) & native.PASS_THROUGH
        assert get_style(layer.overlay, -20) & native.NO_ACTIVATE
        assert not get_style(layer.button, -20) & native.PASS_THROUGH
        assert not get_style(layer.button, -20) & 0x00080000
        assert layer.window_proc(layer.overlay, 0x0084, 0, 0) == -1
        assert layer.window_proc(layer.button, 0x0021, 0, 0) == 3
        layer.window_proc(layer.button, 0x0202, 0, 0)
        assert called == [True]
        assert not native.user32.IsWindowVisible(layer.overlay)
    finally:
        layer.close()


@pytest.mark.skipif(os.name != "nt", reason="Actual Windows hit testing")
def test_visible_close_button_receives_native_hit_and_closes_via_message_queue(store, modules):
    """Actual hit routing on an isolated desktop; never switch the user's desktop or send input."""
    import native_layer as native
    draw(store, [{"type": "grid", "cell_ids": [1]}])
    service_module = load(PROGRAM / "overlay_helper.py", "annotation_service_native_close")
    hit_test = native.api(native.user32, "WindowFromPoint", [native.W.POINT], native.W.HWND)
    post = native.api(native.user32, "PostMessageW", [native.W.HWND, native.W.UINT, native.WPARAM, native.LPARAM], native.W.BOOL)
    foreground = native.api(native.user32, "GetForegroundWindow", [], native.W.HWND)
    create_desktop = native.api(native.user32, "CreateDesktopW", [native.W.LPCWSTR, native.W.LPCWSTR, ctypes.c_void_p,
                               native.W.DWORD, native.W.DWORD, ctypes.c_void_p], native.W.HANDLE)
    set_desktop = native.api(native.user32, "SetThreadDesktop", [native.W.HANDLE], native.W.BOOL)
    get_desktop = native.api(native.user32, "GetThreadDesktop", [native.W.DWORD], native.W.HANDLE)
    close_desktop = native.api(native.user32, "CloseDesktop", [native.W.HANDLE], native.W.BOOL)
    def pump():
        message = native.W.MSG()
        while native.user32.PeekMessageW(ctypes.byref(message), None, 0, 0, 1):
            native.user32.TranslateMessage(ctypes.byref(message))
            native.user32.DispatchMessageW(ctypes.byref(message))
    failures = []
    def worker():
        previous = get_desktop(native.kernel32.GetCurrentThreadId())
        desktop = create_desktop("TianceAnnotationTest_" + os.urandom(8).hex(), None, None, 0, 0xC3, None)
        layer = None
        try:
            assert desktop and set_desktop(desktop)
            before = foreground()
            service = service_module.AnnotationService.__new__(service_module.AnnotationService)
            service.store = store
            stopped = []
            service.stop = lambda: stopped.append(True)
            service.layer = layer = native.NativeLayer(service.user_close)
            rect = {"left": 30, "top": 30, "width": 184, "height": 36}
            layer.button = layer.create(rect, button=True)
            layer.upload(layer.button, rect, Image.new("RGBA", (184, 36), (35, 35, 35, 255)))
            native.user32.ShowWindow(layer.surfaces[layer.button], 4)
            native.user32.ShowWindow(layer.button, 4)
            deadline = time.monotonic() + 2
            hit = None
            while time.monotonic() < deadline:
                pump()
                hit = hit_test(native.W.POINT(rect["left"] + 92, rect["top"] + 18))
                if hit in (layer.button, layer.surfaces[layer.button]):
                    break
                time.sleep(0.01)
            assert hit in (layer.button, layer.surfaces[layer.button]), "关闭按钮实际点击区域不能穿透到其他窗口"
            assert foreground() == before
            assert post(hit, 0x0201, 1, (18 << 16) | 92)
            assert post(hit, 0x0202, 0, (18 << 16) | 92)
            pump()
            assert stopped == [True]
            assert layer.button is None and not layer.surfaces
            assert not store.load(GUI_ID)["display_open"]
            assert store.load(GUI_ID)["annotations"]
            assert foreground() == before
        except BaseException as exc:
            failures.append(exc)
        finally:
            if layer:
                layer.close()
            set_desktop(previous)
            if desktop:
                close_desktop(desktop)
    thread = threading.Thread(target=worker)
    thread.start()
    thread.join(timeout=10)
    assert not thread.is_alive()
    if failures:
        raise failures[0]


def test_user_close_button_updates_all_group_states_and_stops_process(store, modules, monkeypatch):
    monkeypatch.syspath_prepend(str(PROGRAM))
    service_module = load(PROGRAM / "overlay_helper.py", "annotation_service_for_close")
    response = draw(store, [{"type": "grid", "cell_ids": [1]}])
    service = service_module.AnnotationService.__new__(service_module.AnnotationService)
    service.store = store
    actions = []
    service.stop = lambda: actions.append("stop")
    service.layer = type("Layer", (), {"destroy_windows": lambda self: actions.append("destroy")})()
    service.user_close()
    assert actions == ["stop", "destroy"]
    assert not store.load(GUI_ID)["display_open"]
    assert store.load(GUI_ID)["annotations"][0]["annotation_id"] == response["data"]["annotation_ids"][0]


def test_old_runtime_handover_preserves_saved_annotations_and_group_visibility(store, modules, monkeypatch):
    entry = load(PROGRAM / "main.py", "annotation_handover_entry")
    visible = draw(store, [{"type": "grid", "cell_ids": [1]}])["data"]["annotation_ids"][0]
    hidden_id = "gui_" + "b" * 32
    hidden_session = store.gui(GUI_ID)
    hidden_session["gui_session_id"] = hidden_id
    modules.atomic_json(store.root / hidden_id / "session.json", hidden_session)
    hidden = store.apply({"action": "draw", "gui_session_id": hidden_id, "frame_id": 0,
                          "annotations": [{"type": "grid", "cell_ids": [2]}]})["data"]["annotation_ids"][0]
    store.apply({"action": "close", "gui_session_id": hidden_id})
    path = store.root / "annotation-runtime.json"
    modules.atomic_json(path, {"runtime_version": "old"})
    calls = []
    def close_old(state, payload, *, timeout):
        calls.append((payload, timeout))
        result = store.apply(payload)
        path.unlink()
        return result
    monkeypatch.setattr(entry, "rpc", close_old)
    entry.retire_old_runtime({"runtime_version": "old"}, path, store)
    assert calls == [({"action": "close"}, 10)]
    assert not path.exists()
    assert store.load(GUI_ID)["display_open"]
    assert not store.load(hidden_id)["display_open"]
    assert store.load(GUI_ID)["annotations"][0]["annotation_id"] == visible
    assert store.load(hidden_id)["annotations"][0]["annotation_id"] == hidden


@pytest.mark.parametrize("accepted", [False, True])
def test_old_runtime_without_confirmed_exit_does_not_launch_second_helper(store, modules, monkeypatch, accepted):
    entry = load(PROGRAM / "main.py", "annotation_unconfirmed_handover")
    draw(store, [{"type": "grid", "cell_ids": [1]}])
    path = store.root / "annotation-runtime.json"
    state = {"runtime_version": "old"}
    modules.atomic_json(path, state)
    monkeypatch.setattr(entry, "current_context", lambda: (store.root.parents[1], "p"))
    monkeypatch.setattr(entry, "endpoint", lambda *args: state)
    monkeypatch.setattr(entry, "rpc", lambda *args, **kwargs: {"ok": accepted})
    def unexpected_launch(*args):
        pytest.fail("旧进程退出未确认时不得启动第二个显示进程")
    monkeypatch.setattr(entry, "launch", unexpected_launch)
    result = entry.run({"action": "show", "gui_session_id": GUI_ID})
    assert not result["ok"]
    assert result["error_info"]["code"] == ("ANNOTATION_UPGRADE_PENDING" if accepted else "ANNOTATION_UPGRADE_FAILED")
    assert path.exists() and store.load(GUI_ID)["annotations"]


@pytest.mark.parametrize("action", ["list", "close"])
def test_read_and_close_keep_legacy_runtime_directly_addressable(store, modules, monkeypatch, action):
    entry = load(PROGRAM / "main.py", "annotation_legacy_direct_rpc")
    draw(store, [{"type": "grid", "cell_ids": [1]}])
    state = {"runtime_version": "old"}
    monkeypatch.setattr(entry, "current_context", lambda: (store.root.parents[1], "p"))
    monkeypatch.setattr(entry, "endpoint", lambda *args: state)
    calls = []
    def request(existing, payload):
        assert existing is state
        calls.append(payload)
        return store.apply(payload)
    monkeypatch.setattr(entry, "rpc", request)
    monkeypatch.setattr(entry, "retire_old_runtime", lambda *args: pytest.fail("list和close不得触发进程升级"))
    result = entry.run({"action": action})
    assert result["ok"] and calls == [{"action": action}]
    assert "runtime_upgraded" not in result["data"]


@pytest.mark.skipif(os.name != "nt", reason="Detached Windows helper")
@pytest.mark.parametrize("runtime", ["host", "embedded"])
def test_real_detached_helper_survives_call_and_edits_after_call_exit(store, tmp_path, modules, runtime):
    """Use actual Win32 windows and RPC, with ShowWindow suppressed in the child."""
    wrapper = tmp_path / "test_wrapper.py"
    helper = tmp_path / "overlay_helper.py"
    bootstrap = f"import sys\nsys.path.insert(0, {str(PROGRAM)!r})\nsys.path.insert(0, {str(ROOT / '1_PythonServer')!r})\n"
    wrapper.write_text(bootstrap + f"import importlib.util\nspec=importlib.util.spec_from_file_location('annotate_entry', {str(PROGRAM / 'main.py')!r})\n"
        "module=importlib.util.module_from_spec(spec)\nspec.loader.exec_module(module)\nmodule.__file__=__file__\n"
        "from tiance_runtime import run_tool\nrun_tool(module.run)\n", encoding="utf-8")
    helper.write_text(bootstrap + "import native_layer\nnative_layer.user32.ShowWindow=lambda *args: True\n"
        f"import runpy\nrunpy.run_path({str(PROGRAM / 'overlay_helper.py')!r}, run_name='__main__')\n", encoding="utf-8")
    env = {**os.environ, "TIANCE_WORKSPACE_ROOT": str(tmp_path), "TIANCE_PROJECT_ID": "p", "TIANCE_SESSION_ID": "s"}
    endpoint = store.root / "annotation-runtime.json"
    python = Path(sys.executable) if runtime == "host" else ROOT / "runtime/python/py313/python.exe"
    paths = build_tool_python_paths(entry_path=wrapper, tool_root=TOOL,
                                   backend_site_packages_path=ROOT / "runtime/python-packages/backend/py313/site-packages")
    command = build_python_command(python_executable=python, entry_path=wrapper, python_paths=paths)
    def invoke(payload):
        result = subprocess.run(command, input=json.dumps(payload), text=True,
                                encoding="utf-8", capture_output=True, env=env, timeout=45)
        assert result.returncode == 0, result.stderr
        response = json.loads(result.stdout)
        assert response["ok"], response
        return response
    try:
        response = invoke({"action": "draw", "gui_session_id": GUI_ID, "frame_id": 0, "annotations": [{"type": "grid", "cell_ids": [1]}]})
        pid = json.loads(endpoint.read_text(encoding="utf-8"))["pid"]
        time.sleep(0.3)
        assert endpoint.exists()
        assert response["data"]["display_running"]
        annotation_id = response["data"]["annotation_ids"][0]
        updated = invoke({"action": "update", "gui_session_id": GUI_ID, "updates": [{"annotation_id": annotation_id, "color": "green"}]})
        assert json.loads(endpoint.read_text(encoding="utf-8"))["pid"] == pid
        assert updated["data"]["groups"][0]["annotations"][0]["color"] == "#008000"
        legacy = json.loads(endpoint.read_text(encoding="utf-8"))
        assert legacy["runtime_version"] == modules.package_version()
        if runtime == "host":
            legacy.pop("runtime_version")  # Early helpers did not publish a version.
        else:
            legacy["runtime_version"] = "1.0.0"
        modules.atomic_json(endpoint, legacy)
        upgraded = invoke({"action": "update", "gui_session_id": GUI_ID,
                           "updates": [{"annotation_id": annotation_id, "size": 6}]})
        replacement = json.loads(endpoint.read_text(encoding="utf-8"))
        assert replacement["pid"] != pid
        assert replacement["runtime_version"] == modules.package_version()
        assert upgraded["data"]["runtime_upgraded"] and upgraded["data"]["display_running"]
        assert store.load(GUI_ID)["display_open"]
        assert store.load(GUI_ID)["annotations"][0]["annotation_id"] == annotation_id
        assert store.load(GUI_ID)["annotations"][0]["size_px"] == 6
        invoke({"action": "close"})
        assert not endpoint.exists() and not store.load(GUI_ID)["display_open"]
        invoke({"action": "update", "gui_session_id": GUI_ID, "updates": [{"annotation_id": annotation_id, "size": 5}]})
        assert not endpoint.exists()
        invoke({"action": "show", "gui_session_id": GUI_ID})
        assert endpoint.exists() and store.load(GUI_ID)["display_open"]
    finally:
        if endpoint.exists():
            invoke({"action": "close"})


@pytest.mark.parametrize("arguments", [
    {"action": "draw", "gui_session_id": GUI_ID, "frame_id": 0, "annotations": [{"type": "arrow", "head": {"cell_id": 1, "x": 0.5, "y": 0.5}}]},
    {"action": "close", "frame_id": 0},
    {"action": "update", "gui_session_id": GUI_ID, "updates": [{"annotation_id": "ann_" + "a" * 32}]},
    {"action": "draw", "gui_session_id": GUI_ID, "frame_id": 0, "annotations": [{"type": "grid", "cell_ids": [1, 1]}]},
])
def test_malformed_calls_are_rejected_by_both_validators(arguments, modules):
    schema = load_tool(str(TOOL)).input_schema
    assert validate_tool_arguments(arguments, schema)
    with pytest.raises(modules.AnnotationError):
        modules.validate(arguments)
