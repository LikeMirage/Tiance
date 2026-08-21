from pathlib import Path

import pytest

from app.core.errors import AppError, ConflictError
from app.infra.file_workspace import file_storage as file_storage_module
from app.infra.file_workspace import FileWorkspaceStorage, TextFileReadLimitExceededError
from app.services import file_workspace_text


def test_file_workspace_storage_rejects_path_escape(tmp_path):
    storage = FileWorkspaceStorage()

    with pytest.raises(ValueError):
        storage.list_tree(str(tmp_path), parent_path="../outside")


def test_file_workspace_storage_writes_inside_controlled_root(tmp_path):
    storage = FileWorkspaceStorage()

    node = storage.create_entry(
        str(tmp_path),
        parent_path=None,
        kind="file",
        name="tool.py",
    )
    saved = storage.write_text_file(str(tmp_path), node.path, "print('ok')")

    assert node.path == "tool.py"
    assert saved.path == "tool.py"
    assert isinstance(saved.mtime_ms, int)
    assert (tmp_path / "tool.py").read_text(encoding="utf-8") == "print('ok')"


def test_file_workspace_storage_reports_delete_conflict(tmp_path, monkeypatch):
    storage = FileWorkspaceStorage()
    target = tmp_path / "locked.docx"
    target.write_text("locked", encoding="utf-8")

    def raise_file_in_use(_path: Path) -> None:
        raise PermissionError("file is in use")

    monkeypatch.setattr(file_storage_module, "_remove_file", raise_file_in_use)

    with pytest.raises(ConflictError) as exc_info:
        storage.delete_entry(str(tmp_path), target.name)

    assert exc_info.value.status_code == 409
    assert exc_info.value.details == {"reason": "entry_in_use_or_access_denied"}
    assert target.is_file()


def test_file_workspace_storage_reads_large_text_files(tmp_path):
    storage = FileWorkspaceStorage()
    target = tmp_path / "large.jsonl"
    content = "a" * (3 * 1024 * 1024)
    target.write_text(content, encoding="utf-8")

    loaded, mtime_ms = storage.read_text_file(str(tmp_path), "large.jsonl")

    assert loaded == content
    assert isinstance(mtime_ms, int)


def test_file_workspace_storage_rejects_text_over_explicit_read_limit(tmp_path):
    storage = FileWorkspaceStorage()
    target = tmp_path / "oversized.txt"
    target.write_text("0123456789", encoding="utf-8")

    with pytest.raises(TextFileReadLimitExceededError) as exc_info:
        storage.read_text_file_limited(
            str(tmp_path),
            target.name,
            max_size_bytes=9,
        )

    assert exc_info.value.size_bytes == 10
    assert exc_info.value.limit_bytes == 9


def test_editor_text_read_limit_returns_explicit_api_error(tmp_path, monkeypatch):
    storage = FileWorkspaceStorage()
    target = tmp_path / "oversized.txt"
    target.write_text("0123456789", encoding="utf-8")
    monkeypatch.setattr(file_workspace_text, "MAX_EDITOR_TEXT_FILE_SIZE_BYTES", 9)

    with pytest.raises(AppError) as exc_info:
        file_workspace_text.read_editor_text_file(storage, str(tmp_path), target.name)

    assert exc_info.value.status_code == 413
    assert exc_info.value.code == "editor_text_file_too_large"
    assert exc_info.value.details == {"size_bytes": 10, "limit_bytes": 9}


def test_file_workspace_storage_ignores_internal_temp_files_for_children(tmp_path):
    storage = FileWorkspaceStorage()
    folder = tmp_path / "notes"
    folder.mkdir()
    (folder / ".draft.0123456789abcdef0123456789abcdef.tmp").write_text(
        "half-written",
        encoding="utf-8",
    )

    [node] = storage.list_tree(str(tmp_path))

    assert node.path == "notes"
    assert node.has_children is False


def test_file_workspace_storage_search_skips_heavy_directories(tmp_path):
    storage = FileWorkspaceStorage()
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "target.txt").write_text("skip", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "target.txt").write_text("keep", encoding="utf-8")

    tree = storage.list_tree_result(str(tmp_path), query="target")

    assert [node.path for node in tree.items] == ["src"]
    assert [child.path for child in tree.items[0].children] == ["src/target.txt"]


def test_file_workspace_storage_search_returns_all_matches(tmp_path):
    storage = FileWorkspaceStorage()
    for index in range(350):
        (tmp_path / f"match-{index}.txt").write_text("ok", encoding="utf-8")

    tree = storage.list_tree_result(str(tmp_path), query="match")

    assert len(tree.items) == 350


def test_file_workspace_storage_lists_file_mtime_for_external_change_detection(tmp_path):
    storage = FileWorkspaceStorage()
    target = tmp_path / "report.docx"
    target.write_bytes(b"document")

    [listed] = storage.list_tree(str(tmp_path))
    searched = storage.list_tree_result(str(tmp_path), query="report").items[0]

    assert isinstance(listed.mtime_ms, int)
    assert searched.mtime_ms == listed.mtime_ms
