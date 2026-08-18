import asyncio
from datetime import UTC, datetime
import json
from pathlib import Path
import threading
from types import SimpleNamespace
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from app.core.errors import BadRequestError
from app.domain.project import Project, ProjectKind
from app.infra.tool_market import ToolPackageArchive
from app.repositories.tools.tool_market_cache_repository import ToolMarketCacheRepository
from app.repositories.tools.tool_market_settings_repository import (
    DEFAULT_TOOL_MARKET_SOURCE,
    ToolMarketSettingsRepository,
)
from app.schemas.tools.tool_market import ToolMarketEntry, ToolMarketRemoteIndex
from app.services.application.tool_market import ToolMarketApplicationService


class _Registry:
    def __init__(self) -> None:
        self.rebuild_count = 0

    def rebuild_registry(self) -> None:
        self.rebuild_count += 1


class _ToolProjects:
    def __init__(self, projects: tuple[Project, ...]) -> None:
        self.projects = {project.project_id: project for project in projects}
        self.list_toolsets_count = 0
        self.list_tool_folders_count = 0

    def list_toolsets(self):
        self.list_toolsets_count += 1
        return (SimpleNamespace(category_id="tool-category"),)

    def list_tool_folders(self, category_id: str):
        assert category_id == "tool-category"
        self.list_tool_folders_count += 1
        return tuple(
            SimpleNamespace(project_id=project.project_id)
            for project in self.projects.values()
        )

    def get_tool_project(self, project_id: str):
        return self.projects.get(project_id)


class _RemoteClient:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    async def fetch_index(self, source: str) -> dict[str, object]:
        assert source == DEFAULT_TOOL_MARKET_SOURCE
        return self.payload


class _PackageRemoteClient:
    async def download_package(self, **_: object) -> None:
        return None


class _PackageArchive:
    def __init__(self, package_root: Path) -> None:
        self.package_root = package_root

    def validate_and_extract(self, **_: object) -> Path:
        return self.package_root


class _IndexGateway:
    def __init__(self, index: ToolMarketRemoteIndex) -> None:
        self.index = index

    async def fetch(self, _: str):
        return SimpleNamespace(index=self.index)


def test_tool_market_default_source_is_github_pages(tmp_path) -> None:
    repository = ToolMarketSettingsRepository(tmp_path / "market-settings.json")

    settings = repository.ensure_settings_file()

    assert settings.source == DEFAULT_TOOL_MARKET_SOURCE
    assert settings.source == "https://likemirage.github.io/Tiance-tools"
    assert json.loads((tmp_path / "market-settings.json").read_text(encoding="utf-8"))[
        "source"
    ] == settings.source


def test_tool_market_index_reads_local_tool_catalog_once(tmp_path) -> None:
    installed_root = tmp_path / "tools" / "installed"
    conflict_root = tmp_path / "tools" / "conflict"
    _write_package(installed_root, version="1.0.0")
    _write_package(conflict_root, version="1.0.0")
    (conflict_root / "manifest.json").unlink()
    conflict_manifest = _read_json(conflict_root / ".tool/tool.json")
    conflict_manifest["name"] = "conflicting_tool"
    _write_json(conflict_root / ".tool/tool.json", conflict_manifest)

    projects = (
        _project(installed_root, "00000000-0000-0000-0000-000000000123"),
        _project(conflict_root, "00000000-0000-0000-0000-000000000124"),
    )
    tool_projects = _ToolProjects(projects)
    service = ToolMarketApplicationService(
        app_version="0.1.0",
        settings_repository=ToolMarketSettingsRepository(tmp_path / "market-settings.json"),
        cache_repository=ToolMarketCacheRepository(tmp_path / ".market-cache"),
        remote_client=object(),
        archive=ToolPackageArchive(),
        project_service=object(),
        creation_service=object(),
        tool_projects=tool_projects,
        registry=_Registry(),
    )
    remote = ToolMarketRemoteIndex.model_validate({
        "schemaVersion": 1,
        "kind": "tiance-tool-market",
        "name": "测试工具市场",
        "updatedAt": datetime.now(UTC).isoformat(),
        "tools": [
            _entry(version="1.0.0").model_dump(by_alias=True),
            _entry_payload(tool_id="conflict-tool", call_name="conflicting_tool"),
            _entry_payload(tool_id="new-tool", call_name="new_tool"),
        ],
    })

    result = service._to_response(
        remote,
        source=DEFAULT_TOOL_MARKET_SOURCE,
        cached=False,
    )

    assert [tool.installation_status for tool in result.tools] == [
        "installed",
        "call-name-conflict",
        "not-installed",
    ]
    assert result.tools[1].suggested_call_name == "conflicting_tool_2"
    assert tool_projects.list_toolsets_count == 1
    assert tool_projects.list_tool_folders_count == 1


