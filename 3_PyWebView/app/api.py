from __future__ import annotations

import threading
import sys
import socket
import webbrowser
import json
import os
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, build_opener
from urllib.parse import urlparse

from app.config import ShellSettings
from app.external_file_import import ExternalFileImportResult, copy_external_entries_to_directory
from app.runtime import is_shell_api_allowed_url
from app.startup_timing import mark, record_browser_mark
from app.system_metrics import SystemMetricsSampler
from app.windows_clipboard import (
    ClipboardPathEntry,
    read_clipboard_path_entries,
    write_clipboard_path_entries,
)
from app.windows_tray import WindowsTrayIcon

if TYPE_CHECKING:
    from app.backend_process import BackendProcessManager


URL_AVAILABILITY_DEFAULT_TIMEOUT_MS = 1000


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _local_tiance_root() -> Path:
    local_app_data = os.getenv("LOCALAPPDATA")
    if not local_app_data:
        raise RuntimeError("LOCALAPPDATA is unavailable")
    return Path(local_app_data).resolve() / "Tiance"


def _validate_software_update_stage(raw_path: str) -> Path:
    project_root = _project_root()
    if (project_root / ".git").exists():
        raise PermissionError("Source checkouts cannot be updated in place")
    stage_root = Path(raw_path).resolve(strict=True)
    expected_root = (_local_tiance_root() / "updates").resolve()
    if expected_root not in stage_root.parents:
        raise PermissionError("Update stage is outside the managed cache")
    ready_file = stage_root / ".tiance-update-ready"
    version_file = stage_root / "system" / "version.json"
    if not ready_file.is_file() or not version_file.is_file():
        raise ValueError("Update stage is incomplete")
    payload = json.loads(version_file.read_text(encoding="utf-8"))
    version = payload.get("version") if isinstance(payload, dict) else None
    if not isinstance(version, str) or ready_file.read_text(encoding="utf-8").strip() != version:
        raise ValueError("Update stage version does not match")
    return stage_root


@dataclass
class WindowState:
    frameless: bool
    maximized: bool
    min_width: int
    min_height: int


@dataclass
class WindowBounds:
    x: int
    y: int
    width: int
    height: int


@dataclass(frozen=True)
class ShellCapabilities:
    platform: str
    native_window_drag_supported: bool
    native_window_resize_mode: str
    native_window_resize_supported: bool
    page_zoom_supported: bool
    system_tray_supported: bool


