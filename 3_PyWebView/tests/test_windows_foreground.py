from __future__ import annotations

import ctypes
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app import api as api_module, windows_foreground as native
from app.api import ShellApi
from app.backend_process import BackendProcessManager


@pytest.mark.parametrize("foreground_pid,allowed", [(100, True), (100, False), (200, False), (0, False)])
def test_grant_requires_foreground_shell_and_targets_only_backend(monkeypatch, foreground_pid, allowed):
    def get_pid(_hwnd, result):
        result._obj.value = foreground_pid
        return 1

    user32 = SimpleNamespace(
        GetForegroundWindow=Mock(return_value=123),
        GetWindowThreadProcessId=Mock(side_effect=get_pid),
        AllowSetForegroundWindow=Mock(return_value=allowed),
    )
    monkeypatch.setattr(native.sys, "platform", "win32")
    monkeypatch.setattr(native.os, "getpid", lambda: 100)
    monkeypatch.setattr(ctypes, "WinDLL", lambda *_args, **_kwargs: user32, raising=False)

    assert native.allow_backend_foreground(300) is allowed
    if foreground_pid == 100:
        user32.AllowSetForegroundWindow.assert_called_once_with(300)
    else:
        user32.AllowSetForegroundWindow.assert_not_called()


@pytest.mark.parametrize("platform,pid", [("linux", 100), ("win32", None), ("win32", 0), ("win32", -1)])
def test_unavailable_backend_or_non_windows_does_not_grant(monkeypatch, platform, pid):
    monkeypatch.setattr(native.sys, "platform", platform)
    dll = Mock()
    monkeypatch.setattr(ctypes, "WinDLL", dll, raising=False)
    assert native.allow_backend_foreground(pid) is False
    dll.assert_not_called()


@pytest.mark.parametrize("exit_code", [None, 0, 1])
def test_backend_pid_is_available_only_for_live_managed_process(exit_code):
    manager = BackendProcessManager.__new__(BackendProcessManager)
    manager._lock = threading.Lock()
    manager._process = None
    assert manager.process_id is None
    manager._process = SimpleNamespace(pid=300, poll=lambda: exit_code)
    assert manager.process_id == (300 if exit_code is None else None)


def test_bridge_uses_managed_backend_pid_without_frontend_supplied_target(monkeypatch):
    grant = Mock(return_value=True)
    monkeypatch.setattr(api_module, "allow_backend_foreground", grant)
    api = ShellApi(SimpleNamespace(allow_remote_shell_api=False), SimpleNamespace(process_id=300))
    api._window = SimpleNamespace(url="http://127.0.0.1:18100")
    assert api.prepare_file_explorer() is True
    grant.assert_called_once_with(300)


def test_bridge_rejects_untrusted_page_before_grant(monkeypatch):
    grant = Mock()
    monkeypatch.setattr(api_module, "allow_backend_foreground", grant)
    api = ShellApi(SimpleNamespace(allow_remote_shell_api=False), SimpleNamespace(process_id=300))
    api._window = SimpleNamespace(url="https://example.com")
    with pytest.raises(PermissionError):
        api.prepare_file_explorer()
    grant.assert_not_called()
