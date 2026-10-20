"""Display overlays and view navigation without sending input to the desktop."""
from contextlib import nullcontext
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


def fixture_session(tmp_path, monkeypatch, *, overlay="labels+lines", width=288, height=128, grid_rows=4, grid_cols=4):
    module = engine()
    service = module.GuiService.__new__(module.GuiService)
    service._init_activity()
    service.overlay_windows = []
    service.created_gui_sessions = set()
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
    service._create_frame(session, reason="test", raw=raw, source_rect=rect, grid_mode="fixed", grid_rows=grid_rows, grid_cols=grid_cols, overlay=overlay)
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
    assert data["image_size"] == {"width": 288, "height": 128}
    assert data["sampling"]["source_pixels"] == {"width": 18, "height": 8}
    assert data["sampling"]["display_pixels_per_screen_pixel"] == 16
    assert data["zoom_scale_percent"] == 800
    assert data["effective_zoom_scale_percent"] == 400
    assert data["zoom_limited_by_parent"]
    assert data["overlay"]["effective"] == effective
    assert data["overlay"]["labels_visible"] == (mode == "labels+lines")
    assert data["overlay"]["labels_hidden_reason"] is None
    with Image.open(result["image_path"]) as image:
        assert image.getpixel((50, 50)) == (35, 35, 35)
        # The bound is applied before drawing: grid lines remain one output pixel.
        assert image.getpixel((63, 25)) == image.getpixel((65, 25)) == (35, 35, 35)
        assert (image.getpixel((64, 25)) != (35, 35, 35)) == (mode != "none")
        if mode == "none":
            assert image.tobytes() == raw.crop((0, 0, 18, 8)).resize((288, 128), Image.Resampling.NEAREST).tobytes()
    assert any("父View" in warning for warning in result["warnings"])


def test_navigation_strip_zoom_stays_inside_parent_before_allocating(tmp_path, monkeypatch):
    # Reproduce the 1936x1056 -> two cells -> entire middle row failure.
    module, service, session, _, _ = fixture_session(tmp_path, monkeypatch, width=1936, height=1056, grid_cols=5)
    sizes = []
    resize = Image.Image.resize
    def track_resize(image, size, *args, **kwargs):
        sizes.append(size)
        assert size[0] <= 1936 and size[1] <= 1056
        return resize(image, size, *args, **kwargs)
    monkeypatch.setattr(Image.Image, "resize", track_resize)
    common = {"action": "zoom", "gui_session_id": session["gui_session_id"], "frame_id": 0,
              "grid_mode": "fixed", "grid_cols": 8}
    first = service.inspect({**common, "view_id": "root", "cell_ids": [1, 2],
                             "grid_rows": 3, "zoom_scale_percent": 400})
    assert first["data"]["image_size"] == {"width": 1936, "height": 660}
    second = service.inspect({**common, "view_id": first["data"]["view_id"], "cell_ids": list(range(9, 17)),
                              "grid_rows": 1, "zoom_scale_percent": 300})
    assert second["data"]["sampling"]["source_pixels"] == {"width": 774, "height": 88}
    assert second["data"]["image_size"] == {"width": 1936, "height": 220}
    assert second["data"]["effective_zoom_scale_percent"] == pytest.approx(100)
    assert second["data"]["zoom_limited_by_parent"]
    third = service.inspect({**common, "view_id": second["data"]["view_id"], "cell_ids": list(range(1, 9)),
                             "grid_rows": 1, "zoom_scale_percent": 800})
    assert third["data"]["image_size"] == second["data"]["image_size"]
    assert sizes == [(1936, 660), (1936, 220), (1936, 220)]
    with Image.open(third["image_path"]) as image:
        assert image.size == (1936, 220)


@pytest.mark.parametrize("cells,expected_size", [
    ([1, 2], (800, 200)),  # A full row cannot grow wider.
    ([1, 3], (400, 400)),  # A full column cannot grow taller.
    ([1, 2, 3, 4], (800, 400)),  # Selecting everything cannot increase resolution.
    ([1], (800, 400)),  # A small selection can still fill the parent canvas.
])
def test_zoom_fits_both_axes_without_stretching_or_changing_source(tmp_path, monkeypatch, cells, expected_size):
    module, service, session, raw, rect = fixture_session(tmp_path, monkeypatch, width=800, height=400, grid_rows=2, grid_cols=2)
    result = service.inspect({"action": "zoom", "gui_session_id": session["gui_session_id"], "frame_id": 0,
                              "view_id": "root", "cell_ids": cells, "zoom_scale_percent": 800, "overlay": "none"})
    data = result["data"]
    assert data["image_size"] == dict(zip(("width", "height"), expected_size))
    assert data["zoom_limited_by_parent"]
    source = data["source_rect_absolute"]
    assert data["sampling"]["display_pixels_per_screen_pixel"] == data["sampling"]["display_pixels_per_screen_pixel_y"]
    box = (source["left"] - rect["left"], source["top"] - rect["top"],
           source["left"] - rect["left"] + source["width"], source["top"] - rect["top"] + source["height"])
    frame = service._load_session(session["gui_session_id"])["frames"][0]
    view = frame["views"][data["view_id"]]
    with Image.open(service._session_dir(session["gui_session_id"]) / view["raw_image"]) as saved:
        assert saved.tobytes() == raw.crop(box).tobytes()
    with Image.open(result["image_path"]) as image:
        assert image.tobytes() == raw.crop(box).resize(expected_size, Image.Resampling.NEAREST).tobytes()