class ShellApi:
    def __init__(self, settings: ShellSettings, backend_manager: "BackendProcessManager") -> None:
        self._settings = settings
        self._backend_manager = backend_manager
        self._window: Any | None = None
        self._maximized = False
        self._custom_maximized = False
        self._restore_bounds: WindowBounds | None = None
        self._revealed = False
        self._show_desktop_minimize_timer: threading.Timer | None = None
        self._windows_native_events_installed = False
        self._allow_window_close = False
        self._windows_tray = WindowsTrayIcon(
            icon_path=getattr(settings, "app_icon_path", None),
            on_request_exit=self._request_exit_from_windows_tray,
            on_show_window=self._show_window_from_windows_tray,
        )
        self._system_metrics = SystemMetricsSampler()

    def bind_window(self, window: Any) -> None:
        self._window = window
        window.events.maximized += self._handle_maximized
        window.events.restored += self._handle_restored
        window.events.shown += self._install_windows_native_window_enhancements
        window.events.loaded += self._install_windows_native_window_enhancements
        window.events.closing += self._handle_window_closing
        self._install_windows_native_window_enhancements()

    def record_startup_mark(
        self,
        label: str,
        browser_elapsed_ms: float | None = None,
    ) -> bool:
        self._require_allowed_window()
        record_browser_mark(label, browser_elapsed_ms)
        return True

    def check_url_available(self, url: str, timeout_ms: int) -> bool:
        self._require_window()
        if not isinstance(url, str) or not is_shell_api_allowed_url(url, self._settings):
            return False
        return _is_url_available(url, timeout_ms)

    def ensure_backend_running(self) -> dict[str, Any]:
        self._require_allowed_window()
        try:
            self._backend_manager.ensure_running()
        except Exception as exc:
            mark("backend process: ensure failed", error=str(exc))
            return {
                "ok": False,
                "startedByShell": self._backend_manager.started_by_shell,
                "errorCode": "backend_start_failed",
                "error": "后端服务启动失败。请重试；仍失败时查看 Data/logs/desktop-backend.log。",
            }

        return {
            "ok": True,
            "startedByShell": self._backend_manager.started_by_shell,
        }

    def reveal_window(self) -> bool:
        window = self._require_allowed_window()
        if self._revealed:
            return True

        if self._settings.start_maximized and not self._maximized:
            self._restore_bounds = self._capture_window_bounds(window)
            self._custom_maximized = self._maximize_to_work_area(window)
            if not self._custom_maximized and not _must_use_work_area_maximize(self._settings):
                window.maximize()
            self._maximized = True

        window.show()
        _bring_window_to_front(window)
        self._revealed = True
        mark("window reveal: requested by frontend")
        return True

    def select_project_folder(self) -> str | None:
        """打开系统文件夹选择对话框，返回用户选择的文件夹路径"""
        from webview import FileDialog

        result = self._require_allowed_window().create_file_dialog(FileDialog.FOLDER)
        if not result:
            return None
        if isinstance(result, str):
            return result
        return str(result[0]) if result else None

    def select_external_files(self) -> list[ClipboardPathEntry]:
        """打开系统文件选择对话框，返回用户明确选择的本机文件。"""
        from webview import FileDialog

        result = self._require_allowed_window().create_file_dialog(
            FileDialog.OPEN,
            allow_multiple=True,
        )
        if not result:
            return []

        selected_values = [result] if isinstance(result, str) else result
        entries: list[ClipboardPathEntry] = []
        seen: set[str] = set()
        for value in selected_values:
            try:
                path = Path(str(value)).expanduser().resolve(strict=True)
            except (OSError, RuntimeError, ValueError):
                continue
            if not path.is_file():
                continue
            resolved = str(path)
            key = os.path.normcase(resolved)
            if key in seen:
                continue
            seen.add(key)
            entries.append({
                "kind": "file",
                "name": path.name or resolved,
                "path": resolved,
            })
        return entries

    def get_clipboard_path_entries(self) -> list[ClipboardPathEntry]:
        self._require_allowed_window()
        return read_clipboard_path_entries()

    def set_clipboard_path_entries(self, paths: list[str]) -> bool:
        self._require_allowed_window()
        return write_clipboard_path_entries(paths)

    def copy_external_entries_to_directory(
        self,
        source_paths: list[str],
        destination_root: str,
    ) -> ExternalFileImportResult:
        self._require_allowed_window()
        return copy_external_entries_to_directory(source_paths, destination_root)

    def open_external_url(self, url: str) -> bool:
        self._require_allowed_window()
        if not _is_allowed_external_url(url):
            return False
        return bool(webbrowser.open(url, new=2))

    def minimize_window(self) -> None:
        self._require_allowed_window().minimize()

    def hide_window_to_tray(self) -> bool:
        window = self._require_allowed_window()
        if not self._windows_tray.installed:
            self._install_windows_native_window_enhancements()
        if not self._windows_tray.installed:
            mark("windows tray: hide rejected because tray icon is unavailable")
            return False

        window.hide()
        mark("windows tray: window hidden")
        return True

    def toggle_maximize_window(self) -> dict[str, bool]:
        window = self._require_allowed_window()

        if self._maximized:
            bounds = self._restore_bounds
            self._leave_maximized_state(window)
            if bounds is not None:
                self._apply_window_bounds(window, bounds)
                self._restore_bounds = bounds
        else:
            self._restore_bounds = self._capture_window_bounds(window)
            self._custom_maximized = self._maximize_to_work_area(window)
            if not self._custom_maximized and not _must_use_work_area_maximize(self._settings):
                window.maximize()
            self._maximized = True

        return self._build_window_state_response()

    def close_window(self) -> None:
        self._require_allowed_window()
        self._destroy_window()

    def install_software_update(self, stage_path: str) -> dict[str, str | bool]:
        window = self._require_allowed_window()
        try:
            stage_root = _validate_software_update_stage(stage_path)
            updater_source = _project_root() / "system" / "TianceUpdater.exe"
            if not updater_source.is_file():
                raise FileNotFoundError("TianceUpdater.exe is missing")
            runner_root = _local_tiance_root() / "updater-run"
            runner_root.mkdir(parents=True, exist_ok=True)
            updater_runner = runner_root / f"TianceUpdater-{uuid.uuid4().hex}.exe"
            shutil.copy2(updater_source, updater_runner)
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
            subprocess.Popen(
                [
                    str(updater_runner),
                    "--install-root",
                    str(_project_root()),
                    "--stage-root",
                    str(stage_root),
                    "--parent-pid",
                    str(os.getpid()),
                ],
                cwd=str(runner_root),
                creationflags=creationflags,
                close_fds=True,
            )
        except Exception as exc:
            mark("software update: updater launch failed", error=type(exc).__name__)
            return {
                "ok": False,
                "errorCode": "updater_launch_failed",
                "error": "无法启动更新程序，请重新下载后再试。",
            }

        mark("software update: updater launched", stage=stage_root)
        threading.Timer(0.2, self._destroy_window).start()
        return {"ok": True, "errorCode": "", "error": ""}

    def close_after_backend_loss(self, reason: str) -> None:
        mark("backend unavailable: closing shell", reason=reason)
        try:
            self._destroy_window()
        except Exception as exc:  # pragma: no cover - native runtime defensive path
            mark("backend unavailable: shell close failed", error=type(exc).__name__)

    def dispose(self) -> None:
        window = self._window
        if window is None:
            self._windows_tray.dispose()
            return

        try:
            _run_on_native_window_thread(window, self._windows_tray.dispose)
        except Exception:
            self._windows_tray.dispose()

    def get_window_state(self) -> dict[str, bool | int]:
        self._require_allowed_window()
        return self._build_window_state_response()

    def get_shell_capabilities(self) -> dict[str, bool | str]:
        window = self._require_allowed_window()
        native_window_resize_mode = _get_native_window_resize_mode(window)
        capabilities = ShellCapabilities(
            platform=sys.platform,
            native_window_drag_supported=_supports_native_window_drag(window),
            native_window_resize_mode=native_window_resize_mode,
            native_window_resize_supported=native_window_resize_mode != "none",
            page_zoom_supported=_is_webview_page_zoom_supported(window),
            system_tray_supported=sys.platform == "win32",
        )
        return {
            "platform": capabilities.platform,
            "nativeWindowDragSupported": capabilities.native_window_drag_supported,
            "nativeWindowResizeMode": capabilities.native_window_resize_mode,
            "nativeWindowResizeSupported": capabilities.native_window_resize_supported,
            "pageZoomSupported": capabilities.page_zoom_supported,
            "systemTraySupported": capabilities.system_tray_supported,
        }

    def get_page_zoom_factor(self) -> dict[str, bool | float]:
        window = self._require_allowed_window()
        zoom_factor = _get_webview_page_zoom_factor(window)
        return {
            "available": zoom_factor is not None,
            "zoomFactor": zoom_factor if zoom_factor is not None else 1.0,
        }

    def set_page_zoom_factor(self, zoom_factor: float) -> dict[str, bool | float]:
        window = self._require_allowed_window()
        next_zoom_factor = _clamp_float(zoom_factor, 0.6, 1.25)
        did_apply = _set_webview_page_zoom_factor(window, next_zoom_factor)
        applied_zoom_factor = _get_webview_page_zoom_factor(window) if did_apply else None
        return {
            "available": did_apply,
            "zoomFactor": applied_zoom_factor if applied_zoom_factor is not None else next_zoom_factor,
        }

    def get_window_bounds(self) -> dict[str, int]:
        window = self._require_allowed_window()
        bounds = self._capture_window_bounds(window)
        return {
            "x": bounds.x,
            "y": bounds.y,
            "width": bounds.width,
            "height": bounds.height,
        }

    def get_system_metrics(self) -> dict[str, Any]:
        self._require_allowed_window()
        return self._system_metrics.snapshot()

    def set_window_bounds(self, x: int, y: int, width: int, height: int) -> bool:
        window = self._require_allowed_window()

        next_width = max(int(width), self._settings.min_width)
        next_height = max(int(height), self._settings.min_height)
        next_x = int(x)
        next_y = int(y)

        if self._maximized:
            self._leave_maximized_state(window)

        if not self._apply_window_bounds(
            window,
            WindowBounds(
                x=next_x,
                y=next_y,
                width=next_width,
                height=next_height,
            ),
        ):
            return False

        self._restore_bounds = WindowBounds(
            x=next_x,
            y=next_y,
            width=next_width,
            height=next_height,
        )
        return True

    def move_window(self, x: int, y: int) -> bool:
        window = self._require_allowed_window()

        if self._maximized:
            return False

        next_x = int(x)
        next_y = int(y)

        current_bounds = self._capture_window_bounds(window)
        if not self._apply_window_bounds(
            window,
            WindowBounds(
                x=next_x,
                y=next_y,
                width=current_bounds.width,
                height=current_bounds.height,
            ),
        ):
            return False

        self._restore_bounds = WindowBounds(
            x=next_x,
            y=next_y,
            width=current_bounds.width,
            height=current_bounds.height,
        )
        return True

    def start_window_drag(
        self,
        cursor_screen_x: int,
        cursor_screen_y: int,
        anchor_ratio: float,
        drag_offset_y: int,
    ) -> bool:
        window = self._require_allowed_window()

        if not self._settings.frameless:
            return False

        if not _supports_native_window_drag(window):
            mark("window native drag requested", started=False)
            return False

        if self._maximized:
            self._restore_window_for_drag(
                window,
                cursor_screen_x=cursor_screen_x,
                cursor_screen_y=cursor_screen_y,
                anchor_ratio=anchor_ratio,
                drag_offset_y=drag_offset_y,
            )

        did_start = _start_native_window_drag(
            window,
            cursor_screen_x=cursor_screen_x,
            cursor_screen_y=cursor_screen_y,
        )
        mark("window native drag requested", started=did_start)
        return did_start

    def start_window_resize(
        self,
        edge: str,
        cursor_screen_x: int = 0,
        cursor_screen_y: int = 0,
    ) -> bool:
        window = self._require_allowed_window()

        if not self._settings.frameless or self._maximized:
            return False

        if _get_native_window_resize_mode(window) != "api":
            mark("window native resize requested", started=False, edge=edge)
            return False

        did_start = _start_native_resize(
            window,
            edge,
            cursor_screen_x=cursor_screen_x,
            cursor_screen_y=cursor_screen_y,
        )
        if did_start:
            self._restore_bounds = self._capture_window_bounds(window)
        mark("window native resize requested", started=did_start, edge=edge)
        return did_start

    def restore_window_for_drag(
        self,
        cursor_screen_x: int,
        cursor_screen_y: int,
        anchor_ratio: float,
        drag_offset_y: int,
    ) -> dict[str, int]:
        window = self._require_allowed_window()

        if not self._maximized:
            return self._window_bounds_response(window)

        self._restore_window_for_drag(
            window,
            cursor_screen_x=cursor_screen_x,
            cursor_screen_y=cursor_screen_y,
            anchor_ratio=anchor_ratio,
            drag_offset_y=drag_offset_y,
        )
        return self._window_bounds_response(window)

    def _restore_window_for_drag(
        self,
        window: Any,
        *,
        cursor_screen_x: int,
        cursor_screen_y: int,
        anchor_ratio: float,
        drag_offset_y: int,
    ) -> None:
        bounds = self._restore_bounds or self._capture_window_bounds(window)
        normalized_anchor = max(0.12, min(float(anchor_ratio), 0.88))
        next_width = max(bounds.width, self._settings.min_width)
        next_height = max(bounds.height, self._settings.min_height)
        next_x = int(cursor_screen_x - next_width * normalized_anchor)
        next_y = int(cursor_screen_y - max(0, min(int(drag_offset_y), 32)))

        self._leave_maximized_state(window)
        self._apply_window_bounds(
            window,
            WindowBounds(
                x=next_x,
                y=next_y,
                width=next_width,
                height=next_height,
            ),
        )

        self._restore_bounds = WindowBounds(
            x=next_x,
            y=next_y,
            width=next_width,
            height=next_height,
        )

    def _build_window_state_response(self) -> dict[str, bool | int]:
        state = WindowState(
            frameless=self._settings.frameless,
            maximized=self._maximized,
            min_width=self._settings.min_width,
            min_height=self._settings.min_height,
        )
        return {
            "frameless": state.frameless,
            "maximized": state.maximized,
            "minWidth": state.min_width,
            "minHeight": state.min_height,
        }

    def _window_bounds_response(self, window: Any) -> dict[str, int]:
        bounds = self._capture_window_bounds(window)
        return {
            "x": bounds.x,
            "y": bounds.y,
            "width": bounds.width,
            "height": bounds.height,
        }

    def _handle_maximized(self, *_: object) -> None:
        self._maximized = True
        self._custom_maximized = False

    def _handle_restored(self, *_: object) -> None:
        self._maximized = False
        self._custom_maximized = False
        self._install_windows_native_window_enhancements()

    def _install_windows_native_window_enhancements(self, *_: object) -> None:
        if sys.platform != "win32":
            return

        window = self._window
        if window is None:
            return

        native = getattr(window, "native", None)
        if native is None:
            return

        hwnd = _get_native_window_handle(window)
        if hwnd is None:
            return

        application_window_style_ready = _ensure_windows_application_window_style(hwnd)
        if not application_window_style_ready:
            mark("windows native window style unavailable")

        if not self._windows_native_events_installed:
            try:
                native.Deactivate += self._handle_windows_window_deactivated
                self._windows_native_events_installed = True
            except Exception:
                mark("show desktop guard: native deactivate hook unavailable")

        tray_icon_ready = bool(
            _run_on_native_window_thread(window, self._windows_tray.install)
        )
        if not tray_icon_ready:
            mark("windows tray: icon unavailable")

        mark(
            "windows native window enhancements applied",
            application_window_style=application_window_style_ready,
            deactivate_hook=self._windows_native_events_installed,
            tray_icon=tray_icon_ready,
        )

    def _handle_window_closing(self, *_: object) -> bool | None:
        if sys.platform != "win32":
            return None
        if self._allow_window_close:
            return None

        self._schedule_frontend_close_request()
        return False

    def _schedule_frontend_close_request(self) -> None:
        request_thread = threading.Thread(
            target=self._dispatch_frontend_close_request,
            name="tiance-window-close-request",
            daemon=True,
        )
        request_thread.start()

    def _dispatch_frontend_close_request(self) -> None:
        window = self._window
        if window is None:
            return

        try:
            window.evaluate_js(
                "window.dispatchEvent(new CustomEvent('tiance:window-close-requested'))"
            )
        except Exception as exc:
            mark("window close request: frontend dispatch failed", error=type(exc).__name__)

    def _show_window_from_windows_tray(self) -> None:
        window = self._window
        if window is None:
            return

        try:
            window.show()
            _bring_window_to_front(window)
            self._revealed = True
            mark("windows tray: window restored")
        except Exception as exc:
            mark("windows tray: window restore failed", error=type(exc).__name__)

    def _request_exit_from_windows_tray(self) -> None:
        self._show_window_from_windows_tray()
        self._schedule_frontend_close_request()

    def _destroy_window(self) -> None:
        window = self._require_window()
        self._allow_window_close = True
        try:
            self.dispose()
            window.destroy()
        except Exception:
            self._allow_window_close = False
            raise

    def _handle_windows_window_deactivated(self, *_: object) -> None:
        if sys.platform != "win32":
            return

        if self._show_desktop_minimize_timer is not None:
            self._show_desktop_minimize_timer.cancel()

        self._show_desktop_minimize_timer = threading.Timer(
            0.12,
            self._minimize_if_windows_show_desktop_is_foreground,
        )
        self._show_desktop_minimize_timer.daemon = True
        self._show_desktop_minimize_timer.start()

    def _minimize_if_windows_show_desktop_is_foreground(self) -> None:
        window = self._window
        if window is None:
            return

        hwnd = _get_native_window_handle(window)
        if hwnd is None:
            return

        if not _is_windows_desktop_shell_foreground(hwnd):
            return

        if _minimize_windows_window(hwnd):
            mark("show desktop guard: minimized window")

    def _capture_window_bounds(self, window: Any) -> WindowBounds:
        native_bounds = _read_windows_native_window_bounds(window)
        if native_bounds is not None:
            return native_bounds

        return WindowBounds(
            x=window.x,
            y=window.y,
            width=window.width,
            height=window.height,
        )

    def _maximize_to_work_area(self, window: Any) -> bool:
        if not self._settings.frameless:
            return False

        work_area = _get_windows_work_area_bounds(window)
        if work_area is None:
            mark("window work area maximize unavailable")
            return False

        if not self._apply_window_bounds(window, work_area):
            mark("window work area maximize failed")
            return False

        mark(
            "window work area maximized",
            x=work_area.x,
            y=work_area.y,
            width=work_area.width,
            height=work_area.height,
        )
        return True

    def _leave_maximized_state(self, window: Any) -> None:
        if not self._custom_maximized:
            window.restore()

        self._maximized = False
        self._custom_maximized = False

    def _apply_window_bounds(self, window: Any, bounds: WindowBounds) -> bool:
        if sys.platform == "win32" and _apply_windows_window_bounds(window, bounds):
            return True

        try:
            window.move(bounds.x, bounds.y)
            window.resize(bounds.width, bounds.height)
        except Exception:
            return False

        return True

    def _require_window(self) -> Any:
        if self._window is None:  # pragma: no cover - defensive runtime guard
            raise RuntimeError("Window has not been bound to the shell API.")

        return self._window

    def _require_allowed_window(self) -> Any:
        window = self._require_window()
        current_url = _get_current_window_url(window)
        # The inline startup document has no URL but is the trusted document
        # that receives the bridge at window creation time. Any navigated page
        # has a concrete URL and must pass the allow-list check.
        if current_url and not is_shell_api_allowed_url(current_url, self._settings):
            raise PermissionError("Shell API is not available for the current page.")
        return window


