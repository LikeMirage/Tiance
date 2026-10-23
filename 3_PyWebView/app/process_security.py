"""Ephemeral host credentials; never exposed through the JavaScript bridge."""

from dataclasses import dataclass, field
import json
import os
import secrets
from urllib.parse import urlsplit


GATEWAY_TOKEN_ENV = "TIANCE_GATEWAY_INTERNAL_TOKEN"
GATEWAY_TOKEN_HEADER = "X-Tiance-Gateway-Token"
DESKTOP_COOKIE_NAME = "tiance_desktop_session"


@dataclass(frozen=True, repr=False)
class ProcessSecurity:
    desktop_token: str = field(default_factory=lambda: secrets.token_hex(32))
    backend_token: str = field(default_factory=lambda: secrets.token_hex(32))

    @classmethod
    def for_launch(cls, *, manage_backend: bool):
        if manage_backend:
            return cls()
        token = os.environ.pop(GATEWAY_TOKEN_ENV, "")
        if len(token) != 64 or any(char not in "0123456789abcdefABCDEF" for char in token):
            raise RuntimeError("独立后端模式必须配置相同的 TIANCE_GATEWAY_INTERNAL_TOKEN（64 位随机十六进制凭证）。")
        return cls(backend_token=token)

    def gateway_bootstrap(self) -> bytes:
        return (json.dumps({"DesktopToken": self.desktop_token, "BackendToken": self.backend_token}) + "\n").encode()


def is_desktop_auth_document(current_url: str, settings) -> bool:
    # pywebview's in-memory startup document has no URL (or about:blank).
    if not current_url or current_url == "about:blank":
        return True
    current = urlsplit(current_url)
    for trusted_url in (settings.app_url, settings.dev_url):
        trusted = urlsplit(trusted_url)
        if trusted.hostname not in {"127.0.0.1", "localhost", "::1"}:
            continue
        if (current.scheme, current.netloc) == (trusted.scheme, trusted.netloc):
            return current.path == trusted.path or current.path.startswith(trusted.path.rstrip("/") + "/")
    return False


def install_desktop_cookie(window, settings, security: ProcessSecurity) -> bool:
    # Native CookieManager preserves HttpOnly and keeps credentials out of page JS.
    from app.api import _run_on_native_window_thread

    def install():
        from Microsoft.Web.WebView2.Core import CoreWebView2CookieSameSiteKind

        control = getattr(getattr(window, "native", None), "webview", None)
        core = getattr(control, "CoreWebView2", None)
        if core is None:
            raise RuntimeError("Desktop authentication requires the initialized WebView2 host")
        manager = core.CookieManager
        host = urlsplit(settings.api_url).hostname
        cookie = manager.CreateCookie(DESKTOP_COOKIE_NAME, security.desktop_token, host, "/")
        cookie.IsHttpOnly = True
        cookie.IsSecure = urlsplit(settings.api_url).scheme == "https"
        cookie.SameSite = CoreWebView2CookieSameSiteKind.Strict
        manager.AddOrUpdateCookie(cookie)
        return True

    return bool(_run_on_native_window_thread(window, install))
