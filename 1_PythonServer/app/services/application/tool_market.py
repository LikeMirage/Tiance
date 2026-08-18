from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import UTC, datetime
from functools import lru_cache
import json
import platform
from pathlib import Path
import re
import shutil
from uuid import uuid4

from app.core.atomic_replace import atomic_replace_path
from app.core.config import get_settings
from app.core.errors import BadRequestError, ConflictError, NotFoundError
from app.domain.project import Project, ProjectKind
from app.infra.tool_market import (
    ToolMarketConnectionError,
    ToolMarketRemoteClient,
    ToolPackageArchive,
    normalize_tool_market_source,
    remove_tool_market_staging_path,
    resolve_tool_market_asset_url,
)
from app.infra.tools.tool_project_config_constants import TOOL_REQUIREMENTS_FILE
from app.repositories.tools.tool_market_cache_repository import ToolMarketCacheRepository
from app.repositories.tools.tool_market_settings_repository import (
    ToolMarketSettingsRepository,
    get_tool_market_settings_repository,
)
from app.schemas.tools.tool_market import (
    ToolMarketEntry,
    ToolMarketFilterSettings,
    ToolMarketIndexResponse,
    ToolMarketInstallResponse,
    ToolMarketRemoteIndex,
    ToolMarketSettingsResponse,
    ToolMarketToolResponse,
    ToolPackageManifest,
)
from app.services.application.project_creation import (
    ProjectCreationApplicationService,
    get_project_creation_application_service,
)
from app.services.application.online_market import OnlineMarketIndexGateway
from app.services.project.projects import ProjectService, get_project_service
from app.services.tools.tool_projects import ToolProjectService, get_tool_project_service
from app.services.tools.tool_registry import ToolRegistryService, get_tool_registry_service
from app.services.tools.tool_dependency_requirements import parse_requirements_file


_MARKET_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_CALL_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
_VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")
_SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")
_RUNTIMES = frozenset({"python", "client", "internal"})
_PLATFORMS = frozenset(
    {
        "any",
        "windows-x64",
        "windows-arm64",
        "linux-x64",
        "linux-arm64",
        "macos-x64",
        "macos-arm64",
    }
)
_LOCAL_PRESERVED_DIRS = (".Tiance", "dependencies")
_LOCAL_CONFIG_FILE = Path("program") / "config.json"
_TOOL_MANIFEST_FILE = Path(".tool") / "tool.json"
_TOOL_MARKET_RECEIPT_FILE = Path(".Tiance") / "tool-market.json"


