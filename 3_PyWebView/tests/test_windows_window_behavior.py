from __future__ import annotations

import sys
from types import SimpleNamespace

from app import api as api_module
from app.api import ShellApi
import pytest


class _Event:
    def __init__(self) -> None:
        self.handlers: list[object] = []

    def __iadd__(self, handler: object) -> "_Event":
        self.handlers.append(handler)
        return self


def _confirmed_close(api):
    # Simulate the current frontend confirmation without starting a real JS dispatch.
    api._close_coordinator._spawn = lambda action: None
    request_id = api.request_window_close("exit")
    try:
        return api.close_window(request_id)
    finally:
        api._close_coordinator.dispose()


def test_select_external_files_returns_existing_unique_files(monkeypatch, tmp_path) -> None:
    first_file = tmp_path / "first.txt"
    second_file = tmp_path / "second.txt"
    ignored_folder = tmp_path / "folder"
    first_file.write_text("first", encoding="utf-8")
    second_file.write_text("second", encoding="utf-8")
    ignored_folder.mkdir()
    dialog_calls: list[tuple[int, bool]] = []

    def create_file_dialog(dialog_type: int, *, allow_multiple: bool):
        dialog_calls.append((dialog_type, allow_multiple))
        return [
            str(first_file),
            str(second_file),
            str(first_file),
            str(ignored_folder),
            str(tmp_path / "missing.txt"),
        ]

    shell_api = ShellApi(
        SimpleNamespace(allow_remote_shell_api=False),
        SimpleNamespace(),
    )
    shell_api._window = SimpleNamespace(
        create_file_dialog=create_file_dialog,
        url="http://127.0.0.1:18100",
    )
    monkeypatch.setitem(
        sys.modules,
        "webview",
        SimpleNamespace(FileDialog=SimpleNamespace(OPEN=10)),
    )

    result = shell_api.select_external_files()

    assert dialog_calls == [(10, True)]
    assert result == [
        {"kind": "file", "name": "first.txt", "path": str(first_file.resolve())},
        {"kind": "file", "name": "second.txt", "path": str(second_file.resolve())},
    ]


def test_backend_start_failure_returns_stable_error_without_internal_details(monkeypatch) -> None:
    class FailingBackendManager:
        started_by_shell = False

        def ensure_running(self) -> None:
            raise RuntimeError(r"secret failure at C:\private\backend.exe")

    shell_api = ShellApi(
        SimpleNamespace(allow_remote_shell_api=False),
        FailingBackendManager(),
    )
    shell_api._window = SimpleNamespace(url="http://127.0.0.1:18100")
    monkeypatch.setattr(api_module, "mark", lambda *_args, **_kwargs: None)

    result = shell_api.ensure_backend_running()

    assert result == {
        "ok": False,
        "startedByShell": False,
        "errorCode": "backend_start_failed",
        "error": "后端服务启动失败。请重试；仍失败时查看 Data/logs/desktop-backend.log。",
    }
    assert "private" not in result["error"]


def test_shell_mutation_is_rejected_after_navigation_to_remote_page() -> None:
    shell_api = ShellApi(
        SimpleNamespace(allow_remote_shell_api=False),
        SimpleNamespace(),
    )
    shell_api._window = SimpleNamespace(url="https://example.com")

    with pytest.raises(PermissionError, match="not available"):
        shell_api.minimize_window()


def test_software_update_is_rejected_in_source_checkout(monkeypatch, tmp_path) -> None:
    shell_api = ShellApi(SimpleNamespace(allow_remote_shell_api=False), SimpleNamespace())
    shell_api._window = SimpleNamespace(url="http://127.0.0.1:18100")
    stage_root = tmp_path / "stage"
    stage_root.mkdir()
    monkeypatch.setattr(api_module, "_project_root", lambda: tmp_path / "source")
    (tmp_path / "source" / ".git").mkdir(parents=True)

    result = shell_api.install_software_update(str(stage_root))

    assert result["ok"] is False
    assert result["errorCode"] == "updater_launch_failed"


def test_external_browser_only_accepts_github_https_urls(monkeypatch) -> None:
    shell_api = ShellApi(
        SimpleNamespace(allow_remote_shell_api=False),
        SimpleNamespace(),
    )
    shell_api._window = SimpleNamespace(url="http://127.0.0.1:18100")
    opened: list[tuple[str, int]] = []
    monkeypatch.setattr(
        api_module.webbrowser,
        "open",
        lambda url, new: opened.append((url, new)) or True,
    )

    assert shell_api.open_external_url("https://github.com/login/device") is True
    assert shell_api.open_external_url("http://github.com/login/device") is False
    assert shell_api.open_external_url("https://example.com") is False
    assert shell_api.open_external_url("https://user:secret@github.com") is False
    assert opened == [("https://github.com/login/device", 2)]


