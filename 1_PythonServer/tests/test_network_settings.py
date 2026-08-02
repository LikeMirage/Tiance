from app.domain.network_settings import (
    DEFAULT_NETWORK_SETTINGS,
    BackendPortMode,
    NetworkConnectionMode,
    NetworkSettings,
    ProxyScheme,
)
from app.infra.database import ensure_database_schema
from app.repositories.network_settings_repository import NetworkSettingsRepository
from app.services.network_settings import NetworkSettingsService


def test_network_settings_use_defaults_before_first_save(tmp_path):
    database_path = tmp_path / "tiance.db"
    ensure_database_schema(database_path)
    service = NetworkSettingsService(NetworkSettingsRepository(database_path))

    assert service.get_settings() == DEFAULT_NETWORK_SETTINGS


def test_network_settings_persist_and_reconfigure_http_client(tmp_path, monkeypatch):
    database_path = tmp_path / "tiance.db"
    ensure_database_schema(database_path)
    service = NetworkSettingsService(NetworkSettingsRepository(database_path))
    configured = []
    monkeypatch.setattr(
        "app.services.network_settings.configure_shared_http_client",
        configured.append,
    )
    settings = NetworkSettings(
        connection_mode=NetworkConnectionMode.CUSTOM_PROXY,
        proxy_scheme=ProxyScheme.SOCKS5,
        proxy_host="127.0.0.1",
        proxy_port=7890,
        connect_timeout_seconds=8,
        read_timeout_seconds=90,
        stream_timeout_seconds=240,
        backend_port_mode=BackendPortMode.FIXED,
        fixed_backend_port=19000,
    )

    saved = service.save_settings(settings)
    reloaded = service.get_settings()

    assert saved.updated_at
    assert reloaded.connection_mode == NetworkConnectionMode.CUSTOM_PROXY
    assert reloaded.proxy_scheme == ProxyScheme.SOCKS5
    assert reloaded.backend_port_mode == BackendPortMode.FIXED
    assert reloaded.fixed_backend_port == 19000
    assert configured == [saved]


def test_direct_mode_does_not_require_custom_proxy_address(tmp_path, monkeypatch):
    database_path = tmp_path / "tiance.db"
    ensure_database_schema(database_path)
    service = NetworkSettingsService(NetworkSettingsRepository(database_path))
    monkeypatch.setattr(
        "app.services.network_settings.configure_shared_http_client",
        lambda _settings: None,
    )
    settings = NetworkSettings(
        connection_mode=NetworkConnectionMode.DIRECT,
        proxy_scheme=ProxyScheme.HTTP,
        proxy_host="",
        proxy_port=7890,
        connect_timeout_seconds=10,
        read_timeout_seconds=120,
        stream_timeout_seconds=300,
        backend_port_mode=BackendPortMode.AUTO,
        fixed_backend_port=18000,
    )

    saved = service.save_settings(settings)

    assert saved.connection_mode == NetworkConnectionMode.DIRECT
    assert saved.proxy_host == ""
