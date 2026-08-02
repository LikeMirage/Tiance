from functools import lru_cache
import ipaddress
import re

from app.core.errors import BadRequestError
from app.domain.network_settings import (
    DEFAULT_NETWORK_SETTINGS,
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


@lru_cache
def get_network_settings_service() -> NetworkSettingsService:
    return NetworkSettingsService(get_network_settings_repository())