def test_shell_url_fallback_does_not_fail_open_when_url_getter_breaks() -> None:
    shell_api = ShellApi(
        SimpleNamespace(allow_remote_shell_api=False),
        SimpleNamespace(),
    )
    shell_api._window = SimpleNamespace(
        get_current_url=lambda: (_ for _ in ()).throw(RuntimeError("unavailable")),
        url="https://example.com",
    )

    with pytest.raises(PermissionError, match="not available"):
        shell_api.minimize_window()


def test_native_window_style_is_reapplied_without_duplicate_event_hooks(monkeypatch) -> None:
    deactivate = _Event()
    window = SimpleNamespace(native=SimpleNamespace(Deactivate=deactivate))
    shell_api = ShellApi(SimpleNamespace(), SimpleNamespace())
    shell_api._window = window
    style_applications: list[int] = []

    monkeypatch.setattr(api_module.sys, "platform", "win32")
    monkeypatch.setattr(api_module, "_get_native_window_handle", lambda _window: 123)
    monkeypatch.setattr(
        api_module,
        "_ensure_windows_application_window_style",
        lambda hwnd: style_applications.append(hwnd) is None,
    )

    shell_api._install_windows_native_window_enhancements()
    shell_api._install_windows_native_window_enhancements()

    assert style_applications == [123, 123]
    assert len(deactivate.handlers) == 1


@pytest.mark.parametrize("foreground_class,should_minimize", [
    ("Shell_TrayWnd", False),
    ("Shell_SecondaryTrayWnd", False),
    ("OtherApplication", False),
    ("Progman", True),
    ("WorkerW", True),
    ("TrayShowDesktopButtonWClass", True),
])
def test_deactivation_does_not_mistake_taskbar_focus_for_show_desktop(
    monkeypatch, foreground_class, should_minimize,
) -> None:
    import ctypes

    minimized: list[tuple[int, int]] = []
    fake_user32 = SimpleNamespace(
        GetForegroundWindow=lambda: 456,
        IsIconic=lambda _hwnd: 0,
        ShowWindow=lambda hwnd, command: minimized.append((hwnd.value, command)) or 0,
    )
    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(user32=fake_user32), raising=False)
    monkeypatch.setattr(api_module, "_get_windows_window_class_name", lambda _hwnd: foreground_class)
    monkeypatch.setattr(api_module, "_get_native_window_handle", lambda _window: 123)
    shell_api = ShellApi(SimpleNamespace(), SimpleNamespace())
    shell_api._window = SimpleNamespace()

    shell_api._minimize_if_windows_show_desktop_is_foreground()

    assert minimized == ([(123, 6)] if should_minimize else [])


@pytest.mark.parametrize("foreground,already_minimized", [(0, False), (123, False), (456, True)])
def test_show_desktop_guard_ignores_no_foreground_self_and_minimized_window(
    monkeypatch, foreground, already_minimized,
) -> None:
    import ctypes

    fake_user32 = SimpleNamespace(
        GetForegroundWindow=lambda: foreground,
        IsIconic=lambda _hwnd: int(already_minimized),
    )
    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(user32=fake_user32), raising=False)
    monkeypatch.setattr(
        api_module, "_get_windows_window_class_name",
        lambda _hwnd: pytest.fail("Window class should not be inspected"),
    )

    assert api_module._is_windows_desktop_shell_foreground(123) is False


def test_application_window_style_preserves_taskbar_without_native_resize_frame(monkeypatch) -> None:
    original_style = 0x16010000
    required_style = 0x00080000 | 0x00020000 | 0x00010000
    style_reads = iter([original_style, original_style | required_style])
    writes: list[tuple[int, int, int]] = []
    refreshes: list[int] = []

    monkeypatch.setattr(
        api_module,
        "_get_windows_window_long_ptr",
        lambda _hwnd, _index: next(style_reads),
    )
    monkeypatch.setattr(
        api_module,
        "_set_windows_window_long_ptr",
        lambda hwnd, index, value: writes.append((hwnd, index, value)) is None,
    )
    monkeypatch.setattr(
        api_module,
        "_refresh_windows_window_frame",
        lambda hwnd: refreshes.append(hwnd),
    )
    assert api_module._ensure_windows_application_window_style(123) is True
    assert writes == [(123, -16, original_style | required_style)]
    assert refreshes == [123]
    assert (writes[0][2] & 0x00040000) == 0


