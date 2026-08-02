from __future__ import annotations

import ctypes

from app.windows_clipboard import _DropFiles, _build_drop_files_data


def test_build_drop_files_data_uses_unicode_file_list() -> None:
    paths = [r"C:\项目\报告.docx", r"C:\项目\素材"]

    payload = _build_drop_files_data(paths)

    header_size = ctypes.sizeof(_DropFiles)
    header = _DropFiles.from_buffer_copy(payload[:header_size])
    assert header.pFiles == header_size
    assert header.fWide
    assert payload[header_size:].decode("utf-16-le") == "\0".join(paths) + "\0\0"
