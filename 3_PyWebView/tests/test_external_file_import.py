from __future__ import annotations

from pathlib import Path

import pytest

from app.external_file_import import copy_external_entries_to_directory


def test_copies_files_into_destination_root(tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    destination = tmp_path / "project"
    source_dir.mkdir()
    destination.mkdir()
    first = source_dir / "first.txt"
    second = source_dir / "second.md"
    first.write_text("first", encoding="utf-8")
    second.write_text("second", encoding="utf-8")

    result = copy_external_entries_to_directory(
        [str(first), str(second)],
        str(destination),
    )

    assert result["failures"] == []
    assert [item["name"] for item in result["imported"]] == ["first.txt", "second.md"]
    assert (destination / "first.txt").read_text(encoding="utf-8") == "first"
    assert (destination / "second.md").read_text(encoding="utf-8") == "second"


def test_existing_file_is_not_overwritten(tmp_path: Path) -> None:
    source = tmp_path / "outside" / "report.txt"
    destination = tmp_path / "project"
    source.parent.mkdir()
    destination.mkdir()
    source.write_text("new", encoding="utf-8")
    (destination / "report.txt").write_text("existing", encoding="utf-8")

    result = copy_external_entries_to_directory([str(source)], str(destination))

    assert result["failures"] == []
    assert result["imported"][0]["name"] == "report (1).txt"
    assert (destination / "report.txt").read_text(encoding="utf-8") == "existing"
    assert (destination / "report (1).txt").read_text(encoding="utf-8") == "new"


def test_copies_folder_without_blocking_valid_files(tmp_path: Path) -> None:
    source_folder = tmp_path / "folder"
    source_file = tmp_path / "valid.txt"
    destination = tmp_path / "project"
    source_folder.mkdir()
    (source_folder / "nested.txt").write_text("nested", encoding="utf-8")
    destination.mkdir()
    source_file.write_text("valid", encoding="utf-8")

    result = copy_external_entries_to_directory(
        [str(source_folder), str(source_file)],
        str(destination),
    )

    assert result["failures"] == []
    assert [item["name"] for item in result["imported"]] == ["folder", "valid.txt"]
    assert (destination / "folder" / "nested.txt").read_text(encoding="utf-8") == "nested"


def test_rejects_invalid_destination_root(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="destination_root"):
        copy_external_entries_to_directory([], str(tmp_path / "missing"))


def test_existing_folder_is_not_overwritten(tmp_path: Path) -> None:
    source = tmp_path / "outside" / "assets"
    destination = tmp_path / "project"
    source.mkdir(parents=True)
    destination.mkdir()
    (source / "new.txt").write_text("new", encoding="utf-8")
    (destination / "assets").mkdir()
    (destination / "assets" / "existing.txt").write_text("existing", encoding="utf-8")

    result = copy_external_entries_to_directory([str(source)], str(destination))

    assert result["failures"] == []
    assert result["imported"][0]["name"] == "assets (1)"
    assert (destination / "assets" / "existing.txt").read_text(encoding="utf-8") == "existing"
    assert (destination / "assets (1)" / "new.txt").read_text(encoding="utf-8") == "new"
