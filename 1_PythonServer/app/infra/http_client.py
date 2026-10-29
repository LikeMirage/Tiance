import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
import logging
from threading import RLock
from typing import AsyncIterator
from urllib.request import getproxies

import httpx

from app.domain.network_settings import NetworkConnectionMode, NetworkSettings


@dataclass(eq=False)
class _ClientEntry:
    client: httpx.AsyncClient
    loop: asyncio.AbstractEventLoop
    users: int = 0
    retired: bool = False
    close_queued: bool = False
    close_task: asyncio.Task[None] | None = None


_HTTP_CLIENTS: dict[asyncio.AbstractEventLoop, _ClientEntry] = {}
_CLIENT_ENTRIES: dict[int, _ClientEntry] = {}
_CLIENT_LOCK = RLock()
_LOGGER = logging.getLogger(__name__)
_HTTP_CLIENT_SETTINGS: NetworkSettings | None = None
_HTTP_LIMITS = httpx.Limits(
    max_connections=100,
    max_keepalive_connections=20,
    keepalive_expiry=30.0,
)


def configure_shared_http_client(settings: NetworkSettings) -> None:
    global _HTTP_CLIENT_SETTINGS

    with _CLIENT_LOCK:
        if settings == _HTTP_CLIENT_SETTINGS:
            return
        _HTTP_CLIENT_SETTINGS = settings
        for entry in _HTTP_CLIENTS.values():
            entry.retired = True
            _queue_idle_close(entry)
        _HTTP_CLIENTS.clear()


def get_shared_http_client() -> httpx.AsyncClient:
    loop = asyncio.get_running_loop()
    with _CLIENT_LOCK:
        entry = _HTTP_CLIENTS.get(loop)
        if entry is not None and not entry.client.is_closed:
            return entry.client
        if entry is not None:
            _CLIENT_ENTRIES.pop(id(entry.client), None)
        client = _build_http_client()
        entry = _ClientEntry(client, loop)
        _HTTP_CLIENTS[loop] = entry
        _CLIENT_ENTRIES[id(client)] = entry
        return client


@asynccontextmanager
async def lease_http_client(client: httpx.AsyncClient) -> AsyncIterator[httpx.AsyncClient]:
    """Hold a shared client through the entire request, including streamed bodies.

    Enter immediately after get_shared_http_client(), without an intervening
    await. This keeps caller-supplied test clients usable without taking ownership.
    """
    with _CLIENT_LOCK:
        entry = _CLIENT_ENTRIES.get(id(client))
        if entry is not None:
            entry.users += 1
    try:
        yield client
    finally:
        if entry is not None:
            with _CLIENT_LOCK:
                entry.users -= 1
                if entry.retired:
                    _queue_idle_close(entry)


def _queue_idle_close(entry: _ClientEntry) -> None:
    if entry.users or entry.close_queued or entry.close_task is not None:
        return
    if entry.loop.is_closed():
        return  # Shutdown still drains entries whose owner loop has stopped.
    entry.close_queued = True
    try:
        entry.loop.call_soon_threadsafe(_start_idle_close, entry)
    except RuntimeError:
        # The owner may have stopped between the is_closed check and scheduling.
        entry.close_queued = False


def _start_idle_close(entry: _ClientEntry) -> None:
    with _CLIENT_LOCK:
        entry.close_queued = False
        if entry.users or entry.close_task is not None:
            return
        entry.close_task = asyncio.create_task(_close_entry(entry))


async def _close_entry(entry: _ClientEntry) -> None:
    try:
        if not entry.client.is_closed:
            await entry.client.aclose()
    except Exception:
        _LOGGER.exception("Unable to close retired HTTP client")
    finally:
        with _CLIENT_LOCK:
            _CLIENT_ENTRIES.pop(id(entry.client), None)


async def _drain_entry(entry: _ClientEntry) -> None:
    with _CLIENT_LOCK:
        if entry.close_task is None or entry.close_task.cancelled():
            entry.close_task = asyncio.create_task(_close_entry(entry))
        task = entry.close_task
    await asyncio.shield(task)


def start_shared_http_client() -> None:
    get_shared_http_client()


async def close_shared_http_clients() -> None:
    with _CLIENT_LOCK:
        entries = tuple(_CLIENT_ENTRIES.values())
        _HTTP_CLIENTS.clear()
        for entry in entries:
            entry.retired = True
    current_loop = asyncio.get_running_loop()
    for entry in entries:
        if entry.loop is not current_loop and entry.loop.is_running():
            await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(_drain_entry(entry), entry.loop))
        else:
            await _drain_entry(entry)


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