def test_tool_market_index_build_does_not_block_api_event_loop(tmp_path) -> None:
    payload = {
        "schemaVersion": 1,
        "kind": "tiance-tool-market",
        "name": "测试工具市场",
        "updatedAt": datetime.now(UTC).isoformat(),
        "tools": [],
    }
    service = ToolMarketApplicationService(
        app_version="0.1.0",
        settings_repository=ToolMarketSettingsRepository(tmp_path / "market-settings.json"),
        cache_repository=ToolMarketCacheRepository(tmp_path / ".market-cache"),
        remote_client=_RemoteClient(payload),
        archive=ToolPackageArchive(),
        project_service=object(),
        creation_service=object(),
        tool_projects=_ToolProjects(()),
        registry=_Registry(),
    )
    event_loop_thread = threading.get_ident()
    response_threads: list[int] = []
    original_to_response = service._to_response

    def record_response_thread(*args, **kwargs):
        response_threads.append(threading.get_ident())
        return original_to_response(*args, **kwargs)

    service._to_response = record_response_thread

    result = asyncio.run(service.get_index())

    assert result.name == "测试工具市场"
    assert response_threads and response_threads[0] != event_loop_thread


def test_tool_package_accepts_config_but_rejects_local_runtime_state(tmp_path) -> None:
    archive_path = tmp_path / "sample-tool.zip"
    files = _package_files(version="1.0.0")
    with ZipFile(archive_path, "w", compression=ZIP_DEFLATED) as archive:
        for name, payload in files.items():
            archive.writestr(f"sample-tool/{name}", payload)

    extracted = ToolPackageArchive().validate_and_extract(
        archive_path=archive_path,
        staging_root=tmp_path / "staging",
        market_entry=_entry(version="1.0.0"),
    )

    assert json.loads((extracted / "program/config.json").read_text(encoding="utf-8")) == {
        "publisherChoice": True
    }

    unsafe_archive = tmp_path / "unsafe.zip"
    with ZipFile(unsafe_archive, "w", compression=ZIP_DEFLATED) as archive:
        for name, payload in files.items():
            archive.writestr(f"sample-tool/{name}", payload)
        archive.writestr("sample-tool/.Tiance/private.json", "{}")

    with pytest.raises(BadRequestError, match="本地工作状态"):
        ToolPackageArchive().validate_and_extract(
            archive_path=unsafe_archive,
            staging_root=tmp_path / "unsafe-staging",
            market_entry=_entry(version="1.0.0"),
        )


def test_tool_market_update_preserves_local_identity_config_and_dependencies(tmp_path) -> None:
    tool_root = tmp_path / "tools" / "local-project"
    _write_package(tool_root, version="1.0.0")
    local_manifest = _read_json(tool_root / ".tool/tool.json")
    local_manifest["name"] = "my_sample_tool"
    local_manifest["loading"] = {"dynamic": True}
    local_manifest["state"] = {"enabled": False}
    _write_json(tool_root / ".tool/tool.json", local_manifest)
    _write_json(tool_root / "program/config.json", {"apiKey": "local-secret"})
    (tool_root / "dependencies").mkdir()
    (tool_root / "dependencies/local.txt").write_text("keep", encoding="utf-8")
    (tool_root / ".Tiance").mkdir()
    _write_json(tool_root / ".Tiance/local.json", {"keep": True})

    package_root = tmp_path / "download" / "sample-tool"
    _write_package(package_root, version="1.1.0")
    (package_root / "program/main.py").write_text("print('new')\n", encoding="utf-8")
    registry = _Registry()
    service = ToolMarketApplicationService(
        app_version="0.1.0",
        settings_repository=ToolMarketSettingsRepository(tmp_path / "market-settings.json"),
        cache_repository=ToolMarketCacheRepository(tmp_path / ".market-cache"),
        remote_client=object(),
        archive=ToolPackageArchive(),
        project_service=object(),
        creation_service=object(),
        tool_projects=object(),
        registry=registry,
    )
    now = datetime.now(UTC).isoformat()
    project = Project(
        project_id="00000000-0000-0000-0000-000000000123",
        name="本地名称",
        root_path=str(tool_root),
        category_id="tool-category",
        project_kind=ProjectKind.TOOL,
        is_default=False,
        sort_order=0,
        created_at=now,
        updated_at=now,
    )

    service._update_installed_tool(
        project=project,
        package_root=package_root,
        source=DEFAULT_TOOL_MARKET_SOURCE,
        entry=_entry(version="1.1.0"),
        call_name="my_sample_tool",
        backup_root=tmp_path / "backup",
    )

    updated_manifest = _read_json(tool_root / ".tool/tool.json")
    assert updated_manifest["name"] == "my_sample_tool"
    assert updated_manifest["loading"] == {"dynamic": True}
    assert updated_manifest["state"] == {"enabled": False}
    assert _read_json(tool_root / "program/config.json") == {"apiKey": "local-secret"}
    assert (tool_root / "dependencies/local.txt").read_text(encoding="utf-8") == "keep"
    assert _read_json(tool_root / ".Tiance/local.json") == {"keep": True}
    assert _read_json(tool_root / ".Tiance/tool-market.json")["version"] == "1.1.0"
    assert (tool_root / "program/main.py").read_text(encoding="utf-8") == "print('new')\n"
    assert registry.rebuild_count == 1


