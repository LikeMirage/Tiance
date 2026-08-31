from pathlib import Path

import pytest

from app.core.errors import BadRequestError, NotFoundError
from app.services.application.server_directory_browser import ServerDirectoryBrowserService


def test_list_directories_returns_only_immediate_folders(tmp_path: Path) -> None:
    (tmp_path / "beta").mkdir()
    (tmp_path / "Alpha").mkdir()
    (tmp_path / "note.txt").write_text("not a directory", encoding="utf-8")

    listing = ServerDirectoryBrowserService().list_directories(str(tmp_path))

    assert listing["path"] == str(tmp_path.resolve())
    assert listing["parent_path"] == str(tmp_path.resolve().parent)
    assert [item["name"] for item in listing["directories"]] == ["Alpha", "beta"]


def test_list_directories_rejects_missing_path(tmp_path: Path) -> None:
    with pytest.raises(NotFoundError):
        ServerDirectoryBrowserService().list_directories(str(tmp_path / "missing"))


def test_list_directories_rejects_relative_path() -> None:
    with pytest.raises(BadRequestError):
        ServerDirectoryBrowserService().list_directories("relative/folder")