def _get_current_window_url(window: Any) -> str:
    getter = getattr(window, "get_current_url", None)
    if callable(getter):
        try:
            current_url = str(getter() or "")
        except Exception:
            current_url = ""
        if current_url:
            return current_url

    for attribute_name in ("real_url", "url"):
        value = getattr(window, attribute_name, None)
        if isinstance(value, str) and value:
            return value

    return ""


def _must_use_work_area_maximize(settings: ShellSettings) -> bool:
    return sys.platform == "win32" and settings.frameless


def _is_url_available(url: str, timeout_ms: int) -> bool:
    timeout_seconds = _timeout_ms_to_seconds(timeout_ms)
    if not _is_local_url_port_open(url, timeout_seconds):
        return False

    try:
        opener = build_opener(ProxyHandler({}))
        with opener.open(url, timeout=timeout_seconds) as response:
            status = getattr(response, "status", None)
            return status is None or 200 <= status < 400
    except HTTPError as exc:
        return 200 <= exc.code < 400
    except (URLError, TimeoutError, OSError, ValueError):
        return False


def _timeout_ms_to_seconds(timeout_ms: int) -> float:
    try:
        parsed_timeout_ms = int(timeout_ms)
    except (TypeError, ValueError):
        parsed_timeout_ms = URL_AVAILABILITY_DEFAULT_TIMEOUT_MS

    if parsed_timeout_ms <= 0:
        parsed_timeout_ms = URL_AVAILABILITY_DEFAULT_TIMEOUT_MS

    return parsed_timeout_ms / 1000


