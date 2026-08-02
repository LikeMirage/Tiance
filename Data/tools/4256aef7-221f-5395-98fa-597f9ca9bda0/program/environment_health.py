from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import time

from candidate_environment import CandidateEnvironment
from package_environment import (
    EnvironmentError,
    ENVIRONMENTS_DIRECTORY,
    LEASES_DIRECTORY,
    LEASE_STALE_SECONDS,
    resolve_active_site_packages,
)
from windows_permissions import (
    PermissionManagementError,
    PermissionRepairResult,
    inspect_protected_paths,
    reset_user_package_permissions,
    validate_user_packages_root,
)


@dataclass(frozen=True, slots=True)
class EnvironmentHealthReport:
    active_lease_count: int
    active_site_packages: Path
    candidate_directories: tuple[Path, ...]
    clone_probe_succeeded: bool
    healthy: bool
    issues: tuple[dict[str, object], ...]
    protected_paths: tuple[Path, ...]
    stale_lease_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "healthy": self.healthy,
            "active_site_packages": str(self.active_site_packages),
            "clone_probe_succeeded": self.clone_probe_succeeded,
            "protected_path_count": len(self.protected_paths),
            "protected_paths": [str(path) for path in self.protected_paths],
            "candidate_directory_count": len(self.candidate_directories),
            "candidate_directories": [
                str(path) for path in self.candidate_directories
            ],
            "active_lease_count": self.active_lease_count,
            "stale_lease_count": self.stale_lease_count,
            "issues": list(self.issues),
        }


@dataclass(frozen=True, slots=True)
class EnvironmentRepairReport:
    cleanup_failures: tuple[Path, ...]
    health: EnvironmentHealthReport
    permission_result: PermissionRepairResult
    removed_candidate_directories: tuple[Path, ...]
    removed_stale_leases: tuple[Path, ...]
    requires_elevation: bool

    @property
    def succeeded(self) -> bool:
        return self.permission_result.succeeded and self.health.healthy

    def to_dict(self) -> dict[str, object]:
        return {
            "succeeded": self.succeeded,
            "requires_elevation": self.requires_elevation,
            "permission_repair": self.permission_result.to_dict(),
            "removed_candidate_directory_count": len(
                self.removed_candidate_directories
            ),
            "removed_candidate_directories": [
                str(path) for path in self.removed_candidate_directories
            ],
            "removed_stale_lease_count": len(self.removed_stale_leases),
            "removed_stale_leases": [
                str(path) for path in self.removed_stale_leases
            ],
            "cleanup_failure_count": len(self.cleanup_failures),
            "cleanup_failures": [str(path) for path in self.cleanup_failures],
            "health": self.health.to_dict(),
        }


def inspect_environment(user_packages_root: Path) -> EnvironmentHealthReport:
    root = validate_user_packages_root(user_packages_root)
    active_site_packages = resolve_active_site_packages(root)
    active_leases, stale_leases = _lease_counts(root)
    issues: list[dict[str, object]] = []

    try:
        protected_paths = inspect_protected_paths(
            root,
            _permission_check_paths(root, active_site_packages),
        )
    except PermissionManagementError as exc:
        protected_paths = ()
        issues.append(
            {"code": exc.code, "message": exc.message, "details": exc.details}
        )
    if protected_paths:
        issues.append(
            {
                "code": "PROTECTED_WINDOWS_ACL",
                "message": "用户依赖环境中存在未继承父目录权限的路径。",
                "paths": [str(path) for path in protected_paths],
            }
        )

    clone_probe_succeeded = False
    try:
        with CandidateEnvironment(root, auto_repair_permissions=False):
            clone_probe_succeeded = True
    except EnvironmentError as exc:
        issues.append(
            {"code": exc.code, "message": exc.message, "details": exc.details}
        )

    candidates = _candidate_directories(root)
    if candidates:
        issues.append(
            {
                "code": "FAILED_CANDIDATE_RESIDUE",
                "message": "用户依赖环境中存在未清理的失败候选目录。",
                "paths": [str(path) for path in candidates],
            }
        )
    if stale_leases:
        issues.append(
            {
                "code": "STALE_RUNTIME_LEASES",
                "message": "用户依赖环境中存在过期的运行标记。",
                "count": stale_leases,
            }
        )
    healthy = not issues and clone_probe_succeeded
    return EnvironmentHealthReport(
        active_lease_count=active_leases,
        active_site_packages=active_site_packages,
        candidate_directories=candidates,
        clone_probe_succeeded=clone_probe_succeeded,
        healthy=healthy,
        issues=tuple(issues),
        protected_paths=protected_paths,
        stale_lease_count=stale_leases,
    )


def repair_environment(user_packages_root: Path) -> EnvironmentRepairReport:
    root = validate_user_packages_root(user_packages_root)
    permission_result = reset_user_package_permissions(root)
    removed_candidates, cleanup_failures = _cleanup_candidate_directories(root)
    removed_stale_leases = _cleanup_stale_leases(root)
    health = inspect_environment(root)
    return EnvironmentRepairReport(
        cleanup_failures=cleanup_failures,
        health=health,
        permission_result=permission_result,
        removed_candidate_directories=removed_candidates,
        removed_stale_leases=removed_stale_leases,
        requires_elevation=(
            os.name == "nt"
            and (not permission_result.succeeded or bool(health.protected_paths))
        ),
    )


def _permission_check_paths(
    root: Path,
    active_site_packages: Path,
) -> tuple[Path, ...]:
    paths = [root, root / ENVIRONMENTS_DIRECTORY, active_site_packages]
    try:
        paths.extend(active_site_packages.iterdir())
    except OSError:
        pass
    return tuple(dict.fromkeys(paths))


def _candidate_directories(root: Path) -> tuple[Path, ...]:
    environments_root = root / ENVIRONMENTS_DIRECTORY
    try:
        candidates = tuple(
            path
            for path in environments_root.iterdir()
            if path.is_dir() and path.name.startswith(".candidate-")
        )
    except OSError:
        return ()
    return tuple(sorted(candidates, key=lambda path: path.name))


def _cleanup_candidate_directories(
    root: Path,
) -> tuple[tuple[Path, ...], tuple[Path, ...]]:
    removed: list[Path] = []
    failed: list[Path] = []
    for candidate in _candidate_directories(root):
        try:
            shutil.rmtree(candidate)
            removed.append(candidate)
        except OSError:
            failed.append(candidate)
    return tuple(removed), tuple(failed)


def _lease_counts(root: Path) -> tuple[int, int]:
    cutoff = time.time() - LEASE_STALE_SECONDS
    active = 0
    stale = 0
    try:
        leases = tuple((root / LEASES_DIRECTORY).iterdir())
    except OSError:
        return active, stale
    for lease in leases:
        if not lease.is_file():
            continue
        try:
            if lease.stat().st_mtime < cutoff:
                stale += 1
            else:
                active += 1
        except OSError:
            active += 1
    return active, stale


def _cleanup_stale_leases(root: Path) -> tuple[Path, ...]:
    cutoff = time.time() - LEASE_STALE_SECONDS
    removed: list[Path] = []
    try:
        leases = tuple((root / LEASES_DIRECTORY).iterdir())
    except OSError:
        return ()
    for lease in leases:
        try:
            if lease.is_file() and lease.stat().st_mtime < cutoff:
                lease.unlink()
                removed.append(lease)
        except OSError:
            continue
    return tuple(removed)
