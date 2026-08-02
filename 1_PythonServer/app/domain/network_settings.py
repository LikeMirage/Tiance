from dataclasses import dataclass
from enum import StrEnum


class NetworkConnectionMode(StrEnum):
    SYSTEM = "system"
    DIRECT = "direct"
    CUSTOM_PROXY = "custom_proxy"


class ProxyScheme(StrEnum):
    HTTP = "http"
    HTTPS = "https"
    SOCKS5 = "socks5"


class BackendPortMode(StrEnum):
    AUTO = "auto"
    FIXED = "fixed"


@dataclass(frozen=True, slots=True)
class NetworkSettings:
    connection_mode: NetworkConnectionMode
    proxy_scheme: ProxyScheme
    proxy_host: str
    proxy_port: int
    connect_timeout_seconds: float
    read_timeout_seconds: float
    stream_timeout_seconds: float
    backend_port_mode: BackendPortMode
    fixed_backend_port: int
    updated_at: str | None = None


DEFAULT_NETWORK_SETTINGS = NetworkSettings(
    connection_mode=NetworkConnectionMode.SYSTEM,
    proxy_scheme=ProxyScheme.HTTP,
    proxy_host="127.0.0.1",
    proxy_port=7897,
    connect_timeout_seconds=10.0,
    read_timeout_seconds=120.0,
    stream_timeout_seconds=300.0,
    backend_port_mode=BackendPortMode.AUTO,
    fixed_backend_port=18000,
)
