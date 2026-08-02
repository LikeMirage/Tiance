from dataclasses import dataclass
from typing import Literal

DependencyStatus = Literal["installed", "missing", "version_mismatch", "invalid"]
ToolDependencyTaskStatus = Literal["queued", "running", "done", "error"]


@dataclass(frozen=True, slots=True)
class ToolDependency:
    line_number: int
    requirement: str
    name: str
    specifier: str
    installed_version: str | None
    status: DependencyStatus
    message: str


@dataclass(frozen=True, slots=True)
class ToolDependencyReport:
    category_id: str
    project_id: str
    requirements_path: str
    target_path: str
    index_url: str
    pip_available: bool
    items: tuple[ToolDependency, ...]


@dataclass(frozen=True, slots=True)
class ToolDependencyInstallResult:
    ok: bool
    message: str
    installed: tuple[str, ...]
    report: ToolDependencyReport


@dataclass(frozen=True, slots=True)
class ToolDependencyUninstallResult:
    ok: bool
    message: str
    uninstalled: tuple[str, ...]
    report: ToolDependencyReport


@dataclass(frozen=True, slots=True)
class ToolDependencyInstallTask:
    task_id: str
    category_id: str
    project_id: str
    requirement: str | None
    status: ToolDependencyTaskStatus
    message: str
    error: str | None
    created_at: str
    updated_at: str
    completed_at: str | None = None
    result: ToolDependencyInstallResult | None = None
