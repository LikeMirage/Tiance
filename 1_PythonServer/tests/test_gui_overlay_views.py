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


@pytest.mark.parametrize("mode,effective", [("labels+lines", "lines"), ("lines", "lines"), ("none", "none")])
def test_tiny_recursive_crop_does_not_cover_target(tmp_path, monkeypatch, mode, effective):
    module, service, session, raw, rect = fixture_session(tmp_path, monkeypatch)
    first = service.inspect({"action": "zoom", "gui_session_id": session["gui_session_id"], "frame_id": 0,
                             "view_id": "root", "cell_id": 1, "grid_mode": "fixed", "grid_rows": 4, "grid_cols": 4})
    result = service.inspect({"action": "zoom", "gui_session_id": session["gui_session_id"], "frame_id": 0,
                              "view_id": first["data"]["view_id"], "cell_id": 1, "grid_mode": "fixed",
                              "grid_rows": 4, "grid_cols": 4, "zoom_scale_percent": 800, "overlay": mode})
    data = result["data"]
    assert data["image_size"] == {"width": 144, "height": 64}
    assert data["sampling"]["source_pixels"] == {"width": 18, "height": 8}
    assert data["sampling"]["display_pixels_per_screen_pixel"] == 8
    assert data["overlay"]["effective"] == effective
    assert data["overlay"]["labels_visible"] is False
    assert data["overlay"]["labels_hidden_reason"] == ("cells_too_small" if mode == "labels+lines" else None)
    with Image.open(result["image_path"]) as image:
        assert image.getpixel((5, 5)) == (35, 35, 35)
        # Cell boundaries follow whole source pixels: round(18 / 4) * 8 = 32.
        assert image.getpixel((31, 10)) == image.getpixel((33, 10)) == (35, 35, 35)
        assert (image.getpixel((32, 10)) != (35, 35, 35)) == (mode != "none")
        if mode == "none":
            assert image.tobytes() == raw.crop((0, 0, 18, 8)).resize((144, 64), Image.Resampling.NEAREST).tobytes()
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


def test_backtracking_overlay_and_frame_inheritance(tmp_path, monkeypatch):
    module, service, session, raw, rect = fixture_session(tmp_path, monkeypatch, overlay="lines")
    gui_id = session["gui_session_id"]
    child = service.inspect({"action": "zoom", "gui_session_id": gui_id, "frame_id": 0, "view_id": "root", "cell_id": 1})
    assert child["data"]["overlay"]["requested"] == "lines"
    assert child["data"]["parent_view_id"] == "root"
    point = {"frame_id": 0, "view_id": "1", "cell_id": 1, "x": 0.5037, "y": 0.62}
    frame, x, y = service._resolve_point(service._load_session(gui_id), point)
    preview = service._preview_coordinate(session=service._load_session(gui_id), frame=frame, arguments=point,
                                         screen_x=x, screen_y=y, difference=0, mouse_before=0, keyboard_before=0)
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