def _is_local_url_port_open(url: str, timeout_seconds: float) -> bool:
    parsed = urlparse(url)
    if parsed.scheme.lower() not in {"http", "https"}:
        return True

    hostname = parsed.hostname
    if (hostname or "").lower() not in {"127.0.0.1", "localhost", "::1"}:
        return True

    port = parsed.port
    if port is None:
        port = 443 if parsed.scheme.lower() == "https" else 80

    try:
        with socket.create_connection((hostname, port), timeout=timeout_seconds):
            return True
    except OSError:
        return False


def _get_windows_work_area_bounds(window: Any) -> WindowBounds | None:
    display_bounds = _get_windows_display_bounds(window)
    return display_bounds["work_area"] if display_bounds is not None else None


def _get_windows_display_bounds(window: Any) -> dict[str, WindowBounds] | None:
    if sys.platform != "win32":
        return None

    import ctypes

    class Rect(ctypes.Structure):
        _fields_ = [
            ("left", ctypes.c_long),
            ("top", ctypes.c_long),
            ("right", ctypes.c_long),
            ("bottom", ctypes.c_long),
        ]

    class MonitorInfo(ctypes.Structure):
        _fields_ = [
            ("cbSize", ctypes.c_ulong),
            ("rcMonitor", Rect),
            ("rcWork", Rect),
            ("dwFlags", ctypes.c_ulong),
        ]

    scale = _get_window_scale(window)
    user32 = ctypes.windll.user32
    hwnd = _get_native_window_handle(window)

    if hwnd is not None:
        user32.MonitorFromWindow.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        user32.MonitorFromWindow.restype = ctypes.c_void_p
        user32.GetMonitorInfoW.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(MonitorInfo),
        ]
        user32.GetMonitorInfoW.restype = ctypes.c_int

        monitor = user32.MonitorFromWindow(ctypes.c_void_p(hwnd), 0x00000002)
        if monitor:
            info = MonitorInfo()
            info.cbSize = ctypes.sizeof(MonitorInfo)
            if user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
                return {
                    "monitor": _rect_to_window_bounds(info.rcMonitor, scale),
                    "work_area": _rect_to_window_bounds(info.rcWork, scale),
                }

    user32.SystemParametersInfoW.argtypes = [
        ctypes.c_uint,
        ctypes.c_uint,
        ctypes.POINTER(Rect),
        ctypes.c_uint,
    ]
    user32.SystemParametersInfoW.restype = ctypes.c_int

    rect = Rect()
    if user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):
        bounds = _rect_to_window_bounds(rect, scale)
        return {
            "monitor": bounds,
            "work_area": bounds,
        }

    return None


