import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.microphone_permission import MicrophonePermission


class Event:
    def __init__(self):
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self


@pytest.fixture
def host(monkeypatch):
    monkeypatch.setattr("app.microphone_permission._state", lambda allow: "Allow" if allow else "Deny")
    monkeypatch.setattr("app.microphone_permission.sys.platform", "win32")
    # Dispatch synchronously in unit tests, without touching a real microphone.
    monkeypatch.setattr("app.microphone_permission.Thread", lambda target, args, daemon: SimpleNamespace(start=lambda: target(*args)))
    settings = SimpleNamespace(app_url="http://127.0.0.1:18000/app/", dev_url="http://127.0.0.1:18100")
    core = SimpleNamespace(Source=settings.app_url, PermissionRequested=Event(), NavigationStarting=Event(), ProcessFailed=Event())
    window = SimpleNamespace(native=SimpleNamespace(webview=SimpleNamespace(CoreWebView2=core)), evaluate_js=Mock(return_value=True))
    controller = MicrophonePermission(window, settings, lambda fn: fn())
    controller.install()
    controller.install()
    assert len(core.PermissionRequested.handlers) == 1
    return controller, core, window


def request(host, uri="http://127.0.0.1:18000/", kind="Microphone"):
    deferral = SimpleNamespace(Complete=Mock())
    args = SimpleNamespace(Uri=uri, PermissionKind=kind, State="Default", SavesInProfile=True, GetDeferral=Mock(return_value=deferral))
    host[1].PermissionRequested.handlers[0](None, args)
    return args, deferral


def test_request_waits_for_explicit_inline_grant_and_completes_once(host):
    controller, core, window = host
    args, deferred = request(host)
    deferred.Complete.assert_not_called()
    assert args.State == "Deny"
    assert not args.SavesInProfile
    request_id = next(iter(controller.pending))
    assert json.dumps(request_id) in window.evaluate_js.call_args[0][0]
    assert controller.respond(request_id, True)
    assert args.State == "Allow"
    assert args.SavesInProfile
    deferred.Complete.assert_called_once()
    assert not controller.respond(request_id, True)


def test_cancellation_does_not_persist_denial_and_retry_is_possible(host):
    args, deferred = request(host)
    controller = host[0]
    assert controller.respond(next(iter(controller.pending)), False)
    assert args.State == "Deny"
    assert not args.SavesInProfile
    deferred.Complete.assert_called_once()
    next_args, _ = request(host)
    assert controller.respond(next(iter(controller.pending)), True)
    assert next_args.State == "Allow"


@pytest.mark.parametrize("event", ["NavigationStarting", "ProcessFailed"])
def test_reload_or_renderer_failure_revokes_pending_request(host, event):
    controller, core, _ = host
    args, deferred = request(host)
    request_id = next(iter(controller.pending))
    getattr(core, event).handlers[0](None, None)
    assert not controller.respond(request_id, True)
    assert args.State == "Deny"
    deferred.Complete.assert_called_once()


def test_missing_composer_denies_without_popping_native_prompt(host):
    host[2].evaluate_js.return_value = False
    args, deferred = request(host)
    assert args.State == "Deny"
    assert not host[0].pending
    deferred.Complete.assert_called_once()


@pytest.mark.parametrize("url", ["about:blank", "file:///C:/untrusted.html", "http://127.0.0.1:18000/other", "http://127.0.0.1:19999/app/", "https://external.invalid/"])
def test_other_documents_cannot_get_inline_permission(host, url):
    host[1].Source = url
    args, _ = request(host, url)
    args.GetDeferral.assert_not_called()
    host[2].evaluate_js.assert_not_called()


@pytest.mark.parametrize("uri,kind", [("https://external.invalid", "Microphone"), ("http://127.0.0.1:18000/", "Camera")])
def test_other_origins_and_camera_keep_browser_permissions(host, uri, kind):
    args, _ = request(host, uri, kind)
    assert args.State == "Default"
    args.GetDeferral.assert_not_called()


def test_document_is_rechecked_before_grant(host):
    controller, core, _ = host
    args, deferred = request(host)
    core.Source = "https://external.invalid/"
    controller.respond(next(iter(controller.pending)), True)
    assert args.State == "Deny"
    assert not args.SavesInProfile
    deferred.Complete.assert_called_once()
