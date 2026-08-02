from dataclasses import dataclass
import os
from pathlib import Path

from app.port_probe import is_port_open
from app.startup_preferences import (
    NetworkStartupPreferences,
    load_desktop_window_size_preferences,
    load_network_startup_preferences,
)


SHELL_ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = SHELL_ROOT.parent
DEFAULT_WEBVIEW2_RUNTIME_DIR = SHELL_ROOT / "vendor" / "webview2-fixed"
DEFAULT_WEBVIEW2_RUNTIME_NAME = "runtime-149"
DEFAULT_WEBVIEW_STORAGE_ROOT = PROJECT_ROOT / "Data" / "cache" / "desktop-shell" / "webview2-profiles"
DEFAULT_APP_ICON_FILE = SHELL_ROOT / "assets" / "app-icon.ico"
WEBVIEW2_RUNTIME_MODES = {"auto", "bundled", "system"}
DEFAULT_API_PORT = 18000
DEFAULT_API_PORT_RANGE = (18000, 18020)


@dataclass(frozen=True)
class ShellSettings:
    title: str
    debug: bool
    api_host: str
    api_port: int
    api_url: str
    manage_backend: bool
    dev_url: str
    app_url: str
    frontend_dist_path: str
    allow_remote_shell_api: bool
    frameless: bool
    easy_drag: bool
    shadow: bool
    width: int
    height: int
    start_maximized: bool
    min_width: int
    min_height: int
    background_color: str
    webview2_runtime_mode: str
    webview2_runtime_path: str | None
    webview_storage_path: str
    app_icon_path: str | None


def load_settings() -> ShellSettings:
    api_host = os.getenv("TIANCE_API_HOST", "127.0.0.1")
    network_preferences = load_network_startup_preferences(PROJECT_ROOT)
    api_port = _resolve_api_port(api_host, network_preferences)
    api_url = f"http://{api_host}:{api_port}"
    frontend_dist_path = _resolve_frontend_dist_path()
    default_frontend_url = os.getenv("TIANCE_FRONTEND_DEV_URL", "http://127.0.0.1:18100")
    default_app_url = _build_default_app_url(api_url, frontend_dist_path)
    debug = _read_bool(
        os.getenv("TIANCE_SHELL_DEBUG"),
        default=True,
    )
    window_preferences = load_desktop_window_size_preferences(PROJECT_ROOT)
    webview2_runtime_mode = _read_webview2_runtime_mode(os.getenv("TIANCE_WEBVIEW2_RUNTIME_MODE"))
    webview2_runtime_path = _resolve_webview2_runtime_path(webview2_runtime_mode)

    return ShellSettings(
        title=os.getenv("TIANCE_SHELL_TITLE", "Tiance"),
        debug=debug,
        api_host=api_host,
        api_port=api_port,
        api_url=api_url,
        manage_backend=_read_bool(os.getenv("TIANCE_SHELL_MANAGE_BACKEND"), default=True),
        dev_url=default_frontend_url,
        app_url=os.getenv("TIANCE_APP_URL") or default_app_url,
        frontend_dist_path=str(frontend_dist_path),
        allow_remote_shell_api=_read_bool(
            os.getenv("TIANCE_ALLOW_REMOTE_SHELL_API"),
            default=False,
        ),
        frameless=_read_bool(os.getenv("TIANCE_FRAMELESS"), default=True),
        easy_drag=_read_bool(os.getenv("TIANCE_EASY_DRAG"), default=False),
        shadow=_read_bool(
            os.getenv("TIANCE_WINDOW_SHADOW"),
            default=False,
        ),
        width=_read_int(os.getenv("TIANCE_WINDOW_WIDTH"), default=window_preferences.width),
        height=_read_int(os.getenv("TIANCE_WINDOW_HEIGHT"), default=window_preferences.height),
        start_maximized=_read_bool(
            os.getenv("TIANCE_WINDOW_MAXIMIZED"),
            default=window_preferences.maximized,
        ),
        min_width=int(os.getenv("TIANCE_WINDOW_MIN_WIDTH", "1080")),
        min_height=int(os.getenv("TIANCE_WINDOW_MIN_HEIGHT", "720")),
        background_color=os.getenv("TIANCE_WINDOW_BG", "#1e1e1e"),
        webview2_runtime_mode=webview2_runtime_mode,
        webview2_runtime_path=webview2_runtime_path,
        webview_storage_path=str(_resolve_webview_storage_path(webview2_runtime_path)),
        app_icon_path=_resolve_app_icon_path(),
    )


