from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
import subprocess


_RUNTIME_VERSION_PATTERN = re.compile(r"^py\d+$")
_POWERSHELL_ACL_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$payload = [Console]::In.ReadToEnd() | ConvertFrom-Json
$protected = @()
foreach ($item in @($payload.paths)) {
    if (Test-Path -LiteralPath $item) {
        $acl = Get-Acl -LiteralPath $item
        if ($acl.AreAccessRulesProtected) {
            $protected += $item
        }
    }
}
@{ protected_paths = @($protected) } | ConvertTo-Json -Compress
""".strip()


class PermissionManagementError(RuntimeError):
    def __init__(self, code: str, message: str, details: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


@dataclass(frozen=True, slots=True)
class PermissionRepairResult:
    attempted: bool
    exit_code: int
    stderr: str
    stdout: str
    succeeded: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "attempted": self.attempted,
            "exit_code": self.exit_code,
            "succeeded": self.succeeded,
            "stdout": self.stdout,
            "stderr": self.stderr,
        }


def inspect_protected_paths(
    packages_root: Path,
    paths: tuple[Path, ...],
) -> tuple[Path, ...]:
    root = validate_managed_packages_root(packages_root)
    checked_paths = tuple(_validated_child(root, path) for path in paths)
    if os.name != "nt" or not checked_paths:
        return ()
    powershell = shutil.which("pwsh") or shutil.which("powershell")
    if not powershell:
        raise PermissionManagementError(
            "PERMISSION_INSPECTION_UNAVAILABLE",
            "未找到 PowerShell，无法检查 Windows 目录权限。",
        )
    try:
        completed = subprocess.run(
            [
                powershell,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                _POWERSHELL_ACL_SCRIPT,
            ],
            input=json.dumps(
                {"paths": [str(path) for path in checked_paths]},
                ensure_ascii=False,
            ),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PermissionManagementError(
            "PERMISSION_INSPECTION_FAILED",
            "Windows 目录权限检查无法完成。",
            {"error": str(exc) or exc.__class__.__name__},
        ) from exc
    if completed.returncode != 0:
        raise PermissionManagementError(
            "PERMISSION_INSPECTION_FAILED",
            "Windows 目录权限检查失败。",
            {
                "exit_code": completed.returncode,
                "stderr": _truncate(completed.stderr),
            },
        )
    try:
        payload = json.loads((completed.stdout or "{}").lstrip("\ufeff").strip())
        raw_paths = payload.get("protected_paths", [])
    except (AttributeError, json.JSONDecodeError) as exc:
        raise PermissionManagementError(
            "PERMISSION_INSPECTION_FAILED",
            "Windows 目录权限检查返回了无效结果。",
        ) from exc
    if not isinstance(raw_paths, list):
        raise PermissionManagementError(
            "PERMISSION_INSPECTION_FAILED",
            "Windows 目录权限检查返回了无效路径列表。",
        )
    protected: list[Path] = []
    for raw_path in raw_paths:
        if not isinstance(raw_path, str):
            continue
        protected.append(_validated_child(root, Path(raw_path)))
    return tuple(protected)


def reset_package_permissions(packages_root: Path) -> PermissionRepairResult:
    root = validate_managed_packages_root(packages_root)
    return _reset_permissions(root)


def reset_environment_path_permissions(
    packages_root: Path,
    target_path: Path,
) -> PermissionRepairResult:
    root = validate_managed_packages_root(packages_root)
    target = _validated_child(root, target_path)
    return _reset_permissions(target)


def _reset_permissions(target: Path) -> PermissionRepairResult:
    if os.name != "nt":
        return PermissionRepairResult(
            attempted=False,
            exit_code=0,
            stderr="",
            stdout="",
            succeeded=True,
        )
    icacls = shutil.which("icacls")
    if not icacls:
        return PermissionRepairResult(
            attempted=False,
            exit_code=1,
            stderr="未找到 Windows icacls。",
            stdout="",
            succeeded=False,
        )
    try:
        completed = subprocess.run(
            [icacls, str(target), "/reset", "/T", "/C", "/Q"],
            capture_output=True,
            timeout=300,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return PermissionRepairResult(
            attempted=True,
            exit_code=124,
            stderr=f"Windows 目录权限修复超过 300 秒：{exc}",
            stdout="",
            succeeded=False,
        )
    except OSError as exc:
        return PermissionRepairResult(
            attempted=False,
            exit_code=1,
            stderr=str(exc) or exc.__class__.__name__,
            stdout="",
            succeeded=False,
        )
    stdout = _decode_windows_output(completed.stdout)
    stderr = _decode_windows_output(completed.stderr)
    return PermissionRepairResult(
        attempted=True,
        exit_code=completed.returncode,
        stderr=_truncate(stderr),
        stdout=_truncate(stdout),
        succeeded=completed.returncode == 0,
    )


def validate_managed_packages_root(packages_root: Path) -> Path:
    root = packages_root.resolve(strict=False)
    tool_root = root.parent.parent
    if not (
        _RUNTIME_VERSION_PATTERN.fullmatch(root.name)
        and root.parent.name == "dependencies"
        and tool_root.parent.name == "tools"
        and tool_root.parent.parent.name == "Data"
    ):
        raise PermissionManagementError(
            "UNSAFE_PERMISSION_ROOT",
            "拒绝修改不属于天策工具 Python 依赖区的目录权限。",
            {"packages_root": str(root)},
        )
    return root


def _validated_child(root: Path, path: Path) -> Path:
    resolved = path.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise PermissionManagementError(
            "UNSAFE_PERMISSION_PATH",
            "权限检查路径越出天策用户 Python 依赖区。",
            {"path": str(resolved), "packages_root": str(root)},
        ) from exc
    return resolved


def _decode_windows_output(value: bytes | None) -> str:
    if not value:
        return ""
    for encoding in ("utf-8", "gbk", "mbcs"):
        try:
            return value.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return value.decode("utf-8", errors="replace")


def _truncate(value: str, maximum: int = 4000) -> str:
    if len(value) <= maximum:
        return value
    return value[:maximum] + f"\n...<truncated {len(value) - maximum} chars>"