def test_zoom_respects_immediate_parent_and_view_reuses_bounded_size(tmp_path, monkeypatch):
    module, service, session, _, _ = fixture_session(tmp_path, monkeypatch, width=800, height=400, grid_rows=2, grid_cols=2)
    common = {"action": "zoom", "gui_session_id": session["gui_session_id"], "frame_id": 0,
              "cell_id": 1, "grid_mode": "fixed", "grid_rows": 2, "grid_cols": 2}
    first = service.inspect({**common, "view_id": "root", "zoom_scale_percent": 100})
    assert first["data"]["image_size"] == {"width": 400, "height": 200}
    assert not first["data"]["zoom_limited_by_parent"]
    second = service.inspect({**common, "view_id": first["data"]["view_id"], "zoom_scale_percent": 800})
    assert second["data"]["image_size"] == first["data"]["image_size"]
    bare = service.inspect({"action": "view", "gui_session_id": session["gui_session_id"], "frame_id": 0,
                            "view_id": second["data"]["view_id"], "overlay": "none"})
    assert bare["data"]["image_size"] == second["data"]["image_size"]
    assert bare["data"]["effective_zoom_scale_percent"] == second["data"]["effective_zoom_scale_percent"]
    assert bare["data"]["zoom_limited_by_parent"]
    with Image.open(bare["image_path"]) as image:
        assert image.size == (400, 200)


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


def test_activity_tracks_view_tree_frame_reset_and_close(tmp_path, monkeypatch):
    module, service, session, raw, rect = fixture_session(tmp_path, monkeypatch, width=800, height=600, grid_rows=2, grid_cols=2)
    common = {"action": "zoom", "gui_session_id": session["gui_session_id"], "frame_id": 0,
              "grid_mode": "fixed", "grid_rows": 2, "grid_cols": 2}
    first = service.inspect({**common, "view_id": "root", "cell_id": 4})
    second = service.inspect({**common, "view_id": first["data"]["view_id"], "cell_id": 1})
    state = service._activity_status()["observation"]
    assert state["path"] == ["root", "4", "4/1"] and state["depth"] == 2
    assert state["source_rect_absolute"] == second["data"]["source_rect_absolute"]
    assert state["source_rect_absolute"]["width"] == 200
    assert second["data"]["image_size"]["width"] == 800  # Overlay uses screen coordinates, not this enlargement.
    assert "cells" not in state  # status stays compact, geometry is held by the renderer.
    state["grid"]["rows"] = 99
    assert service._activity_status()["observation"]["grid"]["rows"] == 2
    service.inspect({"action": "view", "gui_session_id": session["gui_session_id"], "frame_id": 0, "view_id": "4"})
    assert service._activity_status()["observation"]["depth"] == 1
    session = service._load_session(session["gui_session_id"])
    # A batch item may operate a different view from the last inspected one.
    monkeypatch.setattr(service, "_target_rect", lambda target: rect)
    monkeypatch.setattr(service, "_mouse_click", lambda *args: None)
    monkeypatch.setattr(service, "_hold_modifiers", lambda *args: nullcontext())
    service._execute_batch_item(session, {"type": "click", "frame_id": 0, "view_id": "root", "cell_id": 1})
    assert service._activity_status()["observation"]["view_id"] == "root"
    service._invalidate_activity_view({"gui_session_id": "gui_" + "a" * 32}, close=True)
    assert service._activity_status()["observation"]["view_id"] == "root"
    service._invalidate_frame(session)
    assert not service._activity_status()["observation"]["valid"]
    frame, path = service._create_frame(session, reason="refresh", raw=raw, source_rect=rect)
    service._result_with_image(summary="", session=session, frame=frame, view=frame["views"]["root"], image_path=path)
    assert service._activity_status()["observation"]["frame_id"] == 1
    assert service._activity_status()["observation"]["path"] == ["root"]
    assert service._activity_status()["observation"]["valid"]
    service.inspect({"action": "close", "gui_session_id": session["gui_session_id"]})
    assert service._activity_status()["observation"] is None
    assert service._activity_status()["pointer"] is None


