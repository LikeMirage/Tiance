from dataclasses import replace
from urllib import request as urllib_request

import pytest

from app.domain.network_settings import DEFAULT_NETWORK_SETTINGS, NetworkConnectionMode
from app.infra import http_client as shared


@pytest.mark.parametrize("system,expected", [
    ({"http": "http://127.0.0.1:6001", "https": "http://127.0.0.1:6001"}, "http://127.0.0.1:6001"),
    ({}, None),
])
def test_windows_system_proxy_uses_registry_instead_of_inherited_environment(monkeypatch, system, expected):
    monkeypatch.setattr(urllib_request, "getproxies_registry", lambda: system, raising=False)
    # A desktop shell may inherit this obsolete value before the OS changes.
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:5999")
    monkeypatch.setenv("https_proxy", "http://127.0.0.1:5999")

    assert shared._get_system_proxy() == expected


def test_other_platforms_keep_standard_library_proxy_discovery(monkeypatch):
    monkeypatch.delattr(urllib_request, "getproxies_registry", raising=False)
    monkeypatch.setattr(urllib_request, "getproxies", lambda: {"all": "socks5://127.0.0.1:6003"})

    assert shared._get_system_proxy() == "socks5://127.0.0.1:6003"


@pytest.mark.parametrize("system_proxy", [None, "http://127.0.0.1:6001"])
def test_client_uses_the_resolved_proxy_snapshot_without_environment_fallback(monkeypatch, system_proxy):
    monkeypatch.setattr(shared, "_get_system_proxy", lambda: system_proxy)
    shared.configure_shared_http_client(DEFAULT_NETWORK_SETTINGS)

    def unexpected_read():
        pytest.fail("Client construction must use the same snapshot used for pool invalidation")

    monkeypatch.setattr(shared, "_get_system_proxy", unexpected_read)
    monkeypatch.setattr(shared.httpx, "AsyncClient", lambda **kwargs: kwargs)
    kwargs = shared._build_http_client()

    assert kwargs.get("proxy") == system_proxy
    assert kwargs["trust_env"] is False


@pytest.mark.parametrize("mode,expected", [
    (NetworkConnectionMode.DIRECT, None),
    (NetworkConnectionMode.CUSTOM_PROXY, "http://127.0.0.1:6004"),
])
def test_explicit_modes_do_not_consult_system_proxy(monkeypatch, mode, expected):
    def unexpected_read():
        pytest.fail("Explicit modes must not consult the system proxy")

    monkeypatch.setattr(shared, "_get_system_proxy", unexpected_read)
    shared.configure_shared_http_client(replace(DEFAULT_NETWORK_SETTINGS, connection_mode=mode, proxy_port=6004))
    monkeypatch.setattr(shared.httpx, "AsyncClient", lambda **kwargs: kwargs)
    kwargs = shared._build_http_client()

    assert kwargs.get("proxy") == expected
    assert kwargs["trust_env"] is False
