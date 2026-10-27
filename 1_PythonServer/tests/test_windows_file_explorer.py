from __future__ import annotations

import ctypes
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.core.errors import BadRequestError
from app.infra import file_explorer, windows_file_explorer as native
from app.infra.file_workspace import FileWorkspaceStorage, file_storage


@pytest.mark.parametrize("shell_hwnd,shell_pid,allowed", [(123, 456, True), (123, 456, False), (0, 0, False), (123, 0, False)])
def test_foreground_permission_targets_shell_process_only(monkeypatch, shell_hwnd, shell_pid, allowed):
    def get_pid(_hwnd, result):
        result._obj.value = shell_pid
        return 1

    user32 = SimpleNamespace(
        GetShellWindow=Mock(return_value=shell_hwnd),
        GetWindowThreadProcessId=Mock(side_effect=get_pid),
        AllowSetForegroundWindow=Mock(return_value=allowed),
    )
    monkeypatch.setattr(ctypes, "WinDLL", lambda *_args, **_kwargs: user32, raising=False)

    assert native._allow_explorer_foreground() is allowed
    if shell_hwnd and shell_pid:
        user32.AllowSetForegroundWindow.assert_called_once_with(shell_pid)
    else:
        user32.AllowSetForegroundWindow.assert_not_called()


@pytest.mark.parametrize("is_file", [False, True])
def test_reveal_still_opens_when_foreground_permission_is_unavailable(monkeypatch, tmp_path, is_file):
    target = tmp_path / "目录 文件,示例.txt" if is_file else tmp_path
    if is_file:
        target.write_text("test", encoding="utf-8")
    events = []
    monkeypatch.setattr(native, "_allow_explorer_foreground", lambda: events.append("permission") or False)
    monkeypatch.setattr(native.os, "startfile", lambda path: events.append(("folder", path)), raising=False)
    monkeypatch.setattr(native, "_select_file", lambda path: events.append(("file", str(path))))

    native.reveal_in_windows_explorer(target)

    assert events == ["permission", ("file" if is_file else "folder", str(target))]


@pytest.mark.parametrize("failure", [None, "parse", "open", "changed_mode", "initialize"])
def test_native_file_selection_balances_com_and_frees_pidl(monkeypatch, tmp_path, failure):
    events = []
    error = OSError("native failure")
    if failure == "changed_mode":
        error.winerror = -2147417850

    def initialize(*_args):
        events.append("initialize")
        if failure in {"changed_mode", "initialize"}:
            raise error

    def parse(path, _binding, result, *_args):
        events.append(("parse", path))
        if failure == "parse":
            raise error
        result._obj.value = 12345

    def open_selected(item, count, children, flags):
        events.append(("open", item.value, count, children, flags))
        if failure == "open":
            raise error

    ole32 = SimpleNamespace(
        CoInitializeEx=Mock(side_effect=initialize),
        CoUninitialize=Mock(side_effect=lambda: events.append("uninitialize")),
        CoTaskMemFree=Mock(side_effect=lambda item: events.append(("free", item.value))),
    )
    shell32 = SimpleNamespace(SHParseDisplayName=Mock(side_effect=parse), SHOpenFolderAndSelectItems=Mock(side_effect=open_selected))
    monkeypatch.setattr(ctypes, "OleDLL", lambda name: ole32 if name == "ole32" else shell32, raising=False)
    target = tmp_path / "中文 文件,名字.txt"

    if failure in {"initialize", "parse", "open"}:
        with pytest.raises(OSError, match="native failure"):
            native._select_file(target)
    else:
        native._select_file(target)

    if failure == "initialize":
        assert events == ["initialize"]
        return
    assert events[:2] == ["initialize", ("parse", str(target))]
    if failure == "parse":
        assert events[2:] == ["uninitialize"]
        return
    assert events[2:4] == [("open", 12345, 0, None, 0), ("free", 12345)]
    assert events[4:] == ([] if failure == "changed_mode" else ["uninitialize"])


@pytest.mark.parametrize("relative", ["", "nested", "nested/example.txt"])
def test_workspace_reveal_uses_common_path_opener(monkeypatch, tmp_path, relative):
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested/example.txt").write_text("test", encoding="utf-8")
    reveal = Mock()
    monkeypatch.setattr(file_storage, "reveal_path_in_file_explorer", reveal)

    FileWorkspaceStorage().reveal_entry(str(tmp_path), relative)

    reveal.assert_called_once_with((tmp_path / relative).resolve())


def test_workspace_reveal_keeps_path_boundary_and_open_error_handling(monkeypatch, tmp_path):
    reveal = Mock(side_effect=file_explorer.FileExplorerOpenError("native failure"))
    monkeypatch.setattr(file_storage, "reveal_path_in_file_explorer", reveal)
    with pytest.raises(ValueError):
        FileWorkspaceStorage().reveal_entry(str(tmp_path), "../outside")
    reveal.assert_not_called()
    with pytest.raises(BadRequestError):
        FileWorkspaceStorage().reveal_entry(str(tmp_path), "")


def test_windows_reveal_rejects_missing_path_before_native_call(monkeypatch, tmp_path):
    reveal = Mock()
    monkeypatch.setattr(native, "reveal_in_windows_explorer", reveal)
    with pytest.raises(file_explorer.FileExplorerOpenError, match="does not exist"):
        file_explorer.reveal_path_in_file_explorer(tmp_path / "missing")
    reveal.assert_not_called()


def test_provider_directory_opener_routes_through_common_windows_reveal(monkeypatch, tmp_path):
    monkeypatch.setattr(file_explorer.sys, "platform", "win32")
    reveal = Mock()
    monkeypatch.setattr(native, "reveal_in_windows_explorer", reveal)
    file_explorer.open_directory_in_file_explorer(tmp_path)
    reveal.assert_called_once_with(tmp_path.resolve())