class ToolMarketApplicationService:
    def __init__(
        self,
        *,
        app_version: str,
        settings_repository: ToolMarketSettingsRepository,
        cache_repository: ToolMarketCacheRepository,
        remote_client: ToolMarketRemoteClient,
        archive: ToolPackageArchive,
        project_service: ProjectService,
        creation_service: ProjectCreationApplicationService,
        tool_projects: ToolProjectService,
        registry: ToolRegistryService,
    ) -> None:
        self._app_version = app_version
        self._settings_repository = settings_repository
        self._cache_repository = cache_repository
        self._remote_client = remote_client
        self._archive = archive
        self._project_service = project_service
        self._creation_service = creation_service
        self._tool_projects = tool_projects
        self._registry = registry
        self._index_gateway = OnlineMarketIndexGateway[ToolMarketRemoteIndex](
            settings_repository=settings_repository,
            cache_repository=cache_repository,
            remote_client=remote_client,
            normalize_source=normalize_tool_market_source,
            validate_index=self._validate_index_payload,
            fallback_errors=(ToolMarketConnectionError,),
        )

    def prepare(self) -> ToolMarketSettingsResponse:
        return self._settings_repository.ensure_settings_file()

    def get_settings(self) -> ToolMarketSettingsResponse:
        return self._settings_repository.get_settings()

    def save_filters(self, filters: ToolMarketFilterSettings) -> ToolMarketSettingsResponse:
        return self._settings_repository.save_filters(filters)

    async def connect(self, source: str) -> ToolMarketIndexResponse:
        loaded = await self._index_gateway.connect(source)
        return await loaded.build_response(self._to_response)

    async def get_index(self) -> ToolMarketIndexResponse:
        loaded = await self._index_gateway.get_index()
        return await loaded.build_response(self._to_response)

    async def install_tool(
        self,
        *,
        tool_id: str,
        category_id: str | None,
        call_name: str | None,
    ) -> ToolMarketInstallResponse:
        _require_market_id(tool_id)
        source = normalize_tool_market_source(self.get_settings().source)
        remote = (await self._index_gateway.fetch(source)).index
        entry = _require_entry(remote, tool_id)
        self._require_compatible(entry)

        local_matches = await asyncio.to_thread(self._find_tools_by_market_id, tool_id)
        if len(local_matches) > 1:
            raise ConflictError("本地存在多个相同市场身份的工具，无法确定更新目标。")
        existing = local_matches[0] if local_matches else None
        if existing is not None:
            local_version = _read_local_market_manifest(existing).version
            if _version_tuple(entry.version) <= _version_tuple(local_version):
                raise ConflictError("当前工具已经是最新版本。")
            selected_call_name = _read_tool_call_name(existing)
        else:
            if category_id is None:
                raise BadRequestError("请选择有效的本地工具分类。")
            self._require_category(category_id)
            selected_call_name = (call_name or entry.call_name).strip()
            _require_call_name(selected_call_name)
            conflict = await asyncio.to_thread(
                self._find_project_by_call_name,
                selected_call_name,
            )
            if conflict is not None:
                raise ConflictError(
                    "工具调用名称已存在，请输入新的调用名称。",
                    details={
                        "reason": "tool_call_name_conflict",
                        "call_name": selected_call_name,
                        "suggested_call_name": await asyncio.to_thread(
                            self._suggest_call_name,
                            selected_call_name,
                        ),
                    },
                )

        operation_root = self._cache_repository.downloads_root / uuid4().hex
        archive_path = operation_root / "package.zip"
        staging_root = operation_root / "staging"
        try:
            await self._remote_client.download_package(
                source=source,
                package_url=entry.package_url,
                expected_size=entry.size,
                expected_sha256=entry.sha256,
                target=archive_path,
            )
            package_root = await asyncio.to_thread(
                self._archive.validate_and_extract,
                archive_path=archive_path,
                staging_root=staging_root,
                market_entry=entry,
            )
            has_dependencies = bool(
                await asyncio.to_thread(
                    parse_requirements_file,
                    package_root / TOOL_REQUIREMENTS_FILE,
                )
            )
            if existing is not None:
                project = await asyncio.to_thread(
                    self._update_installed_tool,
                    project=existing,
                    package_root=package_root,
                    source=source,
                    entry=entry,
                    call_name=selected_call_name,
                    backup_root=operation_root / "backup",
                )
                updated = True
            else:
                project = await asyncio.to_thread(
                    self._install_new_tool,
                    package_root=package_root,
                    category_id=category_id or "",
                    source=source,
                    entry=entry,
                    call_name=selected_call_name,
                )
                updated = False
            return ToolMarketInstallResponse(
                toolId=entry.id,
                projectId=project.project_id,
                categoryId=project.category_id,
                callName=selected_call_name,
                version=entry.version,
                updated=updated,
                hasDependencies=has_dependencies,
            )
        finally:
            await asyncio.to_thread(
                remove_tool_market_staging_path,
                operation_root,
                allowed_root=self._cache_repository.downloads_root,
            )

    def _install_new_tool(
        self,
        *,
        package_root: Path,
        category_id: str,
        source: str,
        entry: ToolMarketEntry,
        call_name: str,
    ) -> Project:
        _write_tool_call_name(package_root, call_name)
        registration_name = _read_tool_registration_name(package_root)
        project_id = str(uuid4())
        project = self._project_service.install_managed_project_snapshot(
            staged_root=package_root,
            project_id=project_id,
            name=registration_name,
            category_id=category_id,
            project_kind=ProjectKind.TOOL,
        )
        try:
            self._creation_service.ensure_initial_conversation(project.project_id)
            _write_market_receipt(
                Path(project.root_path),
                source=source,
                entry=entry,
                local_call_name=call_name,
            )
            self._registry.rebuild_registry()
        except Exception:
            self._project_service.rollback_managed_project_snapshot(
                project.project_id,
                staged_root=package_root,
                project_kind=ProjectKind.TOOL,
            )
            raise
        return project

    def _update_installed_tool(
        self,
        *,
        project: Project,
        package_root: Path,
        source: str,
        entry: ToolMarketEntry,
        call_name: str,
        backup_root: Path,
    ) -> Project:
        target_root = Path(project.root_path).resolve()
        _preserve_local_tool_state(target_root, package_root, call_name=call_name)
        _write_market_receipt(
            package_root,
            source=source,
            entry=entry,
            local_call_name=call_name,
        )
        if backup_root.exists():
            shutil.rmtree(backup_root)
        target_root.replace(backup_root)
        try:
            package_root.replace(target_root)
            self._registry.rebuild_registry()
        except Exception:
            with suppress(OSError):
                if target_root.exists():
                    target_root.replace(package_root)
            if backup_root.exists():
                backup_root.replace(target_root)
            with suppress(Exception):
                self._registry.rebuild_registry()
            raise
        shutil.rmtree(backup_root)
        return project

    @staticmethod
    def _validate_index_payload(
        source: str,
        payload: dict[str, object],
    ) -> ToolMarketRemoteIndex:
        try:
            index = ToolMarketRemoteIndex.model_validate(payload)
        except ValueError as exc:
            raise BadRequestError("在线工具索引格式无效。") from exc
        ids: set[str] = set()
        for entry in index.tools:
            _validate_market_entry(source, entry)
            if entry.id in ids:
                raise BadRequestError("在线工具索引包含重复工具 ID。")
            ids.add(entry.id)
        return index

    def _to_response(
        self,
        remote: ToolMarketRemoteIndex,
        *,
        source: str,
        cached: bool,
    ) -> ToolMarketIndexResponse:
        local_projects = self._all_tool_projects()
        local_by_market_id: dict[str, list[Project]] = {}
        local_manifest_by_project_id: dict[str, ToolPackageManifest] = {}
        local_call_name_by_project_id: dict[str, str] = {}
        local_by_call_name: dict[str, Project] = {}
        for project in local_projects:
            try:
                call_name = _read_tool_call_name(project)
            except (OSError, ValueError):
                pass
            else:
                local_call_name_by_project_id[project.project_id] = call_name
                local_by_call_name[call_name] = project

            try:
                manifest = _read_local_market_manifest(project)
            except (OSError, ValueError):
                continue
            local_manifest_by_project_id[project.project_id] = manifest
            local_by_market_id.setdefault(manifest.id, []).append(project)

        tools: list[ToolMarketToolResponse] = []
        for entry in remote.tools:
            matches = local_by_market_id.get(entry.id, [])
            local_project = matches[0] if len(matches) == 1 else None
            local_version = (
                local_manifest_by_project_id[local_project.project_id].version
                if local_project is not None
                else None
            )
            local_call_name = (
                local_call_name_by_project_id.get(local_project.project_id)
                if local_project is not None
                else None
            )
            if local_project is not None:
                status = (
                    "update-available"
                    if local_version and _version_tuple(entry.version) > _version_tuple(local_version)
                    else "installed"
                )
            elif entry.call_name in local_by_call_name:
                status = "call-name-conflict"
            else:
                status = "not-installed"
            tools.append(
                ToolMarketToolResponse(
                    **entry.model_dump(by_alias=True),
                    installationStatus=status,
                    localProjectId=local_project.project_id if local_project else None,
                    localVersion=local_version,
                    localCallName=local_call_name,
                    suggestedCallName=(
                        self._suggest_call_name(
                            entry.call_name,
                            existing=local_by_call_name,
                        )
                        if status == "call-name-conflict"
                        else None
                    ),
                )
            )
        return ToolMarketIndexResponse(
            schemaVersion=remote.schema_version,
            kind=remote.kind,
            name=remote.name,
            updatedAt=remote.updated_at,
            source=source,
            cached=cached,
            tools=tools,
        )

    def _require_compatible(self, entry: ToolMarketEntry) -> None:
        if _version_tuple(entry.compatibility.min_tiance_version) > _version_tuple(
            self._app_version
        ):
            raise BadRequestError("该工具需要更高版本的天策。")
        current = _current_platform_tag()
        if "any" not in entry.compatibility.platforms and current not in entry.compatibility.platforms:
            raise BadRequestError(f"该工具不支持当前平台 {current}。")

    def _require_category(self, category_id: str) -> None:
        if not any(item.category_id == category_id for item in self._tool_projects.list_toolsets()):
            raise BadRequestError("请选择有效的本地工具分类。")

    def _all_tool_projects(self) -> tuple[Project, ...]:
        projects: list[Project] = []
        for category in self._tool_projects.list_toolsets():
            for folder in self._tool_projects.list_tool_folders(category.category_id):
                project = self._tool_projects.get_tool_project(folder.project_id)
                if project is not None:
                    projects.append(project)
        return tuple(projects)

    def _find_tools_by_market_id(self, market_id: str) -> list[Project]:
        matches: list[Project] = []
        for project in self._all_tool_projects():
            try:
                manifest = _read_local_market_manifest(project)
            except (OSError, ValueError):
                continue
            if manifest.id == market_id:
                matches.append(project)
        return matches

    def _local_tools_by_call_name(self) -> dict[str, Project]:
        result: dict[str, Project] = {}
        for project in self._all_tool_projects():
            try:
                result[_read_tool_call_name(project)] = project
            except (OSError, ValueError):
                continue
        return result

    def _find_project_by_call_name(self, call_name: str) -> Project | None:
        return self._local_tools_by_call_name().get(call_name)

    def _suggest_call_name(
        self,
        call_name: str,
        *,
        existing: dict[str, Project] | None = None,
    ) -> str:
        if existing is None:
            existing = self._local_tools_by_call_name()
        index = 2
        while f"{call_name}_{index}" in existing:
            index += 1
        return f"{call_name}_{index}"


