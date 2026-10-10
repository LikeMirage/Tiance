"""Display overlays and view navigation without sending input to the desktop."""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import threading

import pytest
from PIL import Image


def engine():
    path = Path(__file__).resolve().parents[2] / "Data/tools/c7dd4066-37a6-4b1e-a67a-d39f0c6d4a21/program/overlay_helper.py"
    spec = spec_from_file_location("overlay_views_under_test", path)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fixture_session(tmp_path, monkeypatch, *, overlay="labels+lines", width=288, height=128):
    module = engine()
    service = module.GuiService.__new__(module.GuiService)
    service.gui_root = tmp_path
    service.lock_id = "test"
    service.cancel_event = threading.Event()
    service.block_user_input = True
    service.external_mouse_events = service.external_keyboard_events = 0
    monkeypatch.setattr(service, "_native_focus", lambda: 0)
    gui_id = "gui_" + "b" * 32
    service._session_dir(gui_id).mkdir()
    session = {"gui_session_id": gui_id, "lock_id": "test", "status": "active", "target": {"type": "screen"}, "frames": []}
    raw = Image.new("RGB", (width, height), (35, 35, 35))
    raw.putpixel((width // 2, height // 2), (255, 0, 0))
    rect = {"left": -200, "top": 50, "width": width, "height": height}
    service._create_frame(session, reason="test", raw=raw, source_rect=rect, grid_mode="fixed", grid_rows=4, grid_cols=4, overlay=overlay)
    return module, service, session, raw, rect


@pytest.mark.parametrize("mode,effective", [("labels+lines", "labels+lines"), ("lines", "lines"), ("none", "none")])
def test_tiny_recursive_crop_does_not_cover_target(tmp_path, monkeypatch, mode, effective):
    module, service, session, raw, rect = fixture_session(tmp_path, monkeypatch)
    first = service.inspect({"action": "zoom", "gui_session_id": session["gui_session_id"], "frame_id": 0,
                             "view_id": "root", "cell_id": 1, "grid_mode": "fixed", "grid_rows": 4, "grid_cols": 4})
    result = service.inspect({"action": "zoom", "gui_session_id": session["gui_session_id"], "frame_id": 0,
                              "view_id": first["data"]["view_id"], "cell_id": 1, "grid_mode": "fixed",
                              "grid_rows": 4, "grid_cols": 4, "zoom_scale_percent": 800, "overlay": mode})
    data = result["data"]
    assert data["image_size"] == {"width": 576, "height": 256}
    assert data["sampling"]["source_pixels"] == {"width": 18, "height": 8}
    assert data["sampling"]["display_pixels_per_screen_pixel"] == 32
    assert data["overlay"]["effective"] == effective
    assert data["overlay"]["labels_visible"] == (mode == "labels+lines")
    assert data["overlay"]["labels_hidden_reason"] is None
    with Image.open(result["image_path"]) as image:
        assert image.getpixel((50, 50)) == (35, 35, 35)
        # Cell boundaries follow whole source pixels, at the cumulative 4*8 scale.
        assert image.getpixel((127, 50)) == image.getpixel((129, 50)) == (35, 35, 35)
        assert (image.getpixel((128, 50)) != (35, 35, 35)) == (mode != "none")
        if mode == "none":
            assert image.tobytes() == raw.crop((0, 0, 18, 8)).resize((576, 256), Image.Resampling.NEAREST).tobytes()
    assert result["warnings"]  # High magnification is explicit, not a cutoff.


def test_label_budget_and_single_pixel_boundaries():
    module = engine()
    source = {"left": 0, "top": 0, "width": 800, "height": 400}
    cells = module.build_cells(source, 4, 4)
    image = module.overlay_image(Image.new("RGB", (800, 400)), cells, source)
    assert image.info["overlay"]["labels_visible"]
    assert 9 <= image.info["overlay"]["font_size_px"] <= 16
    assert image.info["overlay"]["line_width_px"] == 1
    assert image.getpixel((199, 80)) == image.getpixel((201, 80)) == (0, 0, 0)
    assert image.getpixel((200, 80)) != (0, 0, 0)
    assert image.getpixel((80, 30)) == (0, 0, 0)


def test_small_output_does_not_silently_remove_requested_labels():
    module = engine()
    source = {"left": 0, "top": 0, "width": 18, "height": 8}
    image = module.overlay_image(Image.new("RGB", (144, 64)), module.build_cells(source, 4, 4), source)
    assert image.info["overlay"]["effective"] == "labels+lines"
    assert image.info["overlay"]["labels_visible"]
    assert image.info["overlay"]["font_size_px"] == 9
    assert image.info["overlay"]["labels_hidden_reason"] is None


def test_backtracking_overlay_and_frame_inheritance(tmp_path, monkeypatch):
    module, service, session, raw, rect = fixture_session(tmp_path, monkeypatch, overlay="lines")
    gui_id = session["gui_session_id"]
    child = service.inspect({"action": "zoom", "gui_session_id": gui_id, "frame_id": 0, "view_id": "root", "cell_id": 1})
    assert child["data"]["overlay"]["requested"] == "lines"
    assert child["data"]["parent_view_id"] == "root"
    point = {"frame_id": 0, "view_id": "1", "cell_id": 1, "x": 0.5037, "y": 0.62}
    frame, x, y = service._resolve_point(service._load_session(gui_id), point)
    preview = service._preview_coordinate(session=service._load_session(gui_id), frame=frame, arguments=point,
                                         screen_x=x, screen_y=y, mouse_before=0, keyboard_before=0)
    preview_bytes = Path(preview["image_path"]).read_bytes()
    previous_image = Path(child["image_path"])
    previous_bytes = previous_image.read_bytes()
    changed = service.inspect({"action": "view", "gui_session_id": gui_id, "frame_id": 0, "view_id": "1", "overlay": "none"})
    assert changed["data"]["frame_id"] == 0
    assert not changed["data"]["performed"]
    assert service._resolve_point(service._load_session(gui_id), point)[1:] == (x, y)
    assert Path(preview["image_path"]).read_bytes() == preview_bytes
    assert previous_image.read_bytes() == previous_bytes
    grandchild = service.inspect({"action": "zoom", "gui_session_id": gui_id, "frame_id": 0, "view_id": "1", "cell_id": 1})
    assert grandchild["data"]["overlay"]["requested"] == "none"
    assert grandchild["data"]["parent_view_id"] == "1"
    back = service.inspect({"action": "view", "gui_session_id": gui_id, "frame_id": 0, "view_id": "root"})
    assert back["data"]["overlay"]["requested"] == "lines"
    assert set(back["data"]["available_view_ids"]) == {"root", "1", "1/1"}
    service.inspect({"action": "view", "gui_session_id": gui_id, "frame_id": 0, "view_id": "root", "overlay": "none"})
    session = service._load_session(gui_id)
    fresh, _ = service._create_frame(session, reason="after_action", raw=raw, source_rect=rect)
    assert list(fresh["views"]) == ["root"]
    assert fresh["views"]["root"]["overlay"]["requested"] == "none"
    assert fresh["views"]["root"]["grid"] == {"rows": 4, "columns": 4}
    with pytest.raises(module.GuiError, match="最新Frame"):
        service.inspect({"action": "view", "gui_session_id": gui_id, "frame_id": 0, "view_id": "1"})


def test_invalid_overlay_has_no_session_mutation(tmp_path, monkeypatch):
    module, service, session, _, _ = fixture_session(tmp_path, monkeypatch)
    path = service._session_dir(session["gui_session_id"]) / "session.json"
    before = path.read_bytes()
    with pytest.raises(module.GuiError):
        service.inspect({"action": "view", "gui_session_id": session["gui_session_id"], "frame_id": 0,
                         "view_id": "root", "overlay": "invalid"})
    assert path.read_bytes() == before


def test_three_level_zoom_keeps_readable_canvas_and_redraws_overlay(tmp_path, monkeypatch):
    module, service, session, raw, _ = fixture_session(tmp_path, monkeypatch, width=640, height=512)
    view_id = "root"
    for depth in range(1, 4):
        result = service.inspect({"action": "zoom", "gui_session_id": session["gui_session_id"],
                                  "frame_id": 0, "view_id": view_id, "cell_id": 1,
                                  "grid_mode": "fixed", "grid_rows": 4, "grid_cols": 4})
        data = result["data"]
        view_id = data["view_id"]
        assert data["image_size"] == {"width": 640, "height": 512}
        assert data["sampling"]["display_pixels_per_screen_pixel"] == 4 ** depth
        assert data["overlay"]["labels_visible"]
        assert data["overlay"]["font_size_px"] == 16
        assert data["overlay"]["labels_hidden_reason"] is None
        source = data["source_rect_absolute"]
        with Image.open(result["image_path"]) as rendered:
            # Check actual pixels, not just reported line_width_px.
            boundary = round(source["width"] / 4) * (4 ** depth)
            assert rendered.getpixel((boundary, 60)) != (35, 35, 35)
            assert rendered.getpixel((boundary - 1, 60)) == (35, 35, 35)
            assert rendered.getpixel((boundary + 1, 60)) == (35, 35, 35)
            assert rendered.getpixel((50, 50)) == (35, 35, 35)
    assert data["sampling"]["source_pixels"] == {"width": 10, "height": 8}
    bare = service.inspect({"action": "view", "gui_session_id": session["gui_session_id"],
                            "frame_id": 0, "view_id": view_id, "overlay": "none"})
    with Image.open(bare["image_path"]) as rendered:
        assert rendered.tobytes() == raw.crop((0, 0, 10, 8)).resize((640, 512), Image.Resampling.NEAREST).tobytes()


@pytest.mark.parametrize("seconds,label", [
    (-1, "0s"), (0, "0s"), (59.9, "59s"), (60, "1m00s"), (3599, "59m59s"),
    (3600, "1h00m00s"), (86399, "23h59m59s"), (86400, "1d00h00m00s"),
    (360 * 86400 + 3661, "360d01h01m01s"), (366 * 86400, "366d00h00m00s"),
])
def test_lock_duration_switches_units_at_boundaries_and_never_uses_years(seconds, label):
    assert engine().format_lock_duration(seconds) == label


@pytest.mark.parametrize("width,height,dpi", [(1440, 900, 96), (1920, 1080, 144), (1080, 1920, 192)])
def test_timer_changes_only_the_right_side_of_the_small_notice(width, height, dpi):
    module = engine()
    before = module.render_lock_notice(width, height, dpi, 10)
    after = module.render_lock_notice(width, height, dpi, 11)
    assert before.size == after.size
    assert before.width <= width and before.height < 100 * dpi / 96
    changed = module.ImageChops.difference(before, after).convert("RGB").getbbox()
    assert changed and changed[0] > before.width * 0.7
    # A day count beyond a year still fits even on a portrait monitor at 200%.
    days = module.render_lock_notice(width, height, dpi, 366 * 86400 + 86399)
    assert days.width <= width and days.height < 100 * dpi / 96
    glow = module.render_lock_overlay(width, height, dpi, include_notice=False)
    assert glow.getchannel("A").getpixel((width // 2, round(30 * dpi / 96))) == 0


def test_lock_timer_uses_one_monotonic_origin_for_all_monitors_without_renewing_idle(monkeypatch):
    module = engine()
    service = module.GuiService.__new__(module.GuiService)
    service.cancel_event = threading.Event()
    service.lock_started_at = 100
    service.last_notice_second = 0
    service.last_activity = 150
    service.overlay_notices = [(11, {"width": 1440}), (22, {"width": 1920})]
    now = [159.9]
    monkeypatch.setattr(module.time, "monotonic", lambda: now[0])
    updates = []
    monkeypatch.setattr(service, "_update_lock_notice", lambda hwnd, rect, elapsed: updates.append((hwnd, elapsed)))
    monkeypatch.setattr(service, "_update_overlay", lambda *args: pytest.fail("Timer must not redraw the monitor glow"))
    service._refresh_lock_notice()
    assert updates == [(11, 59), (22, 59)]
    service._refresh_lock_notice()
    assert len(updates) == 2
    now[0] = 160
    service._refresh_lock_notice()
    assert updates[-2:] == [(11, 60), (22, 60)]
    service.last_activity = 160  # Successful GUI request renews idle, never the lock timer.
    now[0] = 3700
    service._refresh_lock_notice()
    assert updates[-2:] == [(11, 3600), (22, 3600)]
    assert service.last_activity == 160 and service.lock_started_at == 100
    service.cancel_event.set()
    now[0] = 3800
    service._refresh_lock_notice()
    assert updates[-2:] == [(11, 3600), (22, 3600)]


def test_window_timer_refreshes_in_message_loop_and_is_removed_on_unlock(monkeypatch):
    module = engine()
    service = module.GuiService.__new__(module.GuiService)
    service.overlay_windows = [123]
    service.overlay_notices = []
    service.overlay_timer_hwnd = 0
    started, killed, refreshed = [], [], []
    monkeypatch.setattr(module.user32, "SetTimer", lambda *args: started.append(args) or 1)
    monkeypatch.setattr(module.user32, "KillTimer", lambda *args: killed.append(args) or True)
    monkeypatch.setattr(module.user32, "IsWindow", lambda *args: False)
    monkeypatch.setattr(service, "_refresh_lock_notice", lambda: refreshed.append(True))
    service._start_overlay_timer()
    assert started == [(123, module.LOCK_NOTICE_TIMER_ID, 1000, None)]
    assert service._window_proc(123, module.WM_TIMER, module.LOCK_NOTICE_TIMER_ID, 0) == 0
    assert refreshed == [True]
    service._destroy_windows()
    service._destroy_windows()
    assert killed == [(123, module.LOCK_NOTICE_TIMER_ID)]
    assert not service.overlay_windows and service.overlay_timer_hwnd == 0


def test_failed_notice_tick_does_not_leave_an_input_lock_with_frozen_status(monkeypatch):
    module = engine()
    service = module.GuiService.__new__(module.GuiService)
    service.overlay_timer_hwnd = 123
    stops = []
    monkeypatch.setattr(service, "request_stop", stops.append)
    def fail():
        raise module.GuiError("OVERLAY_RENDER_FAILED", "simulated failure")
    monkeypatch.setattr(service, "_refresh_lock_notice", fail)
    assert service._window_proc(123, module.WM_TIMER, module.LOCK_NOTICE_TIMER_ID, 0) == 0
    assert stops == ["overlay_timer_failed"]
