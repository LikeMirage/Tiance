from pathlib import Path

import pytest

from app.core import atomic_replace


def _windows_permission_error(winerror: int) -> PermissionError:
    error = PermissionError("文件暂时被占用")
    error.winerror = winerror
    return error


def test_atomic_replace_retries_transient_windows_file_occupation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "source.tmp"
    target_path = tmp_path / "target.json"
    source_path.write_text('{"new":true}', encoding="utf-8")
    target_path.write_text('{"old":true}', encoding="utf-8")
    real_replace = atomic_replace.os.replace
    replace_attempts = 0
    retry_delays: list[float] = []

    def replace_after_temporary_occupation(source: Path, target: Path) -> None:
        nonlocal replace_attempts
        replace_attempts += 1
        if replace_attempts <= 2:
            raise _windows_permission_error(32)
        real_replace(source, target)

    monkeypatch.setattr(
        atomic_replace.os,
        "replace",
        replace_after_temporary_occupation,
    )
    monkeypatch.setattr(atomic_replace, "sleep", retry_delays.append)

    atomic_replace.atomic_replace_path(source_path, target_path)

    assert target_path.read_text(encoding="utf-8") == '{"new":true}'
    assert replace_attempts == 3
    assert retry_delays == [0.03, 0.06]
    assert not source_path.exists()


def test_atomic_replace_stops_after_bounded_retries(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "source.tmp"
    target_path = tmp_path / "target.json"
    source_path.write_text('{"new":true}', encoding="utf-8")
    target_path.write_text('{"old":true}', encoding="utf-8")
    replace_attempts = 0
    retry_delays: list[float] = []

    def always_occupied(_source: Path, _target: Path) -> None:
        nonlocal replace_attempts
        replace_attempts += 1
        raise _windows_permission_error(5)

    monkeypatch.setattr(atomic_replace.os, "replace", always_occupied)
    monkeypatch.setattr(atomic_replace, "sleep", retry_delays.append)

    with pytest.raises(PermissionError):
        atomic_replace.atomic_replace_path(source_path, target_path)

    assert target_path.read_text(encoding="utf-8") == '{"old":true}'
    assert replace_attempts == 6
    assert retry_delays == [0.03, 0.06, 0.12, 0.24, 0.48]
    assert source_path.exists()


def test_atomic_replace_does_not_retry_unrelated_permission_errors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "source.tmp"
    target_path = tmp_path / "target.json"
    source_path.write_text('{"new":true}', encoding="utf-8")
    retry_delays: list[float] = []

    def reject_replace(_source: Path, _target: Path) -> None:
        raise _windows_permission_error(13)

    monkeypatch.setattr(atomic_replace.os, "replace", reject_replace)
    monkeypatch.setattr(atomic_replace, "sleep", retry_delays.append)

    with pytest.raises(PermissionError):
        atomic_replace.atomic_replace_path(source_path, target_path)

    assert retry_delays == []
    assert source_path.exists()
