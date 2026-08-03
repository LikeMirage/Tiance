from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import time
import uuid

from package_environment import (
    ACTIVE_ENVIRONMENT_FILE,
    ACTIVE_ENVIRONMENT_SCHEMA_VERSION,
    ENVIRONMENTS_DIRECTORY,
    LEASES_DIRECTORY,
    LEASE_STALE_SECONDS,
    OBSOLETE_ENVIRONMENT_GRACE_SECONDS,
    EnvironmentError,
    resolve_active_site_packages,
)
from windows_permissions import (
    PermissionManagementError,
    inspect_protected_paths,
    reset_environment_path_permissions,
    reset_package_permissions,
)


class CandidateEnvironment:
    def __init__(
        self,
        packages_root: Path,
        *,
        auto_repair_permissions: bool = True,
    ) -> None:
        self._packages_root = packages_root
        self._auto_repair_permissions = auto_repair_permissions
        self._working_root: Path | None = None
        self.path: Path | None = None
        self._committed = False
        self.preparation_warnings: list[str] = []

    def __enter__(self) -> "CandidateEnvironment":
        try:
            self._create_working_environment()
        except (OSError, shutil.Error) as exc:
            self._discard_working_environment()
            if not self._auto_repair_permissions:
                raise _clone_environment_error(exc) from exc
            repair = reset_package_permissions(self._packages_root)
            if not repair.succeeded:
                raise EnvironmentError(
                    "ENVIRONMENT_PERMISSION_REPAIR_FAILED",
                    "工具依赖环境权限异常，自动修复失败。",
                    {
                        "requires_elevation": True,
                        "permission_repair": repair.to_dict(),
                    },
                ) from exc
            removed_candidates, failed_candidates = _cleanup_failed_candidates(
                self._packages_root
            )
            self.preparation_warnings.append(
                "检测到工具依赖环境权限异常，已自动恢复目录权限。"
            )
            if removed_candidates:
                self.preparation_warnings.append(
                    f"已清理 {removed_candidates} 个失败候选环境。"
                )
            if failed_candidates:
                self.preparation_warnings.append(
                    f"仍有 {failed_candidates} 个失败候选环境暂时无法清理。"
                )
            try:
                self._create_working_environment()
            except (OSError, shutil.Error) as retry_exc:
                self._discard_working_environment()
                raise _clone_environment_error(retry_exc) from retry_exc
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        if not self._committed and self._working_root is not None:
            self._discard_working_environment()
        self._working_root = None
        self.path = None

    def commit(self) -> list[str]:
        if self.path is None or self._working_root is None:
            raise RuntimeError("候选环境尚未创建。")
        protected_paths = self._protected_candidate_paths()
        if protected_paths:
            self._normalize_candidate_permissions(protected_paths)

        generation_root = self._working_root.with_name(f"env-{uuid.uuid4().hex}")
        os.replace(self._working_root, generation_root)
        generation_site_packages = generation_root / "site-packages"
        try:
            _write_active_environment(
                self._packages_root,
                generation_site_packages,
            )
        except Exception:
            shutil.rmtree(generation_root, ignore_errors=True)
            raise
        self._committed = True
        self._working_root = None
        self.path = generation_site_packages
        return _cleanup_obsolete_environments(
            self._packages_root,
            active_generation=generation_root,
        )

    def _create_working_environment(self) -> None:
        environments_root = self._packages_root / ENVIRONMENTS_DIRECTORY
        environments_root.mkdir(parents=True, exist_ok=True)
        self._working_root = environments_root / f".candidate-{uuid.uuid4().hex}"
        self._working_root.mkdir()
        self.path = self._working_root / "site-packages"
        active_directory = resolve_active_site_packages(self._packages_root)
        if active_directory.is_dir():
            shutil.copytree(active_directory, self.path)
        else:
            self.path.mkdir(parents=True)

    def _normalize_candidate_permissions(
        self,
        protected_paths: tuple[Path, ...],
    ) -> None:
        assert self._working_root is not None
        permission_result = reset_environment_path_permissions(
            self._packages_root,
            self._working_root,
        )
        if not permission_result.succeeded:
            raise EnvironmentError(
                "CANDIDATE_PERMISSION_NORMALIZATION_FAILED",
                "无法统一新依赖环境的目录权限。",
                {
                    "requires_elevation": True,
                    "permission_repair": permission_result.to_dict(),
                },
            )
        remaining_protected = self._protected_candidate_paths()
        if remaining_protected:
            raise EnvironmentError(
                "CANDIDATE_PERMISSION_NORMALIZATION_FAILED",
                "新依赖环境仍存在未恢复的目录权限。",
                {
                    "requires_elevation": True,
                    "protected_paths": [
                        str(path) for path in remaining_protected
                    ],
                },
            )
        self.preparation_warnings.append(
            f"已恢复新依赖环境中 {len(protected_paths)} 个路径的继承权限。"
        )

    def _protected_candidate_paths(self) -> tuple[Path, ...]:
        assert self._working_root is not None
        assert self.path is not None
        try:
            check_paths = (
                self._working_root,
                self.path,
                *tuple(self.path.iterdir()),
            )
            return inspect_protected_paths(
                self._packages_root,
                check_paths,
            )
        except (OSError, PermissionManagementError) as exc:
            raise EnvironmentError(
                "CANDIDATE_PERMISSION_INSPECTION_FAILED",
                "无法检查新依赖环境的目录权限。",
                {"error": str(exc) or exc.__class__.__name__},
            ) from exc

    def _discard_working_environment(self) -> None:
        working_root = self._working_root
        if working_root is not None:
            shutil.rmtree(working_root, ignore_errors=True)
        self._working_root = None
        self.path = None


