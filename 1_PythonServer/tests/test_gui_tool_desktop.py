"""显式选择的真实桌面回归：TIANCE_GUI_DESKTOP_TEST=1。仅点击测试自身窗口。"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import traceback
from importlib.util import module_from_spec, spec_from_file_location

import pytest


@pytest.mark.skipif(os.name != "nt" or os.environ.get("TIANCE_GUI_DESKTOP_TEST") != "1", reason="需要显式选择真实桌面验证")
def test_locked_nested_zoom_click_user_movement_and_exit(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    tools_root = root / "Data/tools"
    runtime = tools_root / "c7dd4066-37a6-4b1e-a67a-d39f0c6d4a21/program/main.py"
    inspect = tools_root / "b0548165-4df0-45ff-8dd0-4f614db9812b/program/main.py"
    mouse = tools_root / "08cb1494-bf1e-47a9-bbb5-add9c576db62/program/main.py"
    python = root / "runtime/python/py313/python.exe"
    state_path = Path(tempfile.gettempdir()) / "Tiance/gui-control/active-lock.json"
    assert not state_path.exists(), "已有用户GUI会话，不可覆盖"
    spec = spec_from_file_location("gui_desktop_test_helper", runtime.with_name("overlay_helper.py"))
    helper = module_from_spec(spec)
    spec.loader.exec_module(helper)
    user32 = helper.user32
    user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    user32.FindWindowW.restype = wintypes.HWND
    user32.UpdateWindow.argtypes = [wintypes.HWND]
    env = {**os.environ, "TIANCE_WORKSPACE_ROOT": str(tmp_path), "TIANCE_PROJECT_ID": "gui-regression", "TIANCE_SESSION_ID": "gui-regression", "PYTHONPATH": str(root / "1_PythonServer")}
    errors = []
    clicked = []
    done = threading.Event()
    monitored_overlays = set()
    hidden_overlays = []
    checking_visibility = threading.Event()
    event_proc_type = ctypes.WINFUNCTYPE(None, wintypes.HANDLE, wintypes.DWORD, wintypes.HWND, wintypes.LONG, wintypes.LONG, wintypes.DWORD, wintypes.DWORD)
    user32.SetWinEventHook.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.HMODULE, event_proc_type, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD]
    user32.SetWinEventHook.restype = wintypes.HANDLE
    user32.UnhookWinEvent.argtypes = [wintypes.HANDLE]

    @event_proc_type
    def visibility_event(_hook, event, hwnd, object_id, _child, _thread, _time):
        if checking_visibility.is_set() and event == 0x8003 and object_id == 0 and int(hwnd or 0) in monitored_overlays:
            hidden_overlays.append(int(hwnd))

    def call(entry: Path, payload: dict) -> dict:
        completed = subprocess.run([str(python), str(entry)], input=json.dumps(payload), text=True, encoding="utf-8", capture_output=True, env=env, timeout=20, creationflags=0x08000000)
        assert completed.returncode == 0, completed.stdout + completed.stderr
        result = json.loads(completed.stdout)
        assert result.get("ok"), result
        return result

    def await_stopped() -> None:
        deadline = time.monotonic() + 5
        while state_path.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert not state_path.exists(), "解锁后运行器未退出"
        assert not list((tmp_path / ".Tiance/gui-temp").glob("gui_*"))

    def worker(hwnd: int) -> None:
        try:
            with helper.physical_coordinates():
                started = call(runtime, {"action": "start"})
                assert started["data"]["input_mode"] == "blocked"
                assert started["data"]["capture_mode"] == "exclude_from_capture"
                overlay_hwnd = user32.FindWindowW(None, "Tiance AI Control Overlay")
                exit_hwnd = user32.FindWindowW(None, "退出AI操控")
                assert overlay_hwnd and not exit_hwnd
                monitored_overlays.add(int(overlay_hwnd))
                checking_visibility.set()
                first = call(inspect, {"action": "start", "target": "window", "hwnd": hwnd, "grid_mode": "fixed", "grid_rows": 2, "grid_cols": 2})
                gui_id = first["data"]["gui_session_id"]
                with helper.Image.open(tmp_path / ".Tiance/gui-temp" / gui_id / "frame_000/root_raw.png") as captured:
                    assert captured.getpixel((10, 10)) == (44, 62, 85), "截图包含了覆盖层"
                zoom = call(inspect, {"action": "zoom", "gui_session_id": gui_id, "frame_id": 0, "view_id": "root", "cell_id": 1, "grid_mode": "fixed", "grid_rows": 2, "grid_cols": 2})
                zoom = call(inspect, {"action": "zoom", "gui_session_id": gui_id, "frame_id": 0, "view_id": zoom["data"]["view_id"], "cell_id": 4, "grid_mode": "fixed", "grid_rows": 2, "grid_cols": 2, "zoom_scale_percent": 600})
                args = {"gui_session_id": gui_id, "frame_id": 0, "view_id": zoom["data"]["view_id"], "cell_id": 2, "x": 0.3, "y": 0.6}
                preview = call(mouse, {"action": "preview", "preview_action": "click", **args})
                selected = preview["data"]["selected_coordinate"]
                execute = {"action": "execute_preview", "preview_id": preview["data"]["preview_id"]}
                result = call(mouse, execute)
                assert result["data"]["performed"], result
                time.sleep(0.05)
                rect = helper.window_rect(hwnd)
                expected = (selected["screen_x"] - rect["left"], selected["screen_y"] - rect["top"])
                assert clicked == [expected], (clicked, expected)
                repeated = call(mouse, execute)
                assert repeated["data"]["preview_reused"] and clicked == [expected]
                assert user32.IsWindowVisible(overlay_hwnd)
                assert not hidden_overlays, "截图或操作中隐藏了覆盖层"
                checking_visibility.clear()
                # 同一Windows输入钩子路径，使用无天策标记的事件模拟用户设备输入。
                outsider = helper.GuiService.__new__(helper.GuiService)
                outsider.marker = 0
                outsider.cancel_event = threading.Event()
                outsider.held_mouse_buttons = set()
                outsider.held_keys = set()
                before_pointer = helper.POINT()
                assert user32.GetCursorPos(ctypes.byref(before_pointer))
                outsider._mouse_move_event(250, 220)
                time.sleep(0.05)
                after_pointer = helper.POINT()
                assert user32.GetCursorPos(ctypes.byref(after_pointer))
                assert (before_pointer.x, before_pointer.y) == (after_pointer.x, after_pointer.y), "用户鼠标移动未被拦截"
                outsider._mouse_flag(helper.MOUSEEVENTF_LEFTDOWN)
                outsider._mouse_flag(helper.MOUSEEVENTF_LEFTUP)
                time.sleep(0.05)
                assert clicked == [expected], "用户点击穿透了锁定"
                assert state_path.exists(), "用户点击错误地解锁了"
                # 30秒截图等待中的Esc必须取消；此前跨调用按住的鼠标也要释放。
                held = call(mouse, {"action": "mouse_down", "gui_session_id": gui_id, "frame_id": 1, "view_id": "root", "cell_id": 1, "x": 0.3, "y": 0.6, "screenshot_delay_seconds": 0})
                assert held["data"]["performed"] and user32.GetAsyncKeyState(1) & 0x8000
                outsider._mouse_move_event(260, 230)
                time.sleep(0.05)
                assert user32.GetAsyncKeyState(1) & 0x8000, "被拦截的移动不应释放AI持有的按钮"
                pending = subprocess.Popen([str(python), str(mouse)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", env=env, creationflags=0x08000000)
                pending.stdin.write(json.dumps({"action": "move", "gui_session_id": gui_id, "frame_id": 2, "view_id": "root", "cell_id": 1, "x": 0.3, "y": 0.6, "screenshot_delay_seconds": 30}) + "\n")
                pending.stdin.close()
                pending.stdin = None
                try:
                    time.sleep(1.5)
                    assert pending.poll() is None, "wait在用户退出前意外结束"
                    outsider._press_key("esc", 1, 0)
                    await_stopped()
                    output, _error = pending.communicate(timeout=5)
                    assert not json.loads(output)["ok"], "被用户取消的等待报告了成功"
                    assert not user32.GetAsyncKeyState(1) & 0x8000, "退出后AI按住的按钮没有释放"
                finally:
                    if pending.poll() is None:
                        pending.terminate()
                        pending.wait(timeout=5)
                print(json.dumps({"nested_preview_screen_point": [selected["screen_x"], selected["screen_y"]], "received_click_client_point": list(clicked[0]), "preview_id_executed_once": True, "overlay_hide_events": len(hidden_overlays), "user_mouse_blocked": True, "click_did_not_unlock": True, "escape_unlocked": True, "held_button_released": True, "waiting_cancelled": True, "cleaned": True}))
        except BaseException:
            errors.append(traceback.format_exc())
        finally:
            if state_path.exists():
                try:
                    call(runtime, {"action": "stop"})
                    await_stopped()
                except BaseException:
                    errors.append(traceback.format_exc())
            done.set()

    with helper.physical_coordinates():
        @helper.WNDPROC
        def window_proc(hwnd, message, wparam, lparam):
            if message == helper.WM_PAINT:
                paint = helper.PAINTSTRUCT()
                dc = user32.BeginPaint(hwnd, ctypes.byref(paint))
                rect = wintypes.RECT()
                user32.GetClientRect(hwnd, ctypes.byref(rect))
                user32.FillRect(dc, ctypes.byref(rect), brush)
                user32.EndPaint(hwnd, ctypes.byref(paint))
                return 0
            if message == helper.WM_LBUTTONUP:
                clicked.append((ctypes.c_short(lparam & 0xFFFF).value, ctypes.c_short((lparam >> 16) & 0xFFFF).value))
                return 0
            return user32.DefWindowProcW(hwnd, message, wparam, lparam)

        instance = helper.kernel32.GetModuleHandleW(None)
        class_name = f"TianceGuiRegression_{os.getpid()}"
        brush = helper.gdi32.CreateSolidBrush(helper.colorref(44, 62, 85))
        window_class = helper.WNDCLASSEXW(cbSize=ctypes.sizeof(helper.WNDCLASSEXW), lpfnWndProc=window_proc, hInstance=instance, hbrBackground=brush, lpszClassName=class_name)
        assert user32.RegisterClassExW(ctypes.byref(window_class))
        hwnd = user32.CreateWindowExW(0, class_name, "Tiance GUI regression target", helper.WS_POPUP, 200, 160, 900, 650, 0, 0, instance, None)
        assert hwnd
        user32.ShowWindow(hwnd, 5)
        user32.UpdateWindow(hwnd)
        event_hook = user32.SetWinEventHook(0x8002, 0x8003, 0, visibility_event, 0, 0, 0)
        assert event_hook
        thread = threading.Thread(target=worker, args=(int(hwnd),), daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 55
            while not done.is_set() and time.monotonic() < deadline:
                message = wintypes.MSG()
                while user32.PeekMessageW(ctypes.byref(message), 0, 0, 0, 1):
                    user32.TranslateMessage(ctypes.byref(message))
                    user32.DispatchMessageW(ctypes.byref(message))
                time.sleep(0.005)
            assert done.is_set(), "真实桌面测试超时"
            assert not errors, "\n".join(errors)
        finally:
            user32.UnhookWinEvent(event_hook)
            user32.DestroyWindow(hwnd)
            helper.gdi32.DeleteObject(brush)
