from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
import shutil

from package_environment import (
    EnvironmentError,
    RuntimePaths,
    resolve_active_site_packages,
)
from package_spec import PackageRequest, parse_install_requirement


DEFAULT_TOOL_TARGET = "run_python_script"
PYTHON_SCRIPT_TOOL_ID = "run_python_script"
DEPENDENCY_ROOT = Path("dependencies") / "py313"
REQUIREMENTS_FILE = Path("program") / "requirements.txt"


@dataclass(frozen=True, slots=True)
class PackageTarget:
    display_name: str
    environment_root: Path | None
    identifier: str
    kind: str
    requirements_path: Path | None
    tool_root: Path | None
    warnings: tuple[str, ...] = ()

    @property
    def target_directory(self) -> Path:
        if self.environment_root is None:
            return Path(self.identifier)
        return resolve_active_site_packages(self.environment_root)

    @property
    def is_managed(self) -> bool:
        return self.environment_root is not None


def resolve_package_target(
    request: PackageRequest,
    runtime_paths: RuntimePaths,
) -> PackageTarget:
    if request.target_path is not None:
        return _resolve_path_target(request.target_path)
    return _resolve_tool_target(
        request.target_tool or DEFAULT_TOOL_TARGET,
        runtime_paths,
    )


def read_target_requirements(target: PackageTarget) -> tuple[str, ...]:
    requirements_path = target.requirements_path
    if requirements_path is None:
        raise EnvironmentError(
            "TOOL_TARGET_REQUIRED",
            "当前目标没有工具依赖声明文件。",
        )
    if not requirements_path.is_file():
        return ()
    try:
        lines = requirements_path.read_text(encoding="utf-8-sig").splitlines()
    except OSError as exc:
        raise EnvironmentError(
            "REQUIREMENTS_READ_FAILED",
            "无法读取工具 requirements.txt。",
            {"requirements_path": str(requirements_path)},
        ) from exc
    requirements: list[str] = []
    for line_number, raw_line in enumerate(lines, start=1):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            requirements.append(parse_install_requirement(stripped))
        except Exception as exc:
            raise EnvironmentError(
                "INVALID_REQUIREMENTS_FILE",
                "工具 requirements.txt 包含不支持的依赖格式。",
                {
                    "requirements_path": str(requirements_path),
                    "line": line_number,
                    "value": stripped,
                },
            ) from exc
    if len(requirements) > 100:
        raise EnvironmentError(
            "TOO_MANY_REQUIREMENTS",
            "单个工具最多声明 100 个 Python 依赖。",
            {"requirements_path": str(requirements_path)},
        )
    return tuple(requirements)


def _resolve_path_target(raw_path: str) -> PackageTarget:
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    resolved = path.resolve(strict=False)
    if resolved.exists() and not resolved.is_dir():
        raise EnvironmentError(
            "TARGET_NOT_DIRECTORY",
            "target_path 必须指向目录。",
            {"target_path": str(resolved)},
        )
    return PackageTarget(
        display_name=str(resolved),
        environment_root=None,
        identifier=str(resolved),
        kind="path",
        requirements_path=None,
        tool_root=None,
    )


def _resolve_tool_target(identifier: str, runtime_paths: RuntimePaths) -> PackageTarget:
    tools_root = runtime_paths.tools_root.resolve()
    if not tools_root.is_dir():
        raise EnvironmentError(
            "TOOLS_ROOT_NOT_FOUND",
            "天策工具数据目录不存在。",
            {"tools_root": str(tools_root)},
        )
    normalized = identifier.casefold()
    matches: list[tuple[Path, dict[str, object], dict[str, object]]] = []
    for tool_root in tools_root.iterdir():
        if not tool_root.is_dir():
            continue
        tool_manifest = _read_json_object(tool_root / ".tool" / "tool.json")
        market_manifest = _read_json_object(tool_root / "manifest.json")
        identities = {
            tool_root.name,
            str(tool_manifest.get("name") or ""),
            str(tool_manifest.get("display_name") or ""),
            str(market_manifest.get("id") or ""),
        }
        if normalized in {value.casefold() for value in identities if value}:
            matches.append((tool_root.resolve(), tool_manifest, market_manifest))
    if not matches:
        raise EnvironmentError(
            "TOOL_NOT_FOUND",
            "没有找到指定工具。",
            {"target_tool": identifier},
        )
    if len(matches) > 1:
        raise EnvironmentError(
            "AMBIGUOUS_TOOL",
            "工具名称匹配到多个项目，请改用工具文件夹 ID。",
            {
                "target_tool": identifier,
                "matches": [item[0].name for item in matches],
            },
        )
    tool_root, tool_manifest, market_manifest = matches[0]
    package_id = str(market_manifest.get("id") or tool_manifest.get("name") or tool_root.name)
    warnings: tuple[str, ...] = ()
    environment_root = tool_root / DEPENDENCY_ROOT
    if package_id == PYTHON_SCRIPT_TOOL_ID:
        warning = _migrate_legacy_script_environment(runtime_paths, environment_root)
        warnings = (warning,) if warning else ()
    return PackageTarget(
        display_name=str(tool_manifest.get("display_name") or tool_manifest.get("name") or tool_root.name),
        environment_root=environment_root,
        identifier=tool_root.name,
        kind="tool",
        requirements_path=tool_root / REQUIREMENTS_FILE,
        tool_root=tool_root,
        warnings=warnings,
    )


def _migrate_legacy_script_environment(
    runtime_paths: RuntimePaths,
    target_root: Path,
) -> str | None:
    legacy_root = runtime_paths.runtime_root / "python-packages" / "user" / "py313"
    if not legacy_root.exists():
        return None
    if target_root.exists() and any(target_root.iterdir()):
        raise EnvironmentError(
            "LEGACY_ENVIRONMENT_CONFLICT",
            "旧脚本依赖与新工具依赖目录同时存在，已停止迁移以避免覆盖。",
            {
                "legacy_root": str(legacy_root),
                "target_root": str(target_root),
            },
        )
    target_root.parent.mkdir(parents=True, exist_ok=True)
    if target_root.exists():
        target_root.rmdir()
    try:
        os.replace(legacy_root, target_root)
    except OSError:
        try:
            shutil.copytree(legacy_root, target_root)
            shutil.rmtree(legacy_root)
        except (OSError, shutil.Error) as exc:
            raise EnvironmentError(
                "LEGACY_ENVIRONMENT_MIGRATION_FAILED",
                "无法把旧共享脚本依赖迁入 Python 脚本执行工具。",
                {
                    "legacy_root": str(legacy_root),
                    "target_root": str(target_root),
                },
            ) from exc
    _remove_empty_parents(legacy_root.parent, runtime_paths.runtime_root / "python-packages")
    return "旧共享脚本依赖已迁入 Python 脚本执行工具，并已删除原目录。"


def _remove_empty_parents(path: Path, stop: Path) -> None:
    current = path
    while current != stop:
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent


def _read_json_object(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}
