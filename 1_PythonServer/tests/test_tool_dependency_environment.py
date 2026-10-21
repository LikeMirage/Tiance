from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
import sys
from threading import Event
from zipfile import ZipFile

import pytest

from app.core.errors import BadRequestError
from app.services.tools import tool_dependency_environment as environment
from app.services.tools.tool_dependencies import ToolDependencyService
from app.services.tools.tool_dependency_runtime import resolve_tool_site_packages
from tests.test_tool_dependencies import _create_tool, _write_dist_info, _write_requirements
from tests.tool_project_test_support import ToolProjectFixture


def _package(root, name, version, extra_file=None):
    package = root / name
    package.mkdir(parents=True, exist_ok=True)
    (package / "__init__.py").write_text(f"VERSION = {version!r}\n", encoding="utf-8")
    files = [f"{name}/__init__.py"]
    if extra_file:
        (package / extra_file).write_text("old file", encoding="utf-8")
        files.append(f"{name}/{extra_file}")
    _write_dist_info(root, name=name, version=version, files=files)


def _snapshot(root):
    return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def _setup(tmp_path, install, *, fixed=True):
    storage = ToolProjectFixture(tmp_path / "tools")
    toolset, folder = _create_tool(storage)
    target = tmp_path / "packages" if fixed else resolve_tool_site_packages(Path(folder.root_path))
    _package(target, "demo", "1.0", "obsolete.py")
    _package(target, "other", "1.0")
    _write_requirements(folder.root_path, "demo>=2\nother==1.0\n")
    python = tmp_path / "python.exe"
    pip = tmp_path / "run_pip.py"
    python.touch()
    pip.touch()

    def runner(command, timeout):
        if command[-1] == "--version":
            return subprocess.CompletedProcess(command, 0, stdout="pip test")
        incoming = Path(command[command.index("--target") + 1])
        assert incoming != target
        return install(incoming, target)

    service = ToolDependencyService(
        tool_project_service=storage, target_site_packages=target if fixed else None,
        python_executable=python, pip_runner=pip, command_runner=runner,
    )
    return service, toolset.category_id, folder.project_id, target


def _success(incoming, target):
    assert (target / "demo" / "__init__.py").read_text(encoding="utf-8") == "VERSION = '1.0'\n"
    _package(incoming, "demo", "2.0")
    return subprocess.CompletedProcess([], 0, stdout="ok")


@pytest.mark.parametrize("failure", ["download", "partial_install", "exception", "missing", "wrong_version", "break_other", "invalid_metadata"])
def test_failure_before_activation_keeps_every_old_file(tmp_path, failure):
    def fail(incoming, target):
        if failure == "download":
            return subprocess.CompletedProcess([], 1, stderr="download failed")
        if failure == "missing":
            return subprocess.CompletedProcess([], 0, stdout="no files")
        if failure == "invalid_metadata":
            (incoming / "bad.dist-info").mkdir()
            return subprocess.CompletedProcess([], 0)
        _package(incoming, "demo", "1.5" if failure == "wrong_version" else "2.0")
        if failure == "exception":
            raise OSError("installer crashed")
        if failure == "break_other":
            _package(incoming, "other", "2.0")
        return subprocess.CompletedProcess([], 1 if failure == "partial_install" else 0, stderr="install failed")

    service, category, project, target = _setup(tmp_path, fail)
    before = _snapshot(target)
    with pytest.raises((BadRequestError, OSError, ValueError)):
        service.install_dependencies(category, project)
    assert _snapshot(target) == before
    assert service.list_dependencies(category, project).items[0].installed_version == "1.0"
    assert not list(target.parent.glob(f".{target.name}.install-*"))


@pytest.mark.parametrize("fixed", [True, False])
def test_success_replaces_only_changed_packages_and_cleans_staging(tmp_path, fixed):
    service, category, project, target = _setup(tmp_path, _success, fixed=fixed)
    other = _snapshot(target / "other")
    result = service.install_dependencies(category, project)
    assert result.ok
    assert [item.status for item in result.report.items] == ["installed", "installed"]
    assert (target / "demo" / "__init__.py").read_text(encoding="utf-8") == "VERSION = '2.0'\n"
    assert not (target / "demo" / "obsolete.py").exists()
    assert not (target / "demo-1.0.dist-info").exists()
    assert _snapshot(target / "other") == other
    assert not list(target.parent.glob(f".{target.name}.install-*"))


