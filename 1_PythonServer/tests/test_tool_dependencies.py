from __future__ import annotations

from pathlib import Path
import subprocess
import time

import pytest

from app.core.errors import BadRequestError
from app.infra.tools.tool_project_config_constants import TOOL_REQUIREMENTS_FILE
from app.services.tools.tool_dependency_tasks import ToolDependencyTaskService
from app.services.tools.tool_dependencies import ToolDependencyService
from tests.tool_project_test_support import ToolProjectFixture


def _create_tool(storage: ToolProjectFixture):
    toolset = storage.create_toolset(name="基础工具")
    return toolset, storage.create_tool_folder(toolset.category_id, name="系统信息")


def _write_requirements(folder_root: str, content: str) -> None:
    (Path(folder_root) / TOOL_REQUIREMENTS_FILE).write_text(content, encoding="utf-8")


def _write_dist_info(
    site_packages: Path,
    *,
    name: str,
    version: str,
    files: list[str] | None = None,
) -> None:
    dist_info = site_packages / f"{name}-{version}.dist-info"
    dist_info.mkdir(parents=True, exist_ok=True)
    (dist_info / "METADATA").write_text(
        f"Name: {name}\nVersion: {version}\n",
        encoding="utf-8",
    )
    record_files = [
        *(files or []),
        f"{dist_info.name}/METADATA",
        f"{dist_info.name}/RECORD",
    ]
    (dist_info / "RECORD").write_text(
        "\n".join(f"{path},," for path in record_files),
        encoding="utf-8",
    )


def test_tool_dependency_service_lists_requirement_statuses(tmp_path):
    storage = ToolProjectFixture(tmp_path / "tools")
    toolset, folder = _create_tool(storage)
    site_packages = tmp_path / "tool-packages"
    _write_dist_info(site_packages, name="psutil", version="5.9.6")
    _write_requirements(
        folder.root_path,
        "\n".join(
            [
                "psutil>=5.9.0",
                "pillow==10.0.0",
                "bad @ https://example.com/pkg.whl",
            ]
        ),
    )

    service = ToolDependencyService(
        tool_project_service=storage,
        target_site_packages=site_packages,
        python_executable=tmp_path / "missing-python.exe",
        command_runner=lambda command, timeout: subprocess.CompletedProcess(command, 1),
    )

    report = service.list_dependencies(toolset.category_id, folder.project_id)

    assert report.pip_available is False
    assert [item.status for item in report.items] == [
        "installed",
        "missing",
        "invalid",
    ]
    assert report.items[0].installed_version == "5.9.6"
    assert report.items[1].name == "pillow"
    assert report.items[2].message == "当前只支持普通包名和版本范围。"


def test_tool_dependency_service_detects_version_mismatch(tmp_path):
    storage = ToolProjectFixture(tmp_path / "tools")
    toolset, folder = _create_tool(storage)
    site_packages = tmp_path / "tool-packages"
    _write_dist_info(site_packages, name="psutil", version="5.8.0")
    _write_requirements(folder.root_path, "psutil>=5.9.0\n")

    service = ToolDependencyService(
        tool_project_service=storage,
        target_site_packages=site_packages,
        python_executable=tmp_path / "missing-python.exe",
        command_runner=lambda command, timeout: subprocess.CompletedProcess(command, 1),
    )

    report = service.list_dependencies(toolset.category_id, folder.project_id)

    assert report.items[0].status == "version_mismatch"
    assert report.items[0].installed_version == "5.8.0"


def test_tool_dependency_service_uses_isolated_env_per_tool(tmp_path):
    storage = ToolProjectFixture(tmp_path / "tools")
    toolset = storage.create_toolset(name="基础工具")
    folder_a = storage.create_tool_folder(toolset.category_id, name="工具 A")
    folder_b = storage.create_tool_folder(toolset.category_id, name="工具 B")
    _write_requirements(folder_a.root_path, "sharedpkg<2\n")
    _write_requirements(folder_b.root_path, "sharedpkg>=2\n")

    service = ToolDependencyService(
        tool_project_service=storage,
        python_executable=tmp_path / "missing-python.exe",
        command_runner=lambda command, timeout: subprocess.CompletedProcess(command, 1),
    )
    report_a_before = service.list_dependencies(toolset.category_id, folder_a.project_id)
    report_b_before = service.list_dependencies(toolset.category_id, folder_b.project_id)
    _write_dist_info(Path(report_a_before.target_path), name="sharedpkg", version="1.5.0")
    _write_dist_info(Path(report_b_before.target_path), name="sharedpkg", version="2.1.0")

    report_a = service.list_dependencies(toolset.category_id, folder_a.project_id)
    report_b = service.list_dependencies(toolset.category_id, folder_b.project_id)

    assert report_a.target_path != report_b.target_path
    assert report_a.target_path == str(Path(folder_a.root_path) / "dependencies" / "py313" / "site-packages")
    assert report_b.target_path == str(Path(folder_b.root_path) / "dependencies" / "py313" / "site-packages")
    assert report_a.items[0].status == "installed"
    assert report_a.items[0].installed_version == "1.5.0"
    assert report_b.items[0].status == "installed"
    assert report_b.items[0].installed_version == "2.1.0"