def _clone_environment_error(exc: BaseException) -> EnvironmentError:
    details: dict[str, object] = {"error": str(exc) or exc.__class__.__name__}
    if isinstance(exc, shutil.Error) and exc.args and isinstance(exc.args[0], list):
        details["copy_errors"] = [
            {
                "source": str(item[0]),
                "target": str(item[1]),
                "error": str(item[2]),
            }
            for item in exc.args[0]
            if isinstance(item, tuple) and len(item) == 3
        ]
    return EnvironmentError(
        "ENVIRONMENT_CLONE_FAILED",
        "无法复制当前工具依赖环境。",
        details,
    )


def _write_active_environment(packages_root: Path, site_packages: Path) -> None:
    root = packages_root.resolve()
    target = site_packages.resolve()
    try:
        relative_target = target.relative_to(root)
    except ValueError as exc:
        raise EnvironmentError(
            "ACTIVE_ENVIRONMENT_INVALID",
            "候选依赖环境越出存储目录。",
        ) from exc
    payload = {
        "schema_version": ACTIVE_ENVIRONMENT_SCHEMA_VERSION,
        "site_packages": relative_target.as_posix(),
    }
    pointer_file = root / ACTIVE_ENVIRONMENT_FILE
    temporary_file = root / f".{ACTIVE_ENVIRONMENT_FILE}.{uuid.uuid4().hex}.tmp"
    try:
        temporary_file.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary_file, pointer_file)
    finally:
        temporary_file.unlink(missing_ok=True)


def _cleanup_obsolete_environments(
    packages_root: Path,
    *,
    active_generation: Path,
) -> list[str]:
    environments_root = packages_root / ENVIRONMENTS_DIRECTORY
    warnings: list[str] = []
    if _has_active_runtime_leases(packages_root):
        return warnings
    try:
        candidates = tuple(environments_root.iterdir())
    except OSError:
        return [f"旧依赖环境暂时无法扫描，将在后续操作中清理：{environments_root}"]
    candidate_cutoff = time.time() - OBSOLETE_ENVIRONMENT_GRACE_SECONDS
    for candidate in candidates:
        if candidate == active_generation or not candidate.is_dir():
            continue
        if not (candidate.name.startswith("env-") or candidate.name.startswith(".candidate-")):
            continue
        try:
            if candidate.name.startswith(".candidate-") and candidate.stat().st_mtime > candidate_cutoff:
                continue
            shutil.rmtree(candidate)
        except OSError:
            warnings.append(f"旧依赖环境暂时被占用，将在后续操作中清理：{candidate}")
    return warnings


def _cleanup_failed_candidates(packages_root: Path) -> tuple[int, int]:
    environments_root = packages_root / ENVIRONMENTS_DIRECTORY
    removed = 0
    failed = 0
    try:
        candidates = tuple(environments_root.iterdir())
    except OSError:
        return removed, failed
    for candidate in candidates:
        if not candidate.is_dir() or not candidate.name.startswith(".candidate-"):
            continue
        try:
            shutil.rmtree(candidate)
            removed += 1
        except OSError:
            failed += 1
    return removed, failed


def _has_active_runtime_leases(packages_root: Path) -> bool:
    leases_root = packages_root / LEASES_DIRECTORY
    if not leases_root.is_dir():
        return False
    cutoff = time.time() - LEASE_STALE_SECONDS
    has_active_lease = False
    try:
        leases = tuple(leases_root.iterdir())
    except OSError:
        return True
    for lease in leases:
        if not lease.is_file():
            continue
        try:
            if lease.stat().st_mtime < cutoff:
                lease.unlink(missing_ok=True)
            else:
                has_active_lease = True
        except OSError:
            has_active_lease = True
    return has_active_lease