def test_transitive_upgrade_does_not_leave_old_metadata_or_files(tmp_path):
    def install(incoming, target):
        _success(incoming, target)
        _package(incoming, "transitive", "2.0")
        return subprocess.CompletedProcess([], 0)

    service, category, project, target = _setup(tmp_path, install)
    _package(target, "transitive", "1.0", "obsolete.py")
    service.install_dependencies(category, project)
    assert (target / "transitive-2.0.dist-info").is_dir()
    assert not (target / "transitive-1.0.dist-info").exists()
    assert not (target / "transitive" / "obsolete.py").exists()


@pytest.mark.parametrize("failure", ["backup", "activate"])
def test_directory_switch_failure_restores_old_environment(tmp_path, monkeypatch, failure):
    service, category, project, target = _setup(tmp_path, _success)
    before = _snapshot(target)
    real_replace = environment.atomic_replace_path

    def replace(source, destination):
        if (failure == "backup" and source == target) or (failure == "activate" and source.name == "prepared"):
            raise PermissionError("directory locked")
        real_replace(source, destination)

    monkeypatch.setattr(environment, "atomic_replace_path", replace)
    with pytest.raises((BadRequestError, PermissionError)):
        service.install_dependencies(category, project)
    assert _snapshot(target) == before
    assert not list(target.parent.glob(f".{target.name}.install-*"))


def test_failed_rollback_preserves_recoverable_backup(tmp_path, monkeypatch):
    service, category, project, target = _setup(tmp_path, _success)
    before = _snapshot(target)
    real_replace = environment.atomic_replace_path

    def replace(source, destination):
        if destination == target:
            raise PermissionError("activation and rollback blocked")
        real_replace(source, destination)

    monkeypatch.setattr(environment, "atomic_replace_path", replace)
    with pytest.raises(BadRequestError, match="旧环境保留在"):
        service.install_dependencies(category, project)
    backup, = list(target.parent.glob(f".{target.name}.install-*/previous"))
    assert _snapshot(backup) == before


def test_copy_failure_keeps_original_environment(tmp_path, monkeypatch):
    service, category, project, target = _setup(tmp_path, _success)
    before = _snapshot(target)

    def fail(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(environment.shutil, "copytree", fail)
    with pytest.raises(OSError, match="disk full"):
        service.install_dependencies(category, project)
    assert _snapshot(target) == before


def test_concurrent_installs_recheck_status_after_first_finishes(tmp_path):
    started = Event()
    release = Event()
    calls = []

    def install(incoming, target):
        calls.append(incoming)
        started.set()
        assert release.wait(5)
        return _success(incoming, target)

    service, category, project, target = _setup(tmp_path, install)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(service.install_dependencies, category, project)
        assert started.wait(5)
        second = executor.submit(service.install_dependencies, category, project)
        try:
            assert not second.done()
            assert len(calls) == 1
        finally:
            release.set()
        assert first.result(timeout=5).installed == ("demo>=2",)
        assert second.result(timeout=5).installed == ()
    assert len(calls) == 1


def test_real_offline_pip_update_produces_importable_environment(tmp_path):
    pytest.importorskip("pip")
    wheels = tmp_path / "wheels"
    wheels.mkdir()
    info = "demo-2.0.dist-info"
    files = {
        "demo/__init__.py": "VERSION = '2.0'\n",
        f"{info}/METADATA": "Metadata-Version: 2.1\nName: demo\nVersion: 2.0\n",
        f"{info}/WHEEL": "Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
    }
    files[f"{info}/RECORD"] = "\n".join(f"{name},," for name in [*files, f"{info}/RECORD"]) + "\n"
    with ZipFile(wheels / "demo-2.0-py3-none-any.whl", "w") as wheel:
        for name, content in files.items():
            wheel.writestr(name, content)

    def install(incoming, target):
        assert (target / "demo" / "obsolete.py").is_file()
        return subprocess.run(
            [sys.executable, "-m", "pip", "install", "--disable-pip-version-check",
             "--no-index", "--find-links", str(wheels), "--no-compile", "--target", str(incoming), "demo>=2"],
            capture_output=True, text=True, timeout=30, check=False,
        )

    service, category, project, target = _setup(tmp_path, install)
    result = service.install_dependencies(category, project)
    assert result.report.items[0].installed_version == "2.0"
    check = subprocess.run(
        [sys.executable, "-I", "-c", "import sys; sys.path.insert(0, sys.argv[1]); import demo, other; print(demo.VERSION, other.VERSION)", str(target)],
        capture_output=True, text=True, timeout=10, check=True,
    )
    assert check.stdout.strip() == "2.0 1.0"
    assert not (target / "demo" / "obsolete.py").exists()