def _window_bounds_to_dict(bounds: WindowBounds) -> dict[str, int]:
    return {
        "x": bounds.x,
        "y": bounds.y,
        "width": bounds.width,
        "height": bounds.height,
    }


def _bring_window_to_front(window: Any) -> bool:
    if sys.platform != "win32":
        return False

    import ctypes
    from ctypes import wintypes

    hwnd = _get_native_window_handle(window)
    if hwnd is None:
        return False

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    SW_SHOW = 5
    SW_RESTORE = 9
    HWND_TOP = 0
    SWP_NOMOVE = 0x0002
    SWP_NOSIZE = 0x0001
    SWP_SHOWWINDOW = 0x0040

    target_pid = wintypes.DWORD()
    target_thread = user32.GetWindowThreadProcessId(hwnd, ctypes.byref(target_pid))
    current_thread = kernel32.GetCurrentThreadId()
    foreground_hwnd = user32.GetForegroundWindow()
    foreground_thread = (
        user32.GetWindowThreadProcessId(foreground_hwnd, None) if foreground_hwnd else 0
    )

    attached_target = False
    attached_foreground = False
    try:
        if target_thread and target_thread != current_thread:
            attached_target = bool(user32.AttachThreadInput(current_thread, target_thread, True))
        if foreground_thread and foreground_thread != current_thread:
            attached_foreground = bool(
                user32.AttachThreadInput(current_thread, foreground_thread, True)
            )

        user32.ShowWindow(hwnd, SW_RESTORE if user32.IsIconic(hwnd) else SW_SHOW)
        user32.SetWindowPos(hwnd, HWND_TOP, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
        user32.BringWindowToTop(hwnd)
        return bool(user32.SetForegroundWindow(hwnd))
    except Exception:
        return False
    finally:
        if attached_foreground:
            user32.AttachThreadInput(current_thread, foreground_thread, False)
        if attached_target:
            user32.AttachThreadInput(current_thread, target_thread, False)


def _apply_windows_window_bounds(window: Any, bounds: WindowBounds) -> bool:
    import ctypes

    hwnd = _get_native_window_handle(window)
    if hwnd is None:
        return False

    scale = _get_window_scale(window)
    user32 = ctypes.windll.user32
    user32.SetWindowPos.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_uint,
    ]
    user32.SetWindowPos.restype = ctypes.c_int

    return bool(
        user32.SetWindowPos(
            ctypes.c_void_p(hwnd),
            None,
            int(round(bounds.x * scale)),
            int(round(bounds.y * scale)),
            int(round(bounds.width * scale)),
            int(round(bounds.height * scale)),
            0x0004 | 0x0010,
        )
    )


def _read_windows_native_window_bounds(window: Any) -> WindowBounds | None:
    if sys.platform != "win32":
        return None

    native = getattr(window, "native", None)
    raw_bounds = getattr(native, "Bounds", None)
    if raw_bounds is None:
        return None

    scale = _get_window_scale(window)
    try:
        return WindowBounds(
            x=int(round(int(raw_bounds.X) / scale)),
            y=int(round(int(raw_bounds.Y) / scale)),
            width=max(1, int(round(int(raw_bounds.Width) / scale))),
            height=max(1, int(round(int(raw_bounds.Height) / scale))),
        )
    except (AttributeError, TypeError, ValueError, OverflowError):
        return None


def _get_native_window_handle(window: Any) -> int | None:
    native = getattr(window, "native", None)
    handle = getattr(native, "Handle", None)

    if isinstance(handle, int):
        return handle or None

    for method_name in ("ToInt64", "ToInt32"):
        method = getattr(handle, method_name, None)
        if callable(method):
            try:
                value = int(method())
            except (OverflowError, ValueError, TypeError):
                continue
            return value or None

    return None


