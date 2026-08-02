from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from app.core.config import get_settings
from app.core.errors import BadRequestError
from app.domain.tools import (
    ToolDependencyInstallResult,
    ToolDependencyReport,
    ToolDependencyUninstallResult,
)
from app.infra.tools.tool_project_config_constants import (
    TOOL_DEPENDENCIES_DIR,
    TOOL_REQUIREMENTS_FILE,
)
from app.services.tools.tool_dependency_requirements import (
    parse_requirements_file,
    resolve_dependency_status,
    select_install_targets,
    select_uninstall_target,
)
from app.services.tools.tool_dependency_runtime import (
    CommandRunner,
    normalize_index_url,
    run_command,
)
from app.services.tools.tool_dependency_site_packages import (
    read_installed_versions,
    remove_installed_distribution,
)
from app.services.tools.tool_projects import ToolProjectService, get_tool_project_service


class ToolDependencyService:
    def __init__(
        self,
        *,
        tool_project_service: ToolProjectService,
        target_site_packages: Path | None = None,
        python_executable: Path | None = None,
        pip_runner: Path | None = None,
        default_index_url: str | None = None,
        install_timeout_seconds: int | None = None,
        command_runner: CommandRunner | None = None,
    ) -> None:
        settings = get_settings()
        self._fixed_target_site_packages = target_site_packages
        self._python_executable = (
            python_executable
            if python_executable is not None
            else settings.embedded_python_file
        )
        self._pip_runner = (
            pip_runner
            if pip_runner is not None
            else settings.embedded_pip_runner_file
        )
        self._default_index_url = default_index_url or settings.tool_dependency_index_url
        self._install_timeout_seconds = (
            install_timeout_seconds
            if install_timeout_seconds is not None
            else settings.tool_dependency_install_timeout_seconds
        )
        self._command_runner = command_runner or run_command
        self._tool_projects = tool_project_service

    def list_dependencies(self, category_id: str, project_id: str) -> ToolDependencyReport:
        folder_root = self._project_root(category_id, project_id)
        target_site_packages = self._target_site_packages(folder_root)
        requirements_path = folder_root / TOOL_REQUIREMENTS_FILE
        parsed_requirements = parse_requirements_file(requirements_path)
        installed_versions = read_installed_versions(target_site_packages)
        items = tuple(
            resolve_dependency_status(requirement, installed_versions)
            for requirement in parsed_requirements
        )
        return ToolDependencyReport(
            category_id=category_id,
            project_id=project_id,
            requirements_path=str(requirements_path),
            target_path=str(target_site_packages),
            index_url=self._default_index_url,
            pip_available=self._is_pip_available(),
            items=items,
        )

    def install_dependencies(
        self,
        category_id: str,
        project_id: str,
        *,
        requirement: str | None = None,
        index_url: str | None = None,
    ) -> ToolDependencyInstallResult:
        report = self.list_dependencies(category_id, project_id)
        install_targets = select_install_targets(report.items, requirement=requirement)
        if not install_targets:
            return ToolDependencyInstallResult(
                ok=True,
                message="没有需要安装的依赖。",
                installed=(),
                report=report,
            )
        if not report.pip_available:
            raise BadRequestError("内置 Python 当前没有 pip，暂时不能安装工具依赖。")

        resolved_index_url = normalize_index_url(index_url or self._default_index_url)
        target_site_packages = Path(report.target_path)
        target_site_packages.mkdir(parents=True, exist_ok=True)
        for target in install_targets:
            remove_installed_distribution(target_site_packages, target.name)

        command = [
            str(self._python_executable),
            str(self._pip_runner),
            "install",
            "--disable-pip-version-check",
            "--no-input",
            "--upgrade",
            "--target",
            str(target_site_packages),
            "--index-url",
            resolved_index_url,
            *[target.requirement for target in install_targets],
        ]
        completed = self._command_runner(command, self._install_timeout_seconds)
        if completed.returncode != 0:
            message = (completed.stderr or completed.stdout or "").strip()
            raise BadRequestError(message or "安装依赖失败。")

        return ToolDependencyInstallResult(
            ok=True,
            message="依赖安装完成。",
            installed=tuple(target.requirement for target in install_targets),
            report=self.list_dependencies(category_id, project_id),
        )

    def uninstall_dependency(
        self,
        category_id: str,
        project_id: str,
        *,
        requirement: str,
    ) -> ToolDependencyUninstallResult:
        report = self.list_dependencies(category_id, project_id)
        target = select_uninstall_target(report.items, requirement=requirement)
        removed = remove_installed_distribution(Path(report.target_path), target.name)
        return ToolDependencyUninstallResult(
            ok=True,
            message="依赖卸载完成。" if removed else "依赖已不存在。",
            uninstalled=(target.requirement,) if removed else (),
            report=self.list_dependencies(category_id, project_id),
        )

    def _project_root(self, category_id: str, project_id: str) -> Path:
        project = self._tool_projects.require_tool_project(category_id, project_id)
        return Path(project.root_path)

    def _target_site_packages(self, folder_root: Path) -> Path:
        if self._fixed_target_site_packages is not None:
            return self._fixed_target_site_packages
        return folder_root / TOOL_DEPENDENCIES_DIR / "py313" / "site-packages"

    def _is_pip_available(self) -> bool:
        if not self._python_executable.is_file() or not self._pip_runner.is_file():
            return False
        completed = self._command_runner(
            [str(self._python_executable), str(self._pip_runner), "--version"],
            30,
        )
        return completed.returncode == 0


@lru_cache
def get_tool_dependency_service() -> ToolDependencyService:
    return ToolDependencyService(
        tool_project_service=get_tool_project_service(),
    )
