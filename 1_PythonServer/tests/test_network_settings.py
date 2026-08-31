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
import run as backend_run


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
        external_access_enabled=False,
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
        external_access_enabled=False,
    )

    saved = service.save_settings(settings)

    assert saved.connection_mode == NetworkConnectionMode.DIRECT
    assert saved.proxy_host == ""


def test_external_access_setting_uses_existing_network_settings_record(tmp_path, monkeypatch):
    database_path = tmp_path / "tiance.db"
    ensure_database_schema(database_path)
    service = NetworkSettingsService(NetworkSettingsRepository(database_path))
    monkeypatch.setattr(
        "app.services.network_settings.configure_shared_http_client",
        lambda _settings: None,
    )
    monkeypatch.setenv("TIANCE_GATEWAY_HOST", "127.0.0.1")
    monkeypatch.setenv("TIANCE_GATEWAY_PORT", "19011")

    status = service.save_external_access(True)

    assert service.get_settings().external_access_enabled is True
    assert status.configured_enabled is True
    assert status.effective_enabled is False
    assert status.restart_required is True
    assert status.port == 19011


def test_external_access_status_reports_effective_listener(tmp_path, monkeypatch):
    database_path = tmp_path / "tiance.db"
    ensure_database_schema(database_path)
    service = NetworkSettingsService(NetworkSettingsRepository(database_path))
    monkeypatch.setattr(
        "app.services.network_settings.configure_shared_http_client",
        lambda _settings: None,
    )
    monkeypatch.setattr(
        "app.services.network_settings._discover_access_addresses",
        lambda: ["192.168.1.25"],
    )
    monkeypatch.setenv("TIANCE_GATEWAY_HOST", "0.0.0.0")
    monkeypatch.setenv("TIANCE_GATEWAY_PORT", "19012")

    status = service.save_external_access(True)

    assert status.effective_enabled is True
    assert status.restart_required is False
    assert status.access_urls == ("http://192.168.1.25:19012/app/",)


def test_external_access_status_uses_https_port_only_when_https_is_enabled(tmp_path, monkeypatch):
    database_path = tmp_path / "tiance.db"
    ensure_database_schema(database_path)
    service = NetworkSettingsService(NetworkSettingsRepository(database_path))
    monkeypatch.setattr(
        "app.services.network_settings._discover_access_addresses",
        lambda: ["192.168.1.25"],
    )
    monkeypatch.setenv("TIANCE_GATEWAY_HOST", "0.0.0.0")
    monkeypatch.setenv("TIANCE_GATEWAY_PORT", "18000")
    monkeypatch.setenv("TIANCE_GATEWAY_HTTPS_PORT", "18443")
    monkeypatch.setenv("TIANCE_GATEWAY_HTTPS_ENABLED", "false")

    status = service.get_external_access_status()

    assert status.access_urls == ("http://192.168.1.25:18000/app/",)

    monkeypatch.setenv("TIANCE_GATEWAY_HTTPS_ENABLED", "true")

    status = service.get_external_access_status()

    assert status.access_urls == ("https://192.168.1.25:18443/app/",)


def test_source_server_defaults_to_loopback_when_host_env_is_missing(monkeypatch):
    monkeypatch.delenv("TIANCE_API_HOST", raising=False)

    assert backend_run._resolve_api_host() == "127.0.0.1"


def test_source_server_allows_explicit_host_override(monkeypatch):
    monkeypatch.setenv("TIANCE_API_HOST", "0.0.0.0")

    assert backend_run._resolve_api_host() == "0.0.0.0"