@pytest.mark.parametrize("monitor_left", [-400, 0])
def test_activity_mask_and_grid_align_on_negative_and_cross_monitor_coordinates(monitor_left):
    module = engine()
    source = {"left": -200, "top": 100, "width": 400, "height": 200}
    observation = {"valid": True, "source_rect_absolute": source, "cells": module.build_cells(source, 2, 2)}
    monitor = {"left": monitor_left, "top": 0, "width": 400, "height": 400}
    image = module.render_activity_overlay(monitor, 144, observation)
    inside_x, outside_x = (300, 100) if monitor_left < 0 else (100, 300)
    assert image.size == (400, 400)
    assert image.getpixel((inside_x, 180))[3] == 0
    assert image.getpixel((outside_x, 180))[3] == 140
    assert image.getpixel((inside_x, 199))[3] == 0
    assert image.getpixel((inside_x, 200))[3] == 200
    assert image.getpixel((inside_x, 201))[3] == 0  # One physical pixel; DPI does not move grid lines.
    invalid = module.render_activity_overlay(monitor, 144, {**observation, "valid": False})
    assert invalid.getpixel((inside_x, 200))[3] == invalid.getpixel((outside_x, 180))[3] == 0


def test_activity_coalesces_events_and_pointer_updates_do_not_repaint_grid(tmp_path, monkeypatch):
    module, service, session, _, rect = fixture_session(tmp_path, monkeypatch, width=800, height=600)
    service.overlay_windows = [10]
    service.overlay_canvases = [(11, rect)]
    service.overlay_pointers = [(12, rect)]
    service.overlay_notices = []
    service.lock_started_at = None
    posted, uploads, shown = [], [], []
    monkeypatch.setattr(module.user32, "PostMessageW", lambda *args: posted.append(args) or True)
    monkeypatch.setattr(module.user32, "GetDpiForWindow", lambda *args: 96)
    monkeypatch.setattr(module.user32, "ShowWindow", lambda *args: shown.append(args) or True)
    monkeypatch.setattr(service, "_upload_overlay_image", lambda hwnd, position, image: uploads.append((hwnd, position, image.size)))
    frame = session["frames"][0]
    service._show_activity_view(session, frame, frame["views"]["root"])
    for x in range(100):
        service._publish_activity(pointer={"x": x, "y": 200, "phase": "moving"})
    assert posted == [(10, module.WM_APP_ACTIVITY, 0, 0)]
    service._flush_activity()
    assert [entry[0] for entry in uploads] == [11, 12]
    assert uploads[0][2] == (800, 600) and uploads[1][2] == (48, 56)
    assert uploads[1][1] == {"left": 99 - rect["left"] - 14, "top": 200 - rect["top"] - 14}
    service._publish_activity(pointer={"x": 120, "y": 220, "phase": "pressed"})
    service._flush_activity()
    assert [entry[0] for entry in uploads] == [11, 12, 12]
    service._publish_activity(pointer={"x": 9999, "y": 220, "phase": "moving"})
    service._flush_activity()
    assert shown[-1] == (12, 0)
    revision = service._activity_status()["revision"]
    service.cancel_event.set()
    service._publish_activity(pointer=None)
    assert service._activity_status()["revision"] == revision


def test_activity_preview_is_distinct_from_actual_input_and_handles_window_offset(tmp_path, monkeypatch):
    module, service, session, _, rect = fixture_session(tmp_path, monkeypatch, width=800, height=600)
    service.external_mouse_events = service.external_keyboard_events = 0
    service.block_user_input = True
    service.held_mouse_buttons = set()
    service.marker = 123
    session["target"] = {"type": "window"}
    current_rect = {**rect, "left": rect["left"] + 120, "top": rect["top"] + 40}
    monkeypatch.setattr(service, "_target_rect", lambda target: current_rect)
    frame = session["frames"][0]
    service._preview_coordinate(session=session, frame=frame, arguments={"view_id": "root"},
                                screen_x=100, screen_y=200, mouse_before=0, keyboard_before=0)
    assert service._activity_status()["observation"]["source_rect_absolute"] == current_rect
    assert service._activity_status()["pointer"] == {"x": 100, "y": 200, "phase": "preview"}
    assert frame["views"]["root"]["source_rect_absolute"] == rect
    preview_image, _ = module.render_activity_pointer(96, service._activity_status()["pointer"])
    sent = []
    monkeypatch.setattr(service, "_virtual_metrics", lambda: (-500, -500, 2000, 2000))
    monkeypatch.setattr(service, "_send_input", lambda *args, **kwargs: sent.append(args))
    service._mouse_move_event(101, 201)
    service._mouse_flag(module.MOUSEEVENTF_LEFTDOWN, button="left")
    assert service._activity_status()["pointer"]["phase"] == "pressed"
    click_image, _ = module.render_activity_pointer(96, service._activity_status()["pointer"])
    assert click_image.tobytes() != preview_image.tobytes()
    service._mouse_flag(module.MOUSEEVENTF_LEFTUP, button="left")
    assert service._activity_status()["pointer"]["phase"] == "released" and len(sent) == 3
    def rejected(*args, **kwargs):
        raise module.GuiError("INPUT_DESKTOP_UNAVAILABLE", "input rejected")
    monkeypatch.setattr(service, "_send_input", rejected)
    with pytest.raises(module.GuiError):
        service._mouse_move_event(300, 300)
    assert service._activity_status()["pointer"]["x"] == 101