def _is_webview_page_zoom_supported(window: Any) -> bool:
    return _get_webview_page_zoom_factor(window) is not None


def _get_webview_page_zoom_factor(window: Any) -> float | None:
    try:
        return _run_on_native_window_thread(window, lambda: _read_webview_page_zoom_factor(window))
    except Exception:
        return None


def _set_webview_page_zoom_factor(window: Any, zoom_factor: float) -> bool:
    def apply_zoom() -> bool:
        webview = _get_native_webview_control(window)
        if webview is None:
            return False

        if hasattr(webview, "ZoomFactor"):
            webview.ZoomFactor = zoom_factor
            return True

        core_webview = getattr(webview, "CoreWebView2", None)
        if core_webview is not None and hasattr(core_webview, "ZoomFactor"):
            core_webview.ZoomFactor = zoom_factor
            return True

        return False

    try:
        return bool(_run_on_native_window_thread(window, apply_zoom))
    except Exception:
        return False


def _read_webview_page_zoom_factor(window: Any) -> float | None:
    webview = _get_native_webview_control(window)
    if webview is None:
        return None

    raw_zoom_factor = getattr(webview, "ZoomFactor", None)
    if raw_zoom_factor is None:
        core_webview = getattr(webview, "CoreWebView2", None)
        raw_zoom_factor = getattr(core_webview, "ZoomFactor", None) if core_webview is not None else None

    try:
        zoom_factor = float(raw_zoom_factor)
    except (TypeError, ValueError):
        return None

    return zoom_factor if zoom_factor > 0 else None


def _get_native_webview_control(window: Any) -> Any | None:
    native = getattr(window, "native", None)
    return getattr(native, "webview", None)


def _run_on_native_window_thread(window: Any, action: Any) -> Any:
    native = getattr(window, "native", None)
    if native is not None and getattr(native, "InvokeRequired", False):
        from System import Func, Type

        result: dict[str, Any] = {"value": None}

        def invoke_action() -> None:
            result["value"] = action()

        native.Invoke(Func[Type](invoke_action))
        return result["value"]

    return action()


def _start_native_window_drag(
    window: Any,
    *,
    cursor_screen_x: int,
    cursor_screen_y: int,
) -> bool:
    if sys.platform == "win32":
        return _start_windows_caption_drag(window)

    if _is_qt_native_window(window):
        return _start_qt_native_window_drag(window)

    if _is_gtk_native_window(window):
        return _start_gtk_native_window_drag(
            window,
            cursor_screen_x=cursor_screen_x,
            cursor_screen_y=cursor_screen_y,
        )

    if sys.platform == "darwin" and _is_cocoa_native_window(window):
        return _start_cocoa_native_window_drag(
            window,
            cursor_screen_x=cursor_screen_x,
            cursor_screen_y=cursor_screen_y,
        )

    return False


def _start_windows_caption_drag(window: Any) -> bool:
    if not _supports_native_window_drag(window):
        return False

    return _start_windows_nonclient_drag(window, 2)


def _start_native_resize(
    window: Any,
    edge: str,
    *,
    cursor_screen_x: int,
    cursor_screen_y: int,
) -> bool:
    if sys.platform == "win32":
        return _start_windows_resize(window, edge)

    if _is_qt_native_window(window):
        return _start_qt_native_resize(window, edge)

    if _is_gtk_native_window(window):
        return _start_gtk_native_resize(
            window,
            edge,
            cursor_screen_x=cursor_screen_x,
            cursor_screen_y=cursor_screen_y,
        )

    return False


def _start_windows_resize(window: Any, edge: str) -> bool:
    if _get_native_window_resize_mode(window) != "api":
        return False

    hit_test = _windows_resize_hit_test(edge)
    if hit_test is None:
        return False

    return _start_windows_nonclient_drag(window, hit_test)


def _start_windows_nonclient_drag(window: Any, hit_test: int) -> bool:
    hwnd = _get_native_window_handle(window)
    if hwnd is None:
        return False

    native = getattr(window, "native", None)

    def start_drag_or_resize() -> None:
        _send_windows_nonclient_drag(hwnd, hit_test)

    try:
        if native is not None and getattr(native, "InvokeRequired", False):
            from System import Func, Type

            native.Invoke(Func[Type](start_drag_or_resize))
        else:
            start_drag_or_resize()
    except Exception:
        return False

    return True


def _start_qt_native_window_drag(window: Any) -> bool:
    native = getattr(window, "native", None)
    if native is None:
        return False

    window_handle_getter = getattr(native, "windowHandle", None)
    if not callable(window_handle_getter):
        return False

    try:
        window_handle = window_handle_getter()
    except Exception:
        return False

    if window_handle is None or not hasattr(window_handle, "startSystemMove"):
        return False

    try:
        return bool(window_handle.startSystemMove())
    except Exception:
        return False


def _start_gtk_native_window_drag(
    window: Any,
    *,
    cursor_screen_x: int,
    cursor_screen_y: int,
) -> bool:
    native = getattr(window, "native", None)
    begin_move_drag = getattr(native, "begin_move_drag", None)
    if not callable(begin_move_drag):
        return False

    timestamp = _get_gtk_current_event_time()
    try:
        begin_move_drag(1, int(cursor_screen_x), int(cursor_screen_y), timestamp)
    except Exception:
        return False

    return True


