from typing import Literal

from pydantic import BaseModel, Field

from app.domain.tools import (
    ToolDependency,
    ToolDependencyInstallTask,
    ToolDependencyInstallResult,
    ToolDependencyReport,
    ToolDependencyUninstallResult,
)

ToolDependencyStatus = Literal["installed", "missing", "version_mismatch", "invalid"]
ToolDependencyTaskStatus = Literal["queued", "running", "done", "error"]


class ToolDependencyResponse(BaseModel):
    line_number: int
    requirement: str
    name: str
    specifier: str
    installed_version: str | None
    status: ToolDependencyStatus
    message: str

    @classmethod
    def from_domain(cls, dependency: ToolDependency) -> "ToolDependencyResponse":
        return cls(
            line_number=dependency.line_number,
            requirement=dependency.requirement,
            name=dependency.name,
            specifier=dependency.specifier,
            installed_version=dependency.installed_version,
            status=dependency.status,
            message=dependency.message,
        )


class ToolDependencyListResponse(BaseModel):
    category_id: str
    project_id: str
    requirements_path: str
    target_path: str
    index_url: str
    pip_available: bool
    count: int
    items: list[ToolDependencyResponse] = Field(default_factory=list)

    @classmethod
    def from_domain(cls, report: ToolDependencyReport) -> "ToolDependencyListResponse":
        items = [ToolDependencyResponse.from_domain(item) for item in report.items]
        return cls(
            category_id=report.category_id,
            project_id=report.project_id,
            requirements_path=report.requirements_path,
            target_path=report.target_path,
            index_url=report.index_url,
            pip_available=report.pip_available,
            count=len(items),
            items=items,
        )


class ToolDependencyInstallRequest(BaseModel):
    requirement: str | None = None
    index_url: str | None = None


class ToolDependencyUninstallRequest(BaseModel):
    requirement: str


class ToolDependencyInstallResponse(BaseModel):
    ok: bool
    message: str
    installed: list[str] = Field(default_factory=list)
    report: ToolDependencyListResponse

    @classmethod
    def from_domain(
        cls,
        result: ToolDependencyInstallResult,
    ) -> "ToolDependencyInstallResponse":
        return cls(
            ok=result.ok,
            message=result.message,
            installed=list(result.installed),
            report=ToolDependencyListResponse.from_domain(result.report),
        )


class ToolDependencyInstallTaskResponse(BaseModel):
    task_id: str
    category_id: str
    project_id: str
    requirement: str | None = None
    status: ToolDependencyTaskStatus
    message: str
    error: str | None = None
    created_at: str
    updated_at: str
    completed_at: str | None = None
    installed: list[str] = Field(default_factory=list)
    report: ToolDependencyListResponse | None = None

    @classmethod
    def from_domain(
        cls,
        task: ToolDependencyInstallTask,
    ) -> "ToolDependencyInstallTaskResponse":
        return cls(
            task_id=task.task_id,
            category_id=task.category_id,
            project_id=task.project_id,
            requirement=task.requirement,
            status=task.status,
            message=task.message,
            error=task.error,
            created_at=task.created_at,
            updated_at=task.updated_at,
            completed_at=task.completed_at,
            installed=list(task.result.installed) if task.result is not None else [],
            report=ToolDependencyListResponse.from_domain(task.result.report)
            if task.result is not None
            else None,
        )


class ToolDependencyUninstallResponse(BaseModel):
    ok: bool
    message: str
    uninstalled: list[str] = Field(default_factory=list)
    report: ToolDependencyListResponse

    @classmethod
    def from_domain(
        cls,
        result: ToolDependencyUninstallResult,
    ) -> "ToolDependencyUninstallResponse":
        return cls(
            ok=result.ok,
            message=result.message,
            uninstalled=list(result.uninstalled),
            report=ToolDependencyListResponse.from_domain(result.report),
        )