def test_tool_market_install_reports_declared_python_dependencies(tmp_path) -> None:
    tool_root = tmp_path / "tools" / "local-project"
    _write_package(tool_root, version="1.0.0")
    package_root = tmp_path / "download" / "sample-tool"
    _write_package(package_root, version="1.1.0")
    (package_root / "program/requirements.txt").write_text(
        "python-docx==1.2.0\n",
        encoding="utf-8",
    )
    project = _project(tool_root, "00000000-0000-0000-0000-000000000123")
    service = ToolMarketApplicationService(
        app_version="0.1.0",
        settings_repository=ToolMarketSettingsRepository(tmp_path / "market-settings.json"),
        cache_repository=ToolMarketCacheRepository(tmp_path / ".market-cache"),
        remote_client=_PackageRemoteClient(),
        archive=_PackageArchive(package_root),
        project_service=object(),
        creation_service=object(),
        tool_projects=_ToolProjects((project,)),
        registry=_Registry(),
    )
    service.prepare()
    service._index_gateway = _IndexGateway(
        ToolMarketRemoteIndex.model_validate({
            "schemaVersion": 1,
            "kind": "tiance-tool-market",
            "name": "测试工具市场",
            "updatedAt": datetime.now(UTC).isoformat(),
            "tools": [_entry(version="1.1.0").model_dump(by_alias=True)],
        })
    )
    service._update_installed_tool = lambda **_: project

    result = asyncio.run(
        service.install_tool(tool_id="sample-tool", category_id=None, call_name=None)
    )

    assert result.has_dependencies is True
    assert result.project_id == project.project_id
    assert result.updated is True


def _entry(*, version: str) -> ToolMarketEntry:
    return ToolMarketEntry.model_validate(_entry_payload(version=version))


def _entry_payload(
    *,
    tool_id: str = "sample-tool",
    call_name: str = "sample_tool",
    version: str = "1.0.0",
) -> dict[str, object]:
    return {
        "id": tool_id,
        "version": version,
        "author": "LikeMirage",
        "license": "CC0-1.0",
        "callName": call_name,
        "displayName": "示例工具",
        "summary": "用于测试在线工具包。",
        "runtime": "python",
        "packageUrl": f"packages/sample-tool-{version}.zip",
        "sha256": "0" * 64,
        "size": 1,
        "compatibility": {
            "minTianceVersion": "0.1.0",
            "platforms": ["windows-x64"],
        },
    }


def _package_files(*, version: str) -> dict[str, str]:
    return {
        name: json.dumps(payload, ensure_ascii=False)
        for name, payload in {
            "manifest.json": {
                "schemaVersion": 1,
                "kind": "tiance-tool-package",
                "id": "sample-tool",
                "version": version,
                "author": {"name": "LikeMirage"},
                "license": "CC0-1.0",
                "compatibility": {
                    "minTianceVersion": "0.1.0",
                    "platforms": ["windows-x64"],
                },
            },
            ".tool/tool.json": {
                "name": "sample_tool",
                "registration_name": "示例工具",
                "description": "用于测试在线工具包。",
                "keywords": [],
                "loading": {"dynamic": False},
                "execution": {"parallel": False},
                "runtime": {
                    "type": "python",
                    "entry": "program/main.py",
                    "timeout_seconds": 60,
                },
                "state": {"enabled": True},
            },
            ".tool/input.schema.json": {"type": "object", "properties": {}},
            ".tool/output.schema.json": {"type": "object", "properties": {}},
            ".tool/examples.json": [],
            "program/config.json": {"publisherChoice": True},
        }.items()
    } | {"program/main.py": "print('old')\n"}


def _write_package(root: Path, *, version: str) -> None:
    for name, content in _package_files(version=version).items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def _project(root: Path, project_id: str) -> Project:
    now = datetime.now(UTC).isoformat()
    return Project(
        project_id=project_id,
        name=root.name,
        root_path=str(root),
        category_id="tool-category",
        project_kind=ProjectKind.TOOL,
        is_default=False,
        sort_order=0,
        created_at=now,
        updated_at=now,
    )


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