def _start_cocoa_native_window_drag(
    window: Any,
    *,
    cursor_screen_x: int,
    cursor_screen_y: int,
) -> bool:
    native = getattr(window, "native", None)
    if native is None or not hasattr(native, "performWindowDragWithEvent_"):
        return False

    try:
        import AppKit
    except Exception:
        return False

    try:
        screen_point = AppKit.NSMakePoint(float(cursor_screen_x), float(cursor_screen_y))
        if hasattr(native, "convertPointFromScreen_"):
            window_point = native.convertPointFromScreen_(screen_point)
        elif hasattr(native, "convertScreenToBase_"):
            window_point = native.convertScreenToBase_(screen_point)
        else:
            return False

        mouse_down_event_type = getattr(
            AppKit,
            "NSEventTypeLeftMouseDown",
            getattr(AppKit, "NSLeftMouseDown", None),
        )
        if mouse_down_event_type is None:
            return False

        event = AppKit.NSEvent.mouseEventWithType_location_modifierFlags_timestamp_windowNumber_context_eventNumber_clickCount_pressure_(
            mouse_down_event_type,
            window_point,
            0,
            0,
            native.windowNumber(),
            None,
            0,
            1,
            1.0,
        )
        if event is None:
            return False

        native.performWindowDragWithEvent_(event)
    except Exception:
        return False

    return True


def _start_qt_native_resize(window: Any, edge: str) -> bool:
    native = getattr(window, "native", None)
    if native is None:
        return False

    window_handle_getter = getattr(native, "windowHandle", None)
    if not callable(window_handle_getter):
        return False

    try:
        window_handle = window_handle_getter()
    except Exception:
        return False

    if window_handle is None or not hasattr(window_handle, "startSystemResize"):
        return False

    qt_edges = _qt_resize_edges(edge)
    if qt_edges is None:
        return False

    try:
        return bool(window_handle.startSystemResize(qt_edges))
    except Exception:
        return False


def _start_gtk_native_resize(
    window: Any,
    edge: str,
    *,
    cursor_screen_x: int,
    cursor_screen_y: int,
) -> bool:
    native = getattr(window, "native", None)
    begin_resize_drag = getattr(native, "begin_resize_drag", None)
    if not callable(begin_resize_drag):
        return False

    gtk_edge = _gtk_resize_edge(edge)
    if gtk_edge is None:
        return False

    timestamp = _get_gtk_current_event_time()
    try:
        begin_resize_drag(
            gtk_edge,
            1,
            int(cursor_screen_x),
            int(cursor_screen_y),
            timestamp,
        )
    except Exception:
        return False

    return True


def _is_windows_desktop_shell_foreground(window_hwnd: int) -> bool:
    import ctypes

    user32 = ctypes.windll.user32
    user32.GetForegroundWindow.argtypes = []
    user32.GetForegroundWindow.restype = ctypes.c_void_p
    user32.IsIconic.argtypes = [ctypes.c_void_p]
    user32.IsIconic.restype = ctypes.c_int

    if user32.IsIconic(ctypes.c_void_p(window_hwnd)):
        return False

    foreground = user32.GetForegroundWindow()
    if not foreground or int(foreground) == int(window_hwnd):
        return False

    return _get_windows_window_class_name(int(foreground)) in {
        "Progman",
        "WorkerW",
        "Shell_TrayWnd",
        "TrayShowDesktopButtonWClass",
    }


def _minimize_windows_window(hwnd: int) -> bool:
    import ctypes

    user32 = ctypes.windll.user32
    user32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
    user32.ShowWindow.restype = ctypes.c_int
    user32.ShowWindow(ctypes.c_void_p(hwnd), 6)
    return True


def _ensure_windows_application_window_style(hwnd: int) -> bool:
    style = _get_windows_window_long_ptr(hwnd, -16)
    if style is None:
        return False

    required_style = 0x00080000 | 0x00020000 | 0x00010000
    next_style = int(style) | required_style
    if next_style != int(style):
        if not _set_windows_window_long_ptr(hwnd, -16, next_style):
            return False
        _refresh_windows_window_frame(hwnd)
        applied_style = _get_windows_window_long_ptr(hwnd, -16)
    else:
        applied_style = style

    return (
        applied_style is not None and
        (int(applied_style) & required_style) == required_style
    )


def _refresh_windows_window_frame(hwnd: int) -> None:
    import ctypes

    user32 = ctypes.windll.user32
    user32.SetWindowPos.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_uint,
    ]
    user32.SetWindowPos.restype = ctypes.c_int
    user32.SetWindowPos(
        ctypes.c_void_p(hwnd),
        None,
        0,
        0,
        0,
        0,
        0x0001 | 0x0002 | 0x0004 | 0x0010 | 0x0020,
    )


def _get_windows_window_long_ptr(hwnd: int, index: int) -> int | None:
    import ctypes

    user32 = ctypes.windll.user32
    ctypes.set_last_error(0)

    if hasattr(user32, "GetWindowLongPtrW"):
        get_window_long = user32.GetWindowLongPtrW
        get_window_long.argtypes = [ctypes.c_void_p, ctypes.c_int]
        get_window_long.restype = ctypes.c_ssize_t
    else:
        get_window_long = user32.GetWindowLongW
        get_window_long.argtypes = [ctypes.c_void_p, ctypes.c_int]
        get_window_long.restype = ctypes.c_long

    value = get_window_long(ctypes.c_void_p(hwnd), index)
    if value == 0 and ctypes.get_last_error() != 0:
        return None
    return int(value)


def _set_windows_window_long_ptr(hwnd: int, index: int, value: int) -> bool:
    import ctypes

    user32 = ctypes.windll.user32
    ctypes.set_last_error(0)

    if hasattr(user32, "SetWindowLongPtrW"):
        set_window_long = user32.SetWindowLongPtrW
        set_window_long.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t]
        set_window_long.restype = ctypes.c_ssize_t
    else:
        set_window_long = user32.SetWindowLongW
        set_window_long.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_long]
        set_window_long.restype = ctypes.c_long

    previous = set_window_long(ctypes.c_void_p(hwnd), index, value)
    return previous != 0 or ctypes.get_last_error() == 0


def _get_windows_window_class_name(hwnd: int) -> str:
    import ctypes

    user32 = ctypes.windll.user32
    user32.GetClassNameW.argtypes = [
        ctypes.c_void_p,
        ctypes.c_wchar_p,
        ctypes.c_int,
    ]
    user32.GetClassNameW.restype = ctypes.c_int

    buffer = ctypes.create_unicode_buffer(256)
    length = user32.GetClassNameW(ctypes.c_void_p(hwnd), buffer, len(buffer))
    if length <= 0:
        return ""

    return buffer.value