def _validate_market_entry(source: str, entry: ToolMarketEntry) -> None:
    _require_market_id(entry.id)
    _require_call_name(entry.call_name)
    if not entry.display_name.strip() or not entry.author.strip() or not entry.summary.strip():
        raise BadRequestError("在线工具索引包含空的展示信息。")
    if _VERSION_PATTERN.fullmatch(entry.version) is None:
        raise BadRequestError("在线工具索引包含无效版本号。")
    if _VERSION_PATTERN.fullmatch(entry.compatibility.min_tiance_version) is None:
        raise BadRequestError("在线工具索引包含无效兼容版本。")
    if entry.runtime not in _RUNTIMES:
        raise BadRequestError("在线工具索引包含不支持的运行类型。")
    if not entry.compatibility.platforms or any(
        item not in _PLATFORMS for item in entry.compatibility.platforms
    ):
        raise BadRequestError("在线工具索引包含无效平台声明。")
    if entry.size < 1 or _SHA256_PATTERN.fullmatch(entry.sha256) is None:
        raise BadRequestError("在线工具索引包含无效安装包信息。")
    resolve_tool_market_asset_url(source, entry.package_url)


def _preserve_local_tool_state(source_root: Path, target_root: Path, *, call_name: str) -> None:
    for directory_name in _LOCAL_PRESERVED_DIRS:
        source = source_root / directory_name
        if source.is_dir():
            shutil.copytree(source, target_root / directory_name, dirs_exist_ok=True, symlinks=True)
    local_config = source_root / _LOCAL_CONFIG_FILE
    if local_config.is_file():
        target_config = target_root / _LOCAL_CONFIG_FILE
        target_config.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(local_config, target_config)

    source_manifest = _read_json_object(source_root / _TOOL_MANIFEST_FILE)
    target_manifest = _read_json_object(target_root / _TOOL_MANIFEST_FILE)
    target_manifest["name"] = call_name
    for field in ("state", "loading"):
        if isinstance(source_manifest.get(field), dict):
            target_manifest[field] = source_manifest[field]
    _write_json_atomic(target_root / _TOOL_MANIFEST_FILE, target_manifest)