def _read_bool(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default

    normalized = value.strip().lower()
    return normalized in {"1", "true", "yes", "on"}


def _read_int(value: str | None, *, default: int) -> int:
    if value is None:
        return default
    try:
        return int(value.strip())
    except ValueError:
        return default


def _resolve_api_port(
    host: str,
    preferences: NetworkStartupPreferences | None = None,
) -> int:
    configured_port = os.getenv("TIANCE_API_PORT")
    if configured_port:
        return _read_int(configured_port, default=DEFAULT_API_PORT)
    if preferences is not None and preferences.backend_port_mode == "fixed":
        return preferences.fixed_backend_port

    start_port, end_port = _read_port_range(
        os.getenv("TIANCE_API_PORT_RANGE"),
        default=DEFAULT_API_PORT_RANGE,
    )
    for port in range(start_port, end_port + 1):
        if not is_port_open(host, port):
            return port

    raise SystemExit(
        "No available Tiance API port. "
        f"Checked {host}:{start_port}-{end_port}. "
        "Close the conflicting process or set TIANCE_API_PORT."
    )


def _read_port_range(value: str | None, *, default: tuple[int, int]) -> tuple[int, int]:
    if not value:
        return default

    normalized = value.strip()
    if "-" not in normalized:
        port = _read_int(normalized, default=default[0])
        return port, port

    raw_start, raw_end = normalized.split("-", 1)
    start_port = _read_int(raw_start, default=default[0])
    end_port = _read_int(raw_end, default=default[1])
    if start_port <= 0 or end_port <= 0 or start_port > end_port:
        return default
    return start_port, end_port


def _read_webview2_runtime_mode(value: str | None) -> str:
    runtime_mode = (value or "auto").strip().lower()
    if runtime_mode not in WEBVIEW2_RUNTIME_MODES:
        allowed_modes = ", ".join(sorted(WEBVIEW2_RUNTIME_MODES))
        raise SystemExit(
            "Invalid TIANCE_WEBVIEW2_RUNTIME_MODE. "
            f"Expected one of: {allowed_modes}. Got: {runtime_mode or '<empty>'}"
        )
    return runtime_mode


def _resolve_webview2_runtime_path(runtime_mode: str) -> str | None:
    configured_path = os.getenv("TIANCE_WEBVIEW2_RUNTIME_PATH")

    if runtime_mode == "system":
        if configured_path:
            raise SystemExit(
                "TIANCE_WEBVIEW2_RUNTIME_MODE=system cannot be combined with "
                "TIANCE_WEBVIEW2_RUNTIME_PATH. Remove the custom runtime path or use "
                "TIANCE_WEBVIEW2_RUNTIME_MODE=bundled."
            )
        return None

    if configured_path:
        resolved = _resolve_path(configured_path)
        runtime_dir = _find_webview2_runtime_dir(resolved)
        if runtime_dir is None:
            raise SystemExit(
                "Configured WebView2 runtime path is invalid. "
                f"Expected a directory containing msedgewebview2.exe: {resolved}"
            )
        return str(runtime_dir)

    runtime_dir = DEFAULT_WEBVIEW2_RUNTIME_DIR / DEFAULT_WEBVIEW2_RUNTIME_NAME
    if _looks_like_webview2_runtime_dir(runtime_dir):
        return str(runtime_dir.resolve())

    if runtime_mode == "bundled":
        raise SystemExit(
            "Bundled WebView2 runtime is required but missing. "
            f"Expected: {(DEFAULT_WEBVIEW2_RUNTIME_DIR / DEFAULT_WEBVIEW2_RUNTIME_NAME).resolve()}"
        )

    return None


def _resolve_webview_storage_path(webview2_runtime_path: str | None) -> Path:
    configured_path = os.getenv("TIANCE_WEBVIEW_STORAGE_PATH")
    if configured_path:
        return _resolve_path(configured_path)

    return (DEFAULT_WEBVIEW_STORAGE_ROOT / _webview_storage_profile_name(webview2_runtime_path)).resolve()


def _webview_storage_profile_name(webview2_runtime_path: str | None) -> str:
    if not webview2_runtime_path:
        return "system"

    runtime_name = Path(webview2_runtime_path).name
    safe_name = "".join(
        char if char.isalnum() or char in {".", "-", "_"} else "-"
        for char in runtime_name
    ).strip(".-_")
    return f"fixed-{safe_name or 'runtime'}"


def _resolve_app_icon_path() -> str | None:
    configured_path = os.getenv("TIANCE_APP_ICON")
    if configured_path:
        resolved = _resolve_path(configured_path)
        return str(resolved) if resolved.is_file() else None

    default_icon = DEFAULT_APP_ICON_FILE.resolve()
    return str(default_icon) if default_icon.is_file() else None


def _resolve_frontend_dist_path() -> Path:
    configured_path = os.getenv("TIANCE_FRONTEND_DIST_DIR")
    if configured_path:
        return _resolve_path(configured_path)

    return (PROJECT_ROOT / "2_ReactWeb" / "dist").resolve()


def _build_default_app_url(api_url: str, frontend_dist_path: Path) -> str:
    index_file = frontend_dist_path / "index.html"
    if not index_file.is_file():
        return f"{api_url}/app/"

    try:
        version = int(index_file.stat().st_mtime)
    except OSError:
        return f"{api_url}/app/"

    return f"{api_url}/app/?v={version}"


def _resolve_path(raw_path: str) -> Path:
    path = Path(raw_path).expanduser()
    if path.is_absolute():
        return path.resolve()

    return (SHELL_ROOT / path).resolve()


def _looks_like_webview2_runtime_dir(path: Path) -> bool:
    return path.is_dir() and (path / "msedgewebview2.exe").is_file()


def _find_webview2_runtime_dir(path: Path) -> Path | None:
    if _looks_like_webview2_runtime_dir(path):
        return path.resolve()

    if not path.is_dir():
        return None

    for child in sorted(path.iterdir()):
        if _looks_like_webview2_runtime_dir(child):
            return child.resolve()

    return None
