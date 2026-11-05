from __future__ import annotations

import sys
from types import SimpleNamespace

from app import windows_file_drag


def test_native_drag_uses_ui_thread_file_drop_copy_and_shared_path_normalization(tmp_path, monkeypatch):
    source = tmp_path / "会议记录.docx"
    source.write_bytes(b"test file")
    calls = []

    class FileList(list):
        def Add(self, value):
            self.append(value)

    class DataObject:
        def SetFileDropList(self, files):
            self.files = files

    controls = SimpleNamespace(MouseButtons=1)
    monkeypatch.setattr(windows_file_drag.sys, "platform", "win32")
    monkeypatch.setitem(sys.modules, "System", SimpleNamespace(Action=lambda run: run))
    monkeypatch.setitem(sys.modules, "System.Collections.Specialized", SimpleNamespace(StringCollection=FileList))
    monkeypatch.setitem(sys.modules, "System.Windows.Forms", SimpleNamespace(
        Control=controls, DataObject=DataObject,
        DragDropEffects=SimpleNamespace(Copy=1), MouseButtons=SimpleNamespace(Left=1),
    ))

    def invoke(callback):
        calls.append("invoke")
        callback()

    def drop(data, effect):
        calls.append((list(data.files), effect))
        return 0  # Cancellation/rejection is a completed drag, not a bridge failure.

    window = SimpleNamespace(native=SimpleNamespace(InvokeRequired=True, Invoke=invoke, DoDragDrop=drop))
    assert windows_file_drag.start_file_drag(window, [str(source), str(source)]) is True
    assert calls == ["invoke", ([str(source.resolve())], 1)]
    assert source.read_bytes() == b"test file"

    # No stale drag after mouse release and no missing-file payload.
    calls.clear()
    controls.MouseButtons = 0
    assert windows_file_drag.start_file_drag(window, [str(source)]) is False
    assert calls == ["invoke"]
    calls.clear()
    assert windows_file_drag.start_file_drag(window, [str(tmp_path / "missing")]) is False
    assert calls == []

    # A failed native operation releases the guard for the next user gesture.
    controls.MouseButtons = 1
    def fail(_data, _effect):
        raise RuntimeError("native drag failed")
    window.native.DoDragDrop = fail
    assert windows_file_drag.start_file_drag(window, [str(source)]) is False
    window.native.DoDragDrop = drop
    assert windows_file_drag.start_file_drag(window, [str(source)]) is True


def test_unsupported_host_keeps_web_drag_available(monkeypatch):
    monkeypatch.setattr(windows_file_drag.sys, "platform", "linux")
    assert windows_file_drag.start_file_drag(SimpleNamespace(), ["file.txt"]) is False