def test_activity_reports_tool_failure_without_displaying_input_text(tmp_path, monkeypatch):
    module, service, _, _, _ = fixture_session(tmp_path, monkeypatch)
    service.service_lock = threading.RLock()
    service.token, service.project_id, service.session_id = "token", "project", "session"
    service.block_user_input = True
    seen = []
    def keyboard(arguments):
        seen.append(service._activity_status()["action"])
        raise module.GuiError("GUI_FOCUS_CHANGED", "focus changed")
    monkeypatch.setattr(service, "keyboard", keyboard)
    request = {"token": "token", "project_id": "project", "session_id": "session", "method": "keyboard",
               "payload": {"action": "type_text", "text": "secret input"}}
    with pytest.raises(module.GuiError):
        service._dispatch(request)
    assert seen == [{"tool": "keyboard", "name": "type_text", "phase": "running"}]
    assert service._activity_status()["action"] == {"tool": "keyboard", "name": "type_text", "phase": "failed"}
    assert "secret input" not in str(service._activity_status())
    title, _ = module.activity_notice_lines(service._activity_status())
    assert "输入文字" in title and "失败" in title


def test_activity_batch_steps_and_uia_use_the_same_runtime_state(tmp_path, monkeypatch):
    module, service, session, _, rect = fixture_session(tmp_path, monkeypatch)
    service.service_lock = threading.RLock()
    service.token, service.project_id, service.session_id = "token", "project", "session"
    service.input_events_sent = 0
    seen = []
    monkeypatch.setattr(service, "_preflight", lambda current: (current["frames"][0], rect))
    monkeypatch.setattr(service, "_ai_input", lambda current: nullcontext((0, 0)))
    monkeypatch.setattr(service, "_finish_action", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(service, "_execute_batch_item", lambda *args: seen.append(service._activity_status()["action"]) or {})
    request = {"token": "token", "project_id": "project", "session_id": "session", "method": "batch",
               "payload": {"gui_session_id": session["gui_session_id"], "frame_id": 0,
                           "actions": [{"type": "wait"}, {"type": "wait"}]}}
    assert service._dispatch(request)["ok"]
    assert [(state["step"], state["total"], state["phase"]) for state in seen] == [(1, 2, "running"), (2, 2, "running")]
    assert service._activity_status()["action"]["phase"] == "completed"
    monkeypatch.setattr(service, "uia", lambda args: seen.append(service._activity_status()["action"]) or {"ok": True})
    assert service._dispatch({**request, "method": "uia", "payload": {"action": "invoke"}})["ok"]
    assert seen[-1] == {"tool": "uia", "name": "invoke", "phase": "running"}
    assert service._activity_status()["pointer"] is None  # UIA is not a physical click.


def test_activity_display_failure_releases_runtime_and_cleanup_discards_state(tmp_path, monkeypatch):
    module, service, _, _, _ = fixture_session(tmp_path, monkeypatch)
    service.overlay_windows = [123]
    service.overlay_notices = []
    service.overlay_timer_hwnd = 0
    stops = []
    monkeypatch.setattr(module.user32, "PostMessageW", lambda *args: False)
    monkeypatch.setattr(module.user32, "IsWindow", lambda *args: False)
    monkeypatch.setattr(service, "request_stop", stops.append)
    service._publish_activity(action={"name": "click", "phase": "running"})
    assert stops == ["overlay_activity_failed"]
    def fail():
        raise RuntimeError("upload failed")
    monkeypatch.setattr(service, "_flush_activity", fail)
    assert service._window_proc(123, module.WM_APP_ACTIVITY, 0, 0) == 0
    assert stops == ["overlay_activity_failed", "overlay_activity_failed"]
    service._destroy_windows()
    assert service._activity_status() == {"revision": 0, "observation": None, "pointer": None, "action": None}
    assert not service.overlay_canvases and not service.overlay_pointers
