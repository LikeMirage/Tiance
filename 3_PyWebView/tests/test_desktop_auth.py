import json
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.process_security import ProcessSecurity, is_desktop_auth_document
from app.api import ShellApi
from app.gateway_process import GatewayProcessManager


def test_host_credentials_are_ephemeral_and_separate():
    first, second = ProcessSecurity(), ProcessSecurity()
    assert len(first.desktop_token) == 64
    assert len(first.backend_token) == 64
    assert len({first.desktop_token, first.backend_token, second.desktop_token, second.backend_token}) == 4
    payload = json.loads(first.gateway_bootstrap())
    assert payload == {"DesktopToken": first.desktop_token, "BackendToken": first.backend_token}
    assert first.desktop_token not in repr(first)


def test_unmanaged_backend_requires_explicit_matching_secret(monkeypatch):
    monkeypatch.delenv("TIANCE_GATEWAY_INTERNAL_TOKEN", raising=False)
    with pytest.raises(RuntimeError):
        ProcessSecurity.for_launch(manage_backend=False)
    monkeypatch.setenv("TIANCE_GATEWAY_INTERNAL_TOKEN", "c" * 64)
    assert ProcessSecurity.for_launch(manage_backend=False).backend_token == "c" * 64


def test_shell_rejects_stale_gateway_binary(monkeypatch):
    manager = GatewayProcessManager(SimpleNamespace(api_url="http://127.0.0.1:18000"), ProcessSecurity())
    manager._process = Mock(poll=Mock(return_value=None))
    response = BytesIO(b'{"ok":true}')
    response.status = 200
    monkeypatch.setattr("app.gateway_process.urlopen", lambda *args, **kwargs: response)
    with pytest.raises(RuntimeError, match="版本不一致"):
        manager._wait_until_ready()


def test_desktop_auth_is_bound_to_app_origin_and_never_returns_a_token(monkeypatch):
    settings = SimpleNamespace(app_url="http://127.0.0.1:18000/app/", dev_url="http://127.0.0.1:18100", allow_remote_shell_api=True)
    assert is_desktop_auth_document("", settings)
    assert is_desktop_auth_document("http://127.0.0.1:18000/app/", settings)
    assert is_desktop_auth_document("http://127.0.0.1:18100/", settings)
    assert not is_desktop_auth_document("http://127.0.0.1:19999/", settings)
    assert not is_desktop_auth_document("http://127.0.0.1:18000/other", settings)
    assert not is_desktop_auth_document("https://external.invalid/", settings)
    assert not is_desktop_auth_document("file:///C:/untrusted.html", settings)
    install = Mock(return_value=True)
    monkeypatch.setattr("app.api.install_desktop_cookie", install)
    api = ShellApi(settings, SimpleNamespace(), ProcessSecurity())
    api._window = SimpleNamespace(url=settings.app_url)
    assert api.prepare_gateway_access() is True
    assert install.call_count == 1
    api._window.url = "https://external.invalid"
    with pytest.raises(PermissionError):
        api.prepare_gateway_access()
    assert install.call_count == 1