def test_application_window_style_failure_is_not_reported_as_success(monkeypatch) -> None:
    original_style = 0x16010000
    style_reads = iter([original_style, original_style])

    monkeypatch.setattr(
        api_module,
        "_get_windows_window_long_ptr",
        lambda _hwnd, _index: next(style_reads),
    )
    monkeypatch.setattr(
        api_module,
        "_set_windows_window_long_ptr",
        lambda _hwnd, _index, _value: True,
    )
    monkeypatch.setattr(api_module, "_refresh_windows_window_frame", lambda _hwnd: None)

    assert api_module._ensure_windows_application_window_style(123) is False


def test_windows_uses_borderless_manual_resize(monkeypatch) -> None:
    monkeypatch.setattr(api_module.sys, "platform", "win32")

    assert api_module._get_native_window_resize_mode(SimpleNamespace()) == "none"


@pytest.mark.parametrize("native_started", [True, False])
def test_caption_drag_restores_normal_bounds_and_state_before_native_move(monkeypatch, native_started) -> None:
    shell_api = ShellApi(SimpleNamespace(
        allow_remote_shell_api=False, frameless=True, min_width=800, min_height=600,
    ), SimpleNamespace())
    window = SimpleNamespace(url="http://127.0.0.1:18100", x=100, y=50, width=1100, height=800)
    shell_api._window = window
    monkeypatch.setattr(api_module, "_read_windows_native_window_bounds", lambda _window: None)
    monkeypatch.setattr(api_module, "_get_windows_work_area_bounds",
                        lambda _window: api_module.WindowBounds(0, 0, 1920, 1040))
    monkeypatch.setattr(api_module, "_supports_native_window_drag", lambda _window: True)
    monkeypatch.setattr(api_module, "mark", lambda *_args, **_kwargs: None)

    def apply_bounds(_window, bounds):
        for name in ("x", "y", "width", "height"):
            setattr(window, name, getattr(bounds, name))
        return True

    monkeypatch.setattr(shell_api, "_apply_window_bounds", apply_bounds)

    def start_native_drag(_window, **_kwargs):
        assert shell_api.get_window_state()["maximized"] is False
        assert (window.width, window.height) == (1100, 800)
        assert (window.x, window.y) == (250, 100)
        return native_started

    monkeypatch.setattr(api_module, "_start_native_window_drag", start_native_drag)
    assert shell_api.toggle_maximize_window()["maximized"] is True
    assert (window.width, window.height) == (1920, 1040)
    assert shell_api.start_window_drag(800, 120, 0.5, 20) is native_started
    assert shell_api.get_window_state()["maximized"] is False
    assert shell_api._restore_bounds == api_module.WindowBounds(250, 100, 1100, 800)


def test_native_close_is_cancelled_until_frontend_confirms_exit(monkeypatch) -> None:
    shell_api = ShellApi(SimpleNamespace(), SimpleNamespace())
    close_requests: list[bool] = []
    monkeypatch.setattr(api_module.sys, "platform", "win32")
    monkeypatch.setattr(
        shell_api,
        "_schedule_frontend_close_request",
        lambda: close_requests.append(True),
    )

    assert shell_api._handle_window_closing() is False
    assert close_requests == [True]


def test_explicit_close_bypasses_native_close_interception() -> None:
    destroyed: list[bool] = []
    prepared: list[bool] = []
    shell_api = ShellApi(
        SimpleNamespace(allow_remote_shell_api=False),
        SimpleNamespace(prepare_exit=lambda: prepared.append(True)),
    )
    shell_api._window = SimpleNamespace(
        destroy=lambda: destroyed.append(True),
        url="http://127.0.0.1:18100",
    )

    _confirmed_close(shell_api)

    assert destroyed == [True]
    assert prepared == [True]
    assert shell_api._handle_window_closing() is None


def test_window_is_hidden_only_when_tray_icon_is_installed() -> None:
    hidden: list[bool] = []
    shell_api = ShellApi(
        SimpleNamespace(allow_remote_shell_api=False),
        SimpleNamespace(),
    )
    shell_api._window = SimpleNamespace(
        hide=lambda: hidden.append(True),
        url="http://127.0.0.1:18100",
    )
    shell_api._windows_tray = SimpleNamespace(installed=True)

    assert shell_api.hide_window_to_tray() is True
    assert hidden == [True]
