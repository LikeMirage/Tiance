from dataclasses import dataclass
from urllib.parse import urlparse

from app.config import ShellSettings
from app.startup_page import render_startup_page
from app.startup_timing import mark


@dataclass(frozen=True)
class LaunchTarget:
    url: str | None = None
    html: str | None = None
    shell_api_allowed: bool = False


def resolve_launch_target(settings: ShellSettings) -> LaunchTarget:
    mark("launch target: resolving")
    mark("launch target: startup page selected")
    return LaunchTarget(
        html=render_startup_page(settings),
        shell_api_allowed=is_shell_api_allowed_url(settings.app_url, settings),
    )


def is_shell_api_allowed_url(url: str, settings: ShellSettings) -> bool:
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()

    if scheme == "file":
        return True

    if scheme not in {"http", "https"}:
        return settings.allow_remote_shell_api

    hostname = (parsed.hostname or "").lower()
    if hostname in {"127.0.0.1", "localhost", "::1"}:
        return True

    return settings.allow_remote_shell_api