def _write_tool_call_name(tool_root: Path, call_name: str) -> None:
    manifest_path = tool_root / _TOOL_MANIFEST_FILE
    payload = _read_json_object(manifest_path)
    payload["name"] = call_name
    _write_json_atomic(manifest_path, payload)


def _write_market_receipt(
    tool_root: Path,
    *,
    source: str,
    entry: ToolMarketEntry,
    local_call_name: str,
) -> None:
    _write_json_atomic(
        tool_root / _TOOL_MARKET_RECEIPT_FILE,
        {
            "schemaVersion": 1,
            "kind": "tiance-tool-market-installation",
            "source": source,
            "toolId": entry.id,
            "version": entry.version,
            "publishedCallName": entry.call_name,
            "localCallName": local_call_name,
            "updatedAt": datetime.now(UTC).isoformat(),
        },
    )


def _read_local_market_manifest(project: Project) -> ToolPackageManifest:
    manifest = ToolPackageManifest.model_validate_json(
        (Path(project.root_path) / "manifest.json").read_text(encoding="utf-8")
    )
    if (
        _MARKET_ID_PATTERN.fullmatch(manifest.id) is None
        or _VERSION_PATTERN.fullmatch(manifest.version) is None
    ):
        raise ValueError("Local tool market manifest identity is invalid.")
    return manifest


