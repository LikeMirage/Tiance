from pydantic import BaseModel, ConfigDict, Field

from app.domain.network_settings import (
    DEFAULT_NETWORK_SETTINGS,
    BackendPortMode,
    NetworkConnectionMode,
    NetworkSettings,
    ProxyScheme,
)


class NetworkSettingsPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    connection_mode: NetworkConnectionMode
    proxy_scheme: ProxyScheme
    proxy_host: str = Field(max_length=253)
    proxy_port: int = Field(ge=1, le=65535)
    connect_timeout_seconds: float = Field(ge=1, le=3600)
    read_timeout_seconds: float = Field(ge=1, le=3600)
    stream_timeout_seconds: float = Field(ge=1, le=3600)
    backend_port_mode: BackendPortMode
    fixed_backend_port: int = Field(ge=1, le=65535)
    external_access_enabled: bool

    def to_domain(self) -> NetworkSettings:
        return NetworkSettings(**self.model_dump())

    @classmethod
    def from_domain(cls, settings: NetworkSettings) -> "NetworkSettingsPayload":
        return cls(
            connection_mode=settings.connection_mode,
            proxy_scheme=settings.proxy_scheme,
            proxy_host=settings.proxy_host,
            proxy_port=settings.proxy_port,
            connect_timeout_seconds=settings.connect_timeout_seconds,
            read_timeout_seconds=settings.read_timeout_seconds,
            stream_timeout_seconds=settings.stream_timeout_seconds,
            backend_port_mode=settings.backend_port_mode,
            fixed_backend_port=settings.fixed_backend_port,
            external_access_enabled=settings.external_access_enabled,
        )


class NetworkSettingsSaveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    settings: NetworkSettingsPayload


class NetworkSettingsResponse(BaseModel):
    settings: NetworkSettingsPayload
    default_settings: NetworkSettingsPayload
    updated_at: str | None
    backend_port_restart_required: bool = True

    @classmethod
    def from_domain(cls, settings: NetworkSettings) -> "NetworkSettingsResponse":
        return cls(
            settings=NetworkSettingsPayload.from_domain(settings),
            default_settings=NetworkSettingsPayload.from_domain(DEFAULT_NETWORK_SETTINGS),
            updated_at=settings.updated_at,
        )


class NetworkDiagnosticResponse(BaseModel):
    ok: bool
    target: str
    status_code: int | None = None
    elapsed_ms: int
    error: str | None = None


class ExternalAccessSaveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool


class ExternalAccessStatusResponse(BaseModel):
    configured_enabled: bool
    effective_enabled: bool
    restart_required: bool
    listen_host: str
    port: int
    local_url: str
    access_urls: list[str]
