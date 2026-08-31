from html import escape
import json
from pathlib import Path

from app.config import SHELL_ROOT, ShellSettings
from app.startup_theme import load_startup_theme


STARTUP_CHECK_INITIAL_DELAY_MS = 80
STARTUP_CHECK_FAST_RETRY_DELAY_MS = 200
STARTUP_CHECK_FAST_RETRY_ATTEMPTS = 25
STARTUP_CHECK_RETRY_DELAY_MS = 900
STARTUP_CHECK_MAX_ATTEMPTS = 50
STARTUP_CHECK_DEFAULT_TIMEOUT_MS = 260
STARTUP_CHECK_API_TIMEOUT_MS = 300
STARTUP_CHECK_APP_TIMEOUT_MS = 700
STARTUP_CHECK_DEV_TIMEOUT_MS = 180

STARTUP_ASSETS_DIR = SHELL_ROOT / "assets" / "startup"
STARTUP_HTML_FILE = STARTUP_ASSETS_DIR / "index.html"
STARTUP_CSS_FILE = STARTUP_ASSETS_DIR / "startup.css"
STARTUP_SCRIPT_FILE = STARTUP_ASSETS_DIR / "startup.js"


def render_startup_page(settings: ShellSettings) -> str:
    startup_theme = load_startup_theme()
    startup_state = {
        "apiUrl": settings.api_url,
        "gatewayHealthUrl": f"{settings.api_url}/gateway/health",
        "devUrl": settings.dev_url,
        "appUrl": settings.app_url,
        "distExists": _frontend_dist_exists(settings),
        "bootTheme": {
            "mode": startup_theme.mode,
            "surfaceBase": startup_theme.surface_base,
            "borderSeparator": startup_theme.border_separator,
            "textPrimary": startup_theme.text_primary,
            "textMuted": startup_theme.text_muted,
            "accent": startup_theme.accent,
            "accentRgb": startup_theme.accent_rgb,
        },
    }
    startup_config = {
        "initialDelayMs": STARTUP_CHECK_INITIAL_DELAY_MS,
        "fastRetryDelayMs": STARTUP_CHECK_FAST_RETRY_DELAY_MS,
        "fastRetryAttempts": STARTUP_CHECK_FAST_RETRY_ATTEMPTS,
        "retryDelayMs": STARTUP_CHECK_RETRY_DELAY_MS,
        "maxAttempts": STARTUP_CHECK_MAX_ATTEMPTS,
        "defaultTimeoutMs": STARTUP_CHECK_DEFAULT_TIMEOUT_MS,
        "apiTimeoutMs": STARTUP_CHECK_API_TIMEOUT_MS,
        "appTimeoutMs": STARTUP_CHECK_APP_TIMEOUT_MS,
        "devTimeoutMs": STARTUP_CHECK_DEV_TIMEOUT_MS,
    }

    title = escape(settings.title)
    styles = _read_asset(STARTUP_CSS_FILE)
    styles = _replace_tokens(
        styles,
        {
            "__TIANCE_THEME_MODE__": startup_theme.mode,
            "__TIANCE_SURFACE_BASE__": startup_theme.surface_base,
            "__TIANCE_SURFACE_TITLEBAR__": startup_theme.surface_titlebar,
            "__TIANCE_BORDER_SEPARATOR__": startup_theme.border_separator,
            "__TIANCE_TEXT_PRIMARY__": startup_theme.text_primary,
            "__TIANCE_TEXT_MUTED__": startup_theme.text_muted,
            "__TIANCE_ACCENT__": startup_theme.accent,
            "__TIANCE_ACCENT_RGB__": startup_theme.accent_rgb,
            "__TIANCE_DANGER_TEXT__": startup_theme.danger_text,
            "__TIANCE_DANGER_BORDER__": startup_theme.danger_border,
        },
    )
    script = _replace_tokens(
        _read_asset(STARTUP_SCRIPT_FILE),
        {
            "__TIANCE_STARTUP_STATE__": _json_for_inline_script(startup_state),
            "__TIANCE_STARTUP_CONFIG__": _json_for_inline_script(startup_config),
        },
    )
    return _replace_tokens(
        _read_asset(STARTUP_HTML_FILE),
        {
            "__TIANCE_TITLE__": title,
            "__TIANCE_STARTUP_STYLES__": styles,
            "__TIANCE_STARTUP_SCRIPT__": script,
        },
    )


def _frontend_dist_exists(settings: ShellSettings) -> bool:
    dist_path = Path(settings.frontend_dist_path)
    return dist_path.is_dir() and (dist_path / "index.html").is_file()


def _read_asset(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"Desktop startup asset is unavailable: {path}") from exc


def _json_for_inline_script(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def _replace_tokens(content: str, replacements: dict[str, str]) -> str:
    for token, value in replacements.items():
        content = content.replace(token, value)
    return content
