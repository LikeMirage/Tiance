from pathlib import Path

import pytest

from app.core.errors import BadRequestError
from app.services import desktop_local_path as local_path_module
from app.services.desktop_local_path import DesktopLocalPathService


def test_reveal_requires_an_existing_absolute_path(tmp_path, monkeypatch):
    target = tmp_path / "example.txt"
    target.write_text("ok", encoding="utf-8")
    received: list[Path] = []
    monkeypatch.setattr(
        local_path_module,
        "reveal_path_in_file_explorer",
        lambda path: received.append(path),
    )

    DesktopLocalPathService().reveal(str(target))

    assert received == [target.resolve()]


def test_open_default_rejects_relative_paths():
    with pytest.raises(BadRequestError, match="只接受绝对路径"):
        DesktopLocalPathService().open_default("docs/example.md")


def test_reveal_rejects_missing_paths(tmp_path):
    with pytest.raises(BadRequestError, match="不存在"):
        DesktopLocalPathService().reveal(str(tmp_path / "missing.txt"))