def test_tool_dependency_service_installs_missing_dependency_to_tools_target(tmp_path):
    storage = ToolProjectFixture(tmp_path / "tools")
    toolset, folder = _create_tool(storage)
    site_packages = tmp_path / "tool-packages"
    python_exe = tmp_path / "python.exe"
    pip_runner = tmp_path / "run_pip.py"
    python_exe.write_text("", encoding="utf-8")
    pip_runner.write_text("", encoding="utf-8")
    _write_requirements(folder.root_path, "psutil>=5.9.0\n")
    calls: list[list[str]] = []

    def runner(command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        if command[-1] == "--version":
            return subprocess.CompletedProcess(command, 0, stdout="pip 25.0")
        if "install" in command:
            _write_dist_info(site_packages, name="psutil", version="5.9.6")
            return subprocess.CompletedProcess(command, 0, stdout="ok")
        return subprocess.CompletedProcess(command, 1)

    service = ToolDependencyService(
        tool_project_service=storage,
        target_site_packages=site_packages,
        python_executable=python_exe,
        pip_runner=pip_runner,
        default_index_url="https://mirrors.aliyun.com/pypi/simple/",
        command_runner=runner,
    )

    result = service.install_dependencies(toolset.category_id, folder.project_id)

    install_command = next(command for command in calls if "install" in command)
    assert result.ok is True
    assert result.installed == ("psutil>=5.9.0",)
    assert result.report.items[0].status == "installed"
    assert "--target" in install_command
    assert str(site_packages) in install_command
    assert "--index-url" in install_command
    assert "https://mirrors.aliyun.com/pypi/simple/" in install_command


def test_tool_dependency_service_installs_all_missing_dependencies_in_one_pip_call(tmp_path):
    storage = ToolProjectFixture(tmp_path / "tools")
    toolset, folder = _create_tool(storage)
    site_packages = tmp_path / "tool-packages"
    python_exe = tmp_path / "python.exe"
    pip_runner = tmp_path / "run_pip.py"
    python_exe.write_text("", encoding="utf-8")
    pip_runner.write_text("", encoding="utf-8")
    _write_requirements(folder.root_path, "psutil>=5.9.0\npillow==10.0.0\n")
    calls: list[list[str]] = []

    def runner(command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        if command[-1] == "--version":
            return subprocess.CompletedProcess(command, 0, stdout="pip 25.0")
        if "install" in command:
            _write_dist_info(site_packages, name="psutil", version="5.9.6")
            _write_dist_info(site_packages, name="pillow", version="10.0.0")
            return subprocess.CompletedProcess(command, 0, stdout="ok")
        return subprocess.CompletedProcess(command, 1)

    service = ToolDependencyService(
        tool_project_service=storage,
        target_site_packages=site_packages,
        python_executable=python_exe,
        pip_runner=pip_runner,
        command_runner=runner,
    )

    result = service.install_dependencies(toolset.category_id, folder.project_id)

    install_commands = [command for command in calls if "install" in command]
    assert len(install_commands) == 1
    assert result.installed == ("psutil>=5.9.0", "pillow==10.0.0")
    assert "psutil>=5.9.0" in install_commands[0]
    assert "pillow==10.0.0" in install_commands[0]
    assert [item.status for item in result.report.items] == ["installed", "installed"]


def test_tool_dependency_service_cleans_existing_distribution_before_reinstall(tmp_path):
    storage = ToolProjectFixture(tmp_path / "tools")
    toolset, folder = _create_tool(storage)
    site_packages = tmp_path / "tool-packages"
    package_dir = site_packages / "rich"
    package_dir.mkdir(parents=True)
    (package_dir / "__init__.py").write_text("__version__ = '15.0.0'\n", encoding="utf-8")
    _write_dist_info(
        site_packages,
        name="rich",
        version="15.0.0",
        files=["rich/__init__.py"],
    )
    _write_dist_info(site_packages, name="rich", version="14.3.4")
    python_exe = tmp_path / "python.exe"
    pip_runner = tmp_path / "run_pip.py"
    python_exe.write_text("", encoding="utf-8")
    pip_runner.write_text("", encoding="utf-8")
    _write_requirements(folder.root_path, "rich>=13,<15\n")

    def runner(command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
        if command[-1] == "--version":
            return subprocess.CompletedProcess(command, 0, stdout="pip 25.0")
        if "install" in command:
            package_dir.mkdir(parents=True)
            (package_dir / "__init__.py").write_text("__version__ = '14.3.4'\n", encoding="utf-8")
            _write_dist_info(
                site_packages,
                name="rich",
                version="14.3.4",
                files=["rich/__init__.py"],
            )
            return subprocess.CompletedProcess(command, 0, stdout="ok")
        return subprocess.CompletedProcess(command, 1)

    service = ToolDependencyService(
        tool_project_service=storage,
        target_site_packages=site_packages,
        python_executable=python_exe,
        pip_runner=pip_runner,
        command_runner=runner,
    )

    result = service.install_dependencies(
        toolset.category_id,
        folder.project_id,
        requirement="rich>=13,<15",
    )

    assert result.report.items[0].status == "installed"
    assert result.report.items[0].installed_version == "14.3.4"
    assert not (site_packages / "rich-15.0.0.dist-info").exists()


def test_tool_dependency_service_rejects_install_without_pip(tmp_path):
    storage = ToolProjectFixture(tmp_path / "tools")
    toolset, folder = _create_tool(storage)
    python_exe = tmp_path / "python.exe"
    pip_runner = tmp_path / "run_pip.py"
    python_exe.write_text("", encoding="utf-8")
    pip_runner.write_text("", encoding="utf-8")
    _write_requirements(folder.root_path, "psutil>=5.9.0\n")

    service = ToolDependencyService(
        tool_project_service=storage,
        target_site_packages=tmp_path / "tool-packages",
        python_executable=python_exe,
        pip_runner=pip_runner,
        command_runner=lambda command, timeout: subprocess.CompletedProcess(command, 1),
    )

    with pytest.raises(BadRequestError, match="没有 pip"):
        service.install_dependencies(toolset.category_id, folder.project_id)


def test_tool_dependency_service_only_installs_declared_dependency(tmp_path):
    storage = ToolProjectFixture(tmp_path / "tools")
    toolset, folder = _create_tool(storage)
    python_exe = tmp_path / "python.exe"
    pip_runner = tmp_path / "run_pip.py"
    python_exe.write_text("", encoding="utf-8")
    pip_runner.write_text("", encoding="utf-8")
    _write_requirements(folder.root_path, "psutil>=5.9.0\n")

    service = ToolDependencyService(
        tool_project_service=storage,
        target_site_packages=tmp_path / "tool-packages",
        python_executable=python_exe,
        pip_runner=pip_runner,
        command_runner=lambda command, timeout: subprocess.CompletedProcess(command, 0),
    )

    with pytest.raises(BadRequestError, match="requirements.txt"):
        service.install_dependencies(
            toolset.category_id,
            folder.project_id,
            requirement="pillow",
        )


def test_tool_dependency_service_uninstalls_declared_dependency_from_tools_target(tmp_path):
    storage = ToolProjectFixture(tmp_path / "tools")
    toolset, folder = _create_tool(storage)
    site_packages = tmp_path / "tool-packages"
    package_dir = site_packages / "psutil"
    package_dir.mkdir(parents=True)
    (package_dir / "__init__.py").write_text("__version__ = '5.9.6'\n", encoding="utf-8")
    _write_dist_info(
        site_packages,
        name="psutil",
        version="5.9.6",
        files=["psutil/__init__.py"],
    )
    _write_requirements(folder.root_path, "psutil>=5.9.0\n")

    service = ToolDependencyService(
        tool_project_service=storage,
        target_site_packages=site_packages,
        python_executable=tmp_path / "missing-python.exe",
        command_runner=lambda command, timeout: subprocess.CompletedProcess(command, 1),
    )

    result = service.uninstall_dependency(
        toolset.category_id,
        folder.project_id,
        requirement="psutil>=5.9.0",
    )

    assert result.ok is True
    assert result.uninstalled == ("psutil>=5.9.0",)
    assert result.report.items[0].status == "missing"
    assert not package_dir.exists()
    assert not (site_packages / "psutil-5.9.6.dist-info").exists()


def test_tool_dependency_service_only_uninstalls_declared_dependency(tmp_path):
    storage = ToolProjectFixture(tmp_path / "tools")
    toolset, folder = _create_tool(storage)
    site_packages = tmp_path / "tool-packages"
    _write_dist_info(site_packages, name="pillow", version="10.0.0")
    _write_requirements(folder.root_path, "psutil>=5.9.0\n")

    service = ToolDependencyService(
        tool_project_service=storage,
        target_site_packages=site_packages,
        python_executable=tmp_path / "missing-python.exe",
        command_runner=lambda command, timeout: subprocess.CompletedProcess(command, 1),
    )

    with pytest.raises(BadRequestError, match="requirements.txt"):
        service.uninstall_dependency(
            toolset.category_id,
            folder.project_id,
            requirement="pillow",
        )


def test_tool_dependency_target_is_deleted_with_tool_folder(tmp_path):
    storage = ToolProjectFixture(tmp_path / "tools")
    toolset, folder = _create_tool(storage)
    service = ToolDependencyService(
        tool_project_service=storage,
        python_executable=tmp_path / "missing-python.exe",
        command_runner=lambda command, timeout: subprocess.CompletedProcess(command, 1),
    )
    report = service.list_dependencies(toolset.category_id, folder.project_id)
    target_path = Path(report.target_path)
    target_path.mkdir(parents=True)
    (target_path / "marker.txt").write_text("ok", encoding="utf-8")

    storage.delete_tool_folder(toolset.category_id, folder.project_id)

    assert not Path(folder.root_path).exists()


def test_tool_dependency_task_service_runs_install_in_background(tmp_path):
    storage = ToolProjectFixture(tmp_path / "tools")
    toolset, folder = _create_tool(storage)
    site_packages = tmp_path / "tool-packages"
    python_exe = tmp_path / "python.exe"
    pip_runner = tmp_path / "run_pip.py"
    python_exe.write_text("", encoding="utf-8")
    pip_runner.write_text("", encoding="utf-8")
    _write_requirements(folder.root_path, "psutil>=5.9.0\n")

    def runner(command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
        if command[-1] == "--version":
            return subprocess.CompletedProcess(command, 0, stdout="pip 25.0")
        if "install" in command:
            _write_dist_info(site_packages, name="psutil", version="5.9.6")
            return subprocess.CompletedProcess(command, 0, stdout="ok")
        return subprocess.CompletedProcess(command, 1)

    dependency_service = ToolDependencyService(
        tool_project_service=storage,
        target_site_packages=site_packages,
        python_executable=python_exe,
        pip_runner=pip_runner,
        command_runner=runner,
    )
    task_service = ToolDependencyTaskService(dependency_service, max_workers=1)

    created = task_service.start_install_task(toolset.category_id, folder.project_id)
    completed = _wait_dependency_task(task_service, created.task_id)

    assert created.status in {"queued", "running"}
    assert completed.status == "done"
    assert completed.result is not None
    assert completed.result.installed == ("psutil>=5.9.0",)
    assert completed.result.report.items[0].status == "installed"


def test_tool_dependency_task_service_records_install_errors(tmp_path):
    storage = ToolProjectFixture(tmp_path / "tools")
    toolset, folder = _create_tool(storage)
    python_exe = tmp_path / "python.exe"
    pip_runner = tmp_path / "run_pip.py"
    python_exe.write_text("", encoding="utf-8")
    pip_runner.write_text("", encoding="utf-8")
    _write_requirements(folder.root_path, "psutil>=5.9.0\n")
    dependency_service = ToolDependencyService(
        tool_project_service=storage,
        target_site_packages=tmp_path / "tool-packages",
        python_executable=python_exe,
        pip_runner=pip_runner,
        command_runner=lambda command, timeout: subprocess.CompletedProcess(command, 1),
    )
    task_service = ToolDependencyTaskService(dependency_service, max_workers=1)

    created = task_service.start_install_task(toolset.category_id, folder.project_id)
    completed = _wait_dependency_task(task_service, created.task_id)

    assert completed.status == "error"
    assert completed.error
    assert completed.result is None


def _wait_dependency_task(
    service: ToolDependencyTaskService,
    task_id: str,
):
    for _ in range(100):
        task = service.get_task(task_id)
        if task.status in {"done", "error"}:
            return task
        time.sleep(0.01)
    raise AssertionError("dependency task did not finish")
