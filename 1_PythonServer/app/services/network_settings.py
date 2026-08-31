from dataclasses import replace
from functools import lru_cache
import ipaddress
import os
import re
import socket

from app.core.errors import BadRequestError
from app.domain.network_settings import (
    DEFAULT_NETWORK_SETTINGS,
    ExternalAccessStatus,
    NetworkConnectionMode,
    NetworkSettings,
)
from app.infra.http_client import configure_shared_http_client
from app.repositories.network_settings_repository import (
    NetworkSettingsRepository,
    get_network_settings_repository,
)


class NetworkSettingsService:
    def __init__(self, repository: NetworkSettingsRepository) -> None:
        self._repository = repository

    def get_settings(self) -> NetworkSettings:
        return self._repository.get_settings() or DEFAULT_NETWORK_SETTINGS

    def save_settings(self, settings: NetworkSettings) -> NetworkSettings:
        _validate_settings(settings)
        saved = self._repository.save_settings(settings)
        configure_shared_http_client(saved)
        return saved

    def save_external_access(self, enabled: bool) -> ExternalAccessStatus:
        current = self.get_settings()
        self.save_settings(replace(current, external_access_enabled=enabled))
        return self.get_external_access_status()

    def get_external_access_status(self) -> ExternalAccessStatus:
        settings = self.get_settings()
        listen_host = _effective_gateway_listen_host()
        port = _effective_gateway_port(settings)
        effective_enabled = _effective_gateway_external_access_enabled(listen_host)
        local_url = f"http://127.0.0.1:{port}/app/"
        https_enabled = _effective_gateway_https_enabled()
        external_scheme = "https" if https_enabled else "http"
        external_port = _effective_gateway_https_port(port) if https_enabled else port
        access_urls = tuple(
            f"{external_scheme}://{address}:{external_port}/app/"
            for address in _discover_access_addresses()
        )
        return ExternalAccessStatus(
            configured_enabled=settings.external_access_enabled,
            effective_enabled=effective_enabled,
            restart_required=settings.external_access_enabled != effective_enabled,
            listen_host=listen_host,
            port=port,
            local_url=local_url,
            access_urls=access_urls,
        )


def _validate_settings(settings: NetworkSettings) -> None:
    if settings.connection_mode == NetworkConnectionMode.CUSTOM_PROXY:
        host = settings.proxy_host.strip()
        if not host:
            raise BadRequestError("自定义代理主机不能为空。")
        if "://" in host or "/" in host or "@" in host:
            raise BadRequestError("代理主机只填写域名或 IP 地址，不要包含协议、路径或账号。")
        try:
            ipaddress.ip_address(host.strip("[]"))
        except ValueError:
            labels = host.rstrip(".").split(".")
            if (
                any(not label or len(label) > 63 for label in labels)
                or re.fullmatch(r"[A-Za-z0-9._-]+", host) is None
            ):
                raise BadRequestError("代理主机格式无效。")
        if not 1 <= settings.proxy_port <= 65535:
            raise BadRequestError("代理端口必须在 1 到 65535 之间。")
    if not 1 <= settings.fixed_backend_port <= 65535:
        raise BadRequestError("固定后端端口必须在 1 到 65535 之间。")
    for label, value in (
        ("连接超时", settings.connect_timeout_seconds),
        ("普通读取超时", settings.read_timeout_seconds),
        ("流式读取超时", settings.stream_timeout_seconds),
    ):
        if not 1 <= value <= 3600:
            raise BadRequestError(f"{label}必须在 1 到 3600 秒之间。")


def _effective_gateway_listen_host() -> str:
    configured = os.getenv("TIANCE_GATEWAY_HOST")
    if configured is not None and configured.strip():
        return configured.strip()
    return "127.0.0.1"


def _effective_gateway_port(settings: NetworkSettings) -> int:
    configured = os.getenv("TIANCE_GATEWAY_PORT")
    if configured is not None:
        try:
            port = int(configured.strip())
        except ValueError:
            port = 0
        if 1 <= port <= 65535:
            return port
    if settings.backend_port_mode.value == "fixed":
        return settings.fixed_backend_port
    return 18000


def _effective_gateway_external_access_enabled(listen_host: str) -> bool:
    configured = os.getenv("TIANCE_GATEWAY_EXTERNAL_ACCESS_ENABLED")
    if configured is not None and configured.strip():
        return configured.strip().lower() in {"1", "true", "yes", "on"}
    return not _is_loopback_host(listen_host)


def _effective_gateway_https_enabled() -> bool:
    return (os.getenv("TIANCE_GATEWAY_HTTPS_ENABLED") or "").strip().lower() in {
        "1", "true", "yes", "on",
    }


def _effective_gateway_https_port(http_port: int) -> int:
    configured = os.getenv("TIANCE_GATEWAY_HTTPS_PORT")
    try:
        port = int((configured or "").strip())
    except ValueError:
        return http_port
    return port if 1 <= port <= 65535 else http_port


def _is_loopback_host(host: str) -> bool:
    normalized = host.strip().strip("[]")
    if normalized.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def _discover_access_addresses() -> list[str]:
    addresses: set[str] = set()
    try:
        for info in socket.getaddrinfo(
            socket.gethostname(),
            None,
            family=socket.AF_INET,
            type=socket.SOCK_STREAM,
        ):
            addresses.add(str(info[4][0]))
    except OSError:
        pass

    usable: list[tuple[bool, str]] = []
    for address in addresses:
        try:
            parsed = ipaddress.ip_address(address)
        except ValueError:
            continue
        if parsed.is_loopback or parsed.is_unspecified or parsed.is_multicast or parsed.is_link_local:
            continue
        usable.append((not parsed.is_private, address))
    usable.sort()
    return [address for _is_public, address in usable]


@lru_cache
def get_network_settings_service() -> NetworkSettingsService:
    return NetworkSettingsService(get_network_settings_repository())
