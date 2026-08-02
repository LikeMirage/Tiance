from __future__ import annotations

import importlib.metadata
import shutil
from dataclasses import dataclass
from pathlib import Path

from package_environment import EnvironmentError
from package_spec import normalize_package_name


@dataclass(frozen=True, slots=True)
class InstalledPackage:
    name: str
    version: str

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "version": self.version}


def list_installed_packages(target_directory: Path) -> tuple[InstalledPackage, ...]:
    if not target_directory.is_dir():
        return ()
    packages: dict[str, InstalledPackage] = {}
    for distribution in importlib.metadata.distributions(path=[str(target_directory)]):
        name = str(distribution.metadata.get("Name") or "").strip()
        version = str(distribution.version or "").strip()
        if not name or not version:
            continue
        packages[normalize_package_name(name)] = InstalledPackage(name=name, version=version)
    return tuple(sorted(packages.values(), key=lambda item: item.name.lower()))


def select_installed_packages(
    packages: tuple[InstalledPackage, ...],
    names: tuple[str, ...],
) -> tuple[tuple[InstalledPackage, ...], tuple[str, ...]]:
    by_name = {normalize_package_name(package.name): package for package in packages}
    found: list[InstalledPackage] = []
    missing: list[str] = []
    for name in names:
        package = by_name.get(normalize_package_name(name))
        if package is None:
            missing.append(name)
        else:
            found.append(package)
    return tuple(found), tuple(missing)


def uninstall_packages(target_directory: Path, names: tuple[str, ...]) -> tuple[str, ...]:
    distributions = {
        normalize_package_name(str(distribution.metadata.get("Name") or "")): distribution
        for distribution in importlib.metadata.distributions(path=[str(target_directory)])
        if str(distribution.metadata.get("Name") or "").strip()
    }
    removed: list[str] = []
    for requested_name in names:
        distribution = distributions.get(normalize_package_name(requested_name))
        if distribution is None:
            continue
        files = distribution.files
        if files is None:
            raise EnvironmentError(
                "DISTRIBUTION_RECORD_MISSING",
                f"包 '{requested_name}' 缺少卸载文件记录，为避免误删已停止。",
            )
        _remove_distribution_files(target_directory, tuple(files))
        removed.append(str(distribution.metadata.get("Name") or requested_name))
    return tuple(removed)


def _remove_distribution_files(target_directory: Path, files: tuple[object, ...]) -> None:
    root = target_directory.resolve()
    parent_candidates: set[Path] = set()
    for distribution_file in files:
        path = (target_directory / str(distribution_file)).resolve()
        if not _is_relative_to(path, root):
            continue
        parent_candidates.add(path.parent)
        if path.is_file() or path.is_symlink():
            path.unlink(missing_ok=True)
        elif path.is_dir():
            shutil.rmtree(path)
    for parent in sorted(parent_candidates, key=lambda item: len(item.parts), reverse=True):
        _remove_empty_parents(parent, root)


def _remove_empty_parents(path: Path, root: Path) -> None:
    current = path
    while current != root and _is_relative_to(current, root):
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