def _supports_native_window_drag(window: Any) -> bool:
    if sys.platform == "win32":
        return True

    native = getattr(window, "native", None)
    if native is None:
        return False

    if _is_qt_native_window(window):
        try:
            window_handle = native.windowHandle()
        except Exception:
            window_handle = None
        return window_handle is not None and hasattr(window_handle, "startSystemMove")

    if _is_gtk_native_window(window):
        return callable(getattr(native, "begin_move_drag", None))

    if sys.platform == "darwin":
        return hasattr(native, "performWindowDragWithEvent_")

    return False


def _get_native_window_resize_mode(window: Any) -> str:
    if sys.platform == "win32":
        return "none"

    native = getattr(window, "native", None)
    if native is None:
        return "none"

    if _is_qt_native_window(window) and _qt_native_window_can_start_resize(window):
        return "api"

    if _is_gtk_native_window(window):
        return "api"

    if sys.platform == "darwin" and _is_cocoa_native_window(window):
        return "system-edge"

    return "none"


def _is_qt_native_window(window: Any) -> bool:
    native = getattr(window, "native", None)
    return native is not None and callable(getattr(native, "windowHandle", None))


def _qt_native_window_can_start_resize(window: Any) -> bool:
    native = getattr(window, "native", None)
    if native is None:
        return False

    try:
        window_handle = native.windowHandle()
    except Exception:
        return False

    return window_handle is not None and hasattr(window_handle, "startSystemResize")


def _is_gtk_native_window(window: Any) -> bool:
    native = getattr(window, "native", None)
    return native is not None and callable(getattr(native, "begin_resize_drag", None))


def _is_cocoa_native_window(window: Any) -> bool:
    native = getattr(window, "native", None)
    return native is not None and hasattr(native, "styleMask")


def _qt_resize_edges(edge: str) -> Any | None:
    qt_core = _load_qt_core_module()
    if qt_core is None:
        return None

    edge_container = getattr(qt_core.Qt, "Edge", qt_core.Qt)
    edge_mapping = {
        "left": ("LeftEdge",),
        "right": ("RightEdge",),
        "top": ("TopEdge",),
        "bottom": ("BottomEdge",),
        "top-left": ("TopEdge", "LeftEdge"),
        "top-right": ("TopEdge", "RightEdge"),
        "bottom-right": ("BottomEdge", "RightEdge"),
        "bottom-left": ("BottomEdge", "LeftEdge"),
    }
    edge_names = edge_mapping.get(str(edge))
    if not edge_names:
        return None

    qt_edges = None
    for edge_name in edge_names:
        edge_value = getattr(edge_container, edge_name, None)
        if edge_value is None:
            edge_value = getattr(qt_core.Qt, edge_name, None)
        if edge_value is None:
            return None
        qt_edges = edge_value if qt_edges is None else qt_edges | edge_value

    return qt_edges


def _load_qt_core_module() -> Any | None:
    for module_name in (
        "qtpy.QtCore",
        "PyQt6.QtCore",
        "PySide6.QtCore",
        "PyQt5.QtCore",
        "PySide2.QtCore",
    ):
        try:
            module = __import__(module_name, fromlist=["Qt"])
        except Exception:
            continue
        if hasattr(module, "Qt"):
            return module

    return None


def _gtk_resize_edge(edge: str) -> Any | None:
    try:
        from gi.repository import Gdk
    except Exception:
        return None

    edge_mapping = {
        "left": "WEST",
        "right": "EAST",
        "top": "NORTH",
        "bottom": "SOUTH",
        "top-left": "NORTH_WEST",
        "top-right": "NORTH_EAST",
        "bottom-right": "SOUTH_EAST",
        "bottom-left": "SOUTH_WEST",
    }
    edge_name = edge_mapping.get(str(edge))
    if not edge_name:
        return None

    return getattr(Gdk.WindowEdge, edge_name, None)


def _get_gtk_current_event_time() -> int:
    try:
        from gi.repository import Gdk, Gtk

        timestamp = int(Gtk.get_current_event_time())
        if timestamp > 0:
            return timestamp

        return int(getattr(Gdk, "CURRENT_TIME", 0))
    except Exception:
        return 0


def _windows_resize_hit_test(edge: str) -> int | None:
    return {
        "left": 10,
        "right": 11,
        "top": 12,
        "top-left": 13,
        "top-right": 14,
        "bottom": 15,
        "bottom-left": 16,
        "bottom-right": 17,
    }.get(str(edge))


def _send_windows_nonclient_drag(hwnd: int, hit_test: int) -> None:
    import ctypes

    user32 = ctypes.windll.user32
    user32.ReleaseCapture.argtypes = []
    user32.ReleaseCapture.restype = ctypes.c_int
    user32.SendMessageW.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint,
        ctypes.c_size_t,
        ctypes.c_ssize_t,
    ]
    user32.SendMessageW.restype = ctypes.c_ssize_t

    user32.ReleaseCapture()
    user32.SendMessageW(ctypes.c_void_p(hwnd), 0x00A1, int(hit_test), 0)


def _get_window_scale(window: Any) -> float:
    native = getattr(window, "native", None)
    try:
        scale = float(getattr(native, "_scale", 1) or 1)
    except (TypeError, ValueError):
        return 1

    return scale if scale > 0 else 1


def _rect_to_window_bounds(rect: Any, scale: float) -> WindowBounds:
    left = int(round(rect.left / scale))
    top = int(round(rect.top / scale))
    right = int(round(rect.right / scale))
    bottom = int(round(rect.bottom / scale))

    return WindowBounds(
        x=left,
        y=top,
        width=max(1, right - left),
        height=max(1, bottom - top),
    )


def _clamp_float(value: float, minimum: float, maximum: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return minimum

    return max(minimum, min(maximum, number))


def _is_allowed_external_url(url: object) -> bool:
    if not isinstance(url, str):
        return False
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and (parsed.hostname or "").lower() == "github.com"
        and parsed.username is None
        and parsed.password is None
    )
