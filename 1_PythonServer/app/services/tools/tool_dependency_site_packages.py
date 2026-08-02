from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil

from app.services.tools.tool_dependency_requirements import normalize_package_name


@dataclass(frozen=True, slots=True)
class InstalledDistribution:
    name: str
    version: str
    dist_info_path: Path
    files: tuple[str, ...]


def read_installed_versions(site_packages_path: Path) -> dict[str, str]:
    return {
        normalize_package_name(distribution.name): distribution.version
        for distribution in _iter_installed_distributions(site_packages_path)
    }


def remove_installed_distribution(site_packages_path: Path, package_name: str) -> bool:
    site_packages_root = site_packages_path.resolve()
    distributions = _find_distributions(site_packages_path, package_name)
    if not distributions:
        return False

    paths_to_remove: set[Path] = set()
    for distribution in distributions:
        for package_file in distribution.files:
            file_path = (site_packages_path / package_file).resolve()
            if is_relative_to(file_path, site_packages_root):
                paths_to_remove.add(file_path)

        dist_info_path = distribution.dist_info_path.resolve()
        if is_relative_to(dist_info_path, site_packages_root):
            paths_to_remove.add(dist_info_path)

    removed_any = False
    parent_candidates: set[Path] = set()
    for path in sorted(paths_to_remove, key=lambda item: len(item.parts), reverse=True):
        if not is_relative_to(path, site_packages_root):
            continue
        parent_candidates.add(path.parent)
        if path.is_dir():
            shutil.rmtree(path)
            removed_any = True
        elif path.exists():
            path.unlink()
            removed_any = True

    for path in sorted(parent_candidates, key=lambda item: len(item.parts), reverse=True):
        _remove_empty_parents(path, site_packages_root)

    return removed_any


def is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _find_distributions(
    site_packages_path: Path,
    package_name: str,
) -> tuple[InstalledDistribution, ...]:
    normalized_package_name = normalize_package_name(package_name)
    return tuple(
        distribution
        for distribution in _iter_installed_distributions(site_packages_path)
        if normalize_package_name(distribution.name) == normalized_package_name
    )


def _iter_installed_distributions(site_packages_path: Path) -> tuple[InstalledDistribution, ...]:
    if not site_packages_path.is_dir():
        return ()

    distributions: list[InstalledDistribution] = []
    for dist_info_path in sorted(site_packages_path.glob("*.dist-info")):
        if not dist_info_path.is_dir():
            continue
        metadata = _read_distribution_metadata(dist_info_path / "METADATA")
        name = metadata.get("name")
        version = metadata.get("version")
        if not name or not version:
            raise ValueError(f"Distribution metadata is incomplete: {dist_info_path}")
        distributions.append(
            InstalledDistribution(
                name=name,
                version=version,
                dist_info_path=dist_info_path,
                files=_read_distribution_record_paths(dist_info_path),
            )
        )
    return tuple(distributions)


def _read_distribution_metadata(metadata_path: Path) -> dict[str, str]:
    if not metadata_path.is_file():
        raise ValueError(f"Distribution metadata is missing: {metadata_path}")

    metadata: dict[str, str] = {}
    for line in metadata_path.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition(":")
        if not separator:
            continue
        normalized_key = key.strip().lower()
        if normalized_key in {"name", "version"}:
            metadata[normalized_key] = value.strip()
    return metadata


def _read_distribution_record_paths(dist_info_path: Path) -> tuple[str, ...]:
    record_path = dist_info_path / "RECORD"
    if not record_path.is_file():
        raise ValueError(f"Distribution RECORD is missing: {record_path}")

    paths: list[str] = []
    for line in record_path.read_text(encoding="utf-8").splitlines():
        raw_path = line.split(",", 1)[0].strip()
        if raw_path:
            paths.append(raw_path.replace("\\", "/"))
    return tuple(paths)


def _remove_empty_parents(path: Path, root: Path) -> None:
    current = path.resolve()
    while current != root and is_relative_to(current, root):
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent
