from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Literal, TypedDict


class ImportedExternalFile(TypedDict):
    name: str
    path: str
    sourcePath: str


class ExternalFileImportFailure(TypedDict):
    name: str
    reason: Literal["source_missing", "copy_failed"]
    sourcePath: str


class ExternalFileImportResult(TypedDict):
    failures: list[ExternalFileImportFailure]
    imported: list[ImportedExternalFile]


def copy_external_entries_to_directory(
    source_paths: list[str],
    destination_root: str,
) -> ExternalFileImportResult:
    """Copy external files or folders into a destination root without overwriting."""

    destination = _resolve_destination_root(destination_root)
    imported: list[ImportedExternalFile] = []
    failures: list[ExternalFileImportFailure] = []

    for raw_source_path in _deduplicate_source_paths(source_paths):
        source_path = Path(raw_source_path).expanduser()
        display_name = source_path.name or raw_source_path

        if not source_path.exists():
            failures.append(_failure(raw_source_path, display_name, "source_missing"))
            continue
        try:
            copied_path = (
                _copy_file(source_path, destination)
                if source_path.is_file()
                else _copy_directory(source_path, destination)
            )
        except OSError:
            failures.append(_failure(raw_source_path, display_name, "copy_failed"))
            continue

        imported.append(
            {
                "name": copied_path.name,
                "path": copied_path.name,
                "sourcePath": raw_source_path,
            }
        )

    return {"failures": failures, "imported": imported}


def _resolve_destination_root(destination_root: str) -> Path:
    if not isinstance(destination_root, str) or not destination_root.strip():
        raise ValueError("destination_root is required")

    try:
        destination = Path(destination_root).expanduser().resolve(strict=True)
    except OSError as exc:
        raise ValueError("destination_root must be an existing directory") from exc
    if not destination.is_dir():
        raise ValueError("destination_root must be a directory")
    return destination


def _deduplicate_source_paths(source_paths: list[str]) -> list[str]:
    if not isinstance(source_paths, list):
        raise ValueError("source_paths must be a list")

    unique_paths: list[str] = []
    seen: set[str] = set()
    for value in source_paths:
        if not isinstance(value, str) or not value.strip():
            continue
        normalized = str(Path(value).expanduser().absolute())
        key = os.path.normcase(normalized)
        if key in seen:
            continue
        seen.add(key)
        unique_paths.append(normalized)
    return unique_paths


def _reserve_destination_file(destination: Path, source_name: str):
    source = Path(source_name)
    for index in range(10_000):
        candidate_name = source.name if index == 0 else f"{source.stem} ({index}){source.suffix}"
        candidate = destination / candidate_name
        try:
            return candidate, candidate.open("xb")
        except FileExistsError:
            continue
    raise OSError("unable to reserve a unique destination filename")


def _copy_file(source_path: Path, destination: Path) -> Path:
    reserved_path: Path | None = None
    try:
        with source_path.open("rb") as source_stream:
            reserved_path, destination_stream = _reserve_destination_file(
                destination,
                source_path.name,
            )
            with destination_stream:
                shutil.copyfileobj(source_stream, destination_stream)
        try:
            shutil.copystat(source_path, reserved_path)
        except OSError:
            pass
        return reserved_path
    except OSError:
        if reserved_path is not None:
            reserved_path.unlink(missing_ok=True)
        raise


def _copy_directory(source_path: Path, destination: Path) -> Path:
    if source_path.is_symlink():
        raise OSError("symbolic link directories are unsupported")
    source = source_path.resolve(strict=True)
    if _is_within_path(destination, source):
        raise OSError("source directory cannot be copied into itself")
    if any(path.is_symlink() for path in source.rglob("*")):
        raise OSError("source directory contains unsupported symbolic links")

    target = _reserve_destination_directory(destination, source.name)
    try:
        shutil.copytree(source, target, dirs_exist_ok=True, copy_function=shutil.copy2)
    except OSError:
        shutil.rmtree(target, ignore_errors=True)
        raise
    return target


def _reserve_destination_directory(destination: Path, source_name: str) -> Path:
    source = Path(source_name)
    for index in range(10_000):
        candidate_name = source.name if index == 0 else f"{source.name} ({index})"
        candidate = destination / candidate_name
        try:
            candidate.mkdir()
            return candidate
        except FileExistsError:
            continue
    raise OSError("unable to reserve a unique destination directory name")


def _is_within_path(path: Path, ancestor: Path) -> bool:
    try:
        path.resolve(strict=True).relative_to(ancestor)
    except ValueError:
        return False
    return True


def _failure(
    source_path: str,
    name: str,
    reason: Literal["source_missing", "copy_failed"],
) -> ExternalFileImportFailure:
    return {"name": name, "reason": reason, "sourcePath": source_path}
