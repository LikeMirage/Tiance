import asyncio
from urllib.request import getproxies

import httpx

from app.domain.network_settings import NetworkConnectionMode, NetworkSettings


_HTTP_CLIENTS: dict[asyncio.AbstractEventLoop, tuple[int, httpx.AsyncClient]] = {}
_RETIRED_HTTP_CLIENTS: list[httpx.AsyncClient] = []
_HTTP_CLIENT_SETTINGS: NetworkSettings | None = None
_HTTP_CLIENT_SETTINGS_GENERATION = 0
_HTTP_LIMITS = httpx.Limits(
    max_connections=100,
    max_keepalive_connections=20,
    keepalive_expiry=30.0,
)


def configure_shared_http_client(settings: NetworkSettings) -> None:
    global _HTTP_CLIENT_SETTINGS
    global _HTTP_CLIENT_SETTINGS_GENERATION

    if settings == _HTTP_CLIENT_SETTINGS:
        return
    _HTTP_CLIENT_SETTINGS = settings
    _HTTP_CLIENT_SETTINGS_GENERATION += 1


def get_shared_http_client() -> httpx.AsyncClient:
    loop = asyncio.get_running_loop()
    entry = _HTTP_CLIENTS.get(loop)
    if entry is not None:
        generation, client = entry
        if generation == _HTTP_CLIENT_SETTINGS_GENERATION and not client.is_closed:
            return client
        if not client.is_closed:
            _RETIRED_HTTP_CLIENTS.append(client)

    client = _build_http_client()
    _HTTP_CLIENTS[loop] = (_HTTP_CLIENT_SETTINGS_GENERATION, client)
    return client


def start_shared_http_client() -> None:
    get_shared_http_client()


async def close_shared_http_clients() -> None:
    clients = tuple(client for _, client in _HTTP_CLIENTS.values()) + tuple(
        _RETIRED_HTTP_CLIENTS,
    )
    _HTTP_CLIENTS.clear()
    _RETIRED_HTTP_CLIENTS.clear()
    for client in clients:
        if not client.is_closed:
            await client.aclose()


def get_http_timeout(*, stream: bool = False) -> httpx.Timeout:
    settings = _require_settings()
    return httpx.Timeout(
        connect=settings.connect_timeout_seconds,
        read=(
            settings.stream_timeout_seconds
            if stream
            else settings.read_timeout_seconds
        ),
        write=settings.read_timeout_seconds,
        pool=settings.connect_timeout_seconds,
    )


def _build_http_client() -> httpx.AsyncClient:
    settings = _require_settings()
    kwargs: dict[str, object] = {
        "limits": _HTTP_LIMITS,
        "timeout": get_http_timeout(),
        "trust_env": False,
        "follow_redirects": True,
    }
    if settings.connection_mode == NetworkConnectionMode.SYSTEM:
        system_proxy = _get_system_proxy()
        if system_proxy is not None:
            kwargs["proxy"] = system_proxy
        else:
            kwargs["trust_env"] = True
    elif settings.connection_mode == NetworkConnectionMode.CUSTOM_PROXY:
        kwargs["proxy"] = (
            f"{settings.proxy_scheme.value}://"
            f"{settings.proxy_host}:{settings.proxy_port}"
        )
    return httpx.AsyncClient(**kwargs)


def _get_system_proxy() -> str | None:
    proxies = getproxies()
    for scheme in ("https", "http", "all"):
        proxy = proxies.get(scheme)
        if proxy:
            return proxy
    return None


def _require_settings() -> NetworkSettings:
    if _HTTP_CLIENT_SETTINGS is None:
        raise RuntimeError("Shared HTTP client settings have not been configured.")
    return _HTTP_CLIENT_SETTINGS