def _read_tool_call_name(project: Project) -> str:
    payload = _read_json_object(Path(project.root_path) / _TOOL_MANIFEST_FILE)
    value = payload.get("name")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Tool call name is missing.")
    return value.strip()


def _read_tool_registration_name(tool_root: Path) -> str:
    payload = _read_json_object(tool_root / _TOOL_MANIFEST_FILE)
    value = payload.get("registration_name")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Tool registration name is missing.")
    return value.strip()


def _read_json_object(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("JSON payload must be an object.")
    return payload


def _write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        atomic_replace_path(temporary, path)
    finally:
        with suppress(OSError):
            temporary.unlink(missing_ok=True)


def _require_entry(index: ToolMarketRemoteIndex, tool_id: str) -> ToolMarketEntry:
    for entry in index.tools:
        if entry.id == tool_id:
            return entry
    raise NotFoundError("在线工具不存在。")


def _require_market_id(value: str) -> None:
    if _MARKET_ID_PATTERN.fullmatch(value) is None:
        raise BadRequestError("在线工具 ID 无效。")


def _require_call_name(value: str) -> None:
    if _CALL_NAME_PATTERN.fullmatch(value) is None:
        raise BadRequestError("工具调用名称只能使用小写英文、数字和下划线，并以英文开头。")


def _version_tuple(value: str) -> tuple[int, int, int]:
    try:
        parts = tuple(int(part) for part in value.split("."))
    except ValueError as exc:
        raise BadRequestError("工具版本号无效。") from exc
    if len(parts) != 3:
        raise BadRequestError("工具版本号无效。")
    return parts


def _current_platform_tag() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    os_name = {"windows": "windows", "linux": "linux", "darwin": "macos"}.get(
        system,
        system,
    )
    architecture = "arm64" if machine in {"arm64", "aarch64"} else "x64"
    return f"{os_name}-{architecture}"


@lru_cache
def get_tool_market_application_service() -> ToolMarketApplicationService:
    settings = get_settings()
    return ToolMarketApplicationService(
        app_version=settings.app_version,
        settings_repository=get_tool_market_settings_repository(),
        cache_repository=ToolMarketCacheRepository(
            settings.tools_data_path / ".market-cache"
        ),
        remote_client=ToolMarketRemoteClient(),
        archive=ToolPackageArchive(),
        project_service=get_project_service(),
        creation_service=get_project_creation_application_service(),
        tool_projects=get_tool_project_service(),
        registry=get_tool_registry_service(),
    )
