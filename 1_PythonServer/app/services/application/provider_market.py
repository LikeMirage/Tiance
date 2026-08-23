from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import UTC, datetime
from functools import lru_cache
import json
from pathlib import Path
import re
import shutil
from uuid import uuid4

from app.core.atomic_replace import atomic_replace_path
from app.core.config import get_settings
from app.core.errors import BadRequestError, ConflictError, NotFoundError
from app.domain.llm.provider_catalog import ProviderProtocolFamily
from app.infra.provider_market import (
    ProviderMarketConnectionError,
    ProviderMarketRemoteClient,
    ProviderPackageArchive,
    normalize_provider_market_source,
    remove_provider_staging_path,
    resolve_provider_market_asset_url,
)
from app.repositories.llm.provider_catalog_repository import (
    ProviderCatalogRepository,
    get_provider_catalog_repository,
)
from app.repositories.llm.provider_file_store import (
    PROVIDER_MANIFEST_FILE,
    PROVIDER_MODEL_RULES_FILE,
    PROVIDER_RULES_FILE,
    ProviderFileStore,
    get_provider_file_store,
)
from app.repositories.llm.provider_market_cache_repository import ProviderMarketCacheRepository
from app.repositories.llm.provider_market_settings_repository import (
    ProviderMarketSettingsRepository,
    get_provider_market_settings_repository,
)
from app.schemas.llm.provider_market import (
    ProviderMarketEntry,
    ProviderMarketFilterSettings,
    ProviderMarketIndexResponse,
    ProviderMarketInstallResponse,
    ProviderMarketProviderResponse,
    ProviderMarketRemoteIndex,
    ProviderMarketSettingsResponse,
    ProviderPackageManifest,
)
from app.services.llm.provider.workspace_registry import (
    ProviderWorkspaceRegistryService,
    get_provider_workspace_registry_service,
    provider_project_id,
)
from app.services.application.online_market import OnlineMarketIndexGateway
from app.services.project import ProjectService, get_project_service


MARKET_MANIFEST_FILE = "manifest.json"
PROVIDER_COMPATIBLE_UPDATE_FILES = (
    MARKET_MANIFEST_FILE,
    PROVIDER_RULES_FILE,
    PROVIDER_MODEL_RULES_FILE,
)
_PROVIDER_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")
_SEMVER_PATTERN = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-[0-9A-Za-z.-]+)?$"
)


class ProviderMarketApplicationService:
    def __init__(
        self,
        *,
        app_version: str,
        providers_root: Path,
        settings_repository: ProviderMarketSettingsRepository,
        cache_repository: ProviderMarketCacheRepository,
        remote_client: ProviderMarketRemoteClient,
        archive: ProviderPackageArchive,
        file_store: ProviderFileStore,
        catalog_repository: ProviderCatalogRepository,
        workspace_registry: ProviderWorkspaceRegistryService,
        project_service: ProjectService,
    ) -> None:
        self._app_version = app_version
        self._providers_root = providers_root.resolve()
        self._settings_repository = settings_repository
        self._cache_repository = cache_repository
        self._remote_client = remote_client
        self._archive = archive
        self._file_store = file_store
        self._catalog_repository = catalog_repository
        self._workspace_registry = workspace_registry
        self._project_service = project_service
        self._downloads_root = self._providers_root / ".downloads"
        self._index_gateway = OnlineMarketIndexGateway[ProviderMarketRemoteIndex](
            settings_repository=settings_repository,
            cache_repository=cache_repository,
            remote_client=remote_client,
            normalize_source=normalize_provider_market_source,
            validate_index=self._validate_index_payload,
            fallback_errors=(ProviderMarketConnectionError,),
        )

    def get_settings(self) -> ProviderMarketSettingsResponse:
        return self._settings_repository.ensure_settings_file()

    def save_filters(
        self,
        filters: ProviderMarketFilterSettings,
    ) -> ProviderMarketSettingsResponse:
        return self._settings_repository.save_filters(_normalize_filters(filters))

    async def connect(self, source: str) -> ProviderMarketIndexResponse:
        loaded = await self._index_gateway.connect(source)
        return await loaded.build_response(self._to_response)

    async def get_index(self) -> ProviderMarketIndexResponse:
        loaded = await self._index_gateway.get_index()
        return await loaded.build_response(self._to_response)

    async def install_provider(
        self,
        *,
        provider_id: str,
        category_id: str | None,
        replace_existing: bool = False,
    ) -> ProviderMarketInstallResponse:
        if _PROVIDER_ID_PATTERN.fullmatch(provider_id) is None:
            raise BadRequestError("在线供应商 ID 无效。")

        local_exists = self._file_store.has_provider_directory(provider_id)
        local_manifest = self._read_local_market_manifest(provider_id) if local_exists else None
        if local_exists and not replace_existing:
            raise ConflictError(
                "此供应商已经安装。",
                details={"reason": "provider_already_installed", "provider_id": provider_id},
            )
        if not local_exists:
            if category_id is None:
                raise BadRequestError("请选择有效的本地供应商分类。")
            self._workspace_registry.validate_provider_category(category_id)

        source = normalize_provider_market_source(self.get_settings().source)
        remote_index = (await self._index_gateway.fetch(source)).index
        entry = _require_entry(remote_index, provider_id)
        self._require_compatible(entry)
        if local_manifest is not None and _version_tuple(entry.version) <= _version_tuple(
            local_manifest.version
        ):
            raise ConflictError("当前供应商已经是最新版本。")

        operation_root = self._downloads_root / uuid4().hex
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
            if local_exists:
                await asyncio.to_thread(
                    self._update_installed_provider,
                    provider_id=provider_id,
                    package_root=package_root,
                    backup_root=operation_root / "backup",
                )
                updated = True
            else:
                await asyncio.to_thread(
                    self._install_new_provider,
                    provider_id=provider_id,
                    package_root=package_root,
                    category_id=category_id or "",
                )
                updated = False
            project = self._project_service.get_project(provider_project_id(provider_id))
            if project is None:
                raise RuntimeError("供应商工作区登记失败。")
            return ProviderMarketInstallResponse(
                providerId=provider_id,
                projectId=project.project_id,
                categoryId=project.category_id,
                version=entry.version,
                updated=updated,
            )
        finally:
            await asyncio.to_thread(
                remove_provider_staging_path,
                operation_root,
                allowed_root=self._downloads_root,
            )

    def _install_new_provider(
        self,
        *,
        provider_id: str,
        package_root: Path,
        category_id: str,
    ) -> None:
        target_root = self._file_store.provider_dir(provider_id)
        if target_root.exists():
            raise ConflictError("本地已有同名供应商。")
        old_order = self._catalog_repository.list_ordered_provider_ids()
        self._prepare_new_provider_definition(package_root)
        try:
            target_root.parent.mkdir(parents=True, exist_ok=True)
            atomic_replace_path(package_root, target_root)
            self._file_store.ensure_provider_sidecars(provider_id)
            self._catalog_repository.replace_provider_order(
                (*old_order, provider_id),
                updated_at=_utc_now(),
            )
            self._workspace_registry.synchronize()
            self._workspace_registry.move_provider_to_category(provider_id, category_id)
        except Exception:
            with suppress(OSError):
                if target_root.exists():
                    shutil.rmtree(target_root)
            with suppress(Exception):
                self._catalog_repository.replace_provider_order(old_order, updated_at=_utc_now())
                self._workspace_registry.synchronize()
            raise

    def _update_installed_provider(
        self,
        *,
        provider_id: str,
        package_root: Path,
        backup_root: Path,
    ) -> None:
        target_root = self._file_store.provider_dir(provider_id)
        self._require_compatible_update(
            provider_id=provider_id,
            target_root=target_root,
            package_root=package_root,
        )
        backup_root.mkdir(parents=True, exist_ok=True)
        backed_up: set[str] = set()
        for file_name in PROVIDER_COMPATIBLE_UPDATE_FILES:
            source_path = target_root / file_name
            if source_path.is_file():
                shutil.copy2(source_path, backup_root / file_name)
                backed_up.add(file_name)
        try:
            for file_name in PROVIDER_COMPATIBLE_UPDATE_FILES:
                _atomic_copy(package_root / file_name, target_root / file_name)
        except Exception:
            for file_name in PROVIDER_COMPATIBLE_UPDATE_FILES:
                target = target_root / file_name
                backup = backup_root / file_name
                if file_name in backed_up:
                    _atomic_copy(backup, target)
                else:
                    with suppress(OSError):
                        target.unlink(missing_ok=True)
            raise

    @staticmethod
    def _prepare_new_provider_definition(package_root: Path) -> None:
        package_path = package_root / PROVIDER_MANIFEST_FILE
        payload = _read_json_object(package_path)
        now = _utc_now()
        payload.update(
            {
                "enabled": False,
                "createdAt": now,
                "updatedAt": now,
            }
        )
        _write_json(package_path, payload)

    @staticmethod
    def _require_compatible_update(
        *,
        provider_id: str,
        target_root: Path,
        package_root: Path,
    ) -> None:
        try:
            local_definition = _read_json_object(target_root / PROVIDER_MANIFEST_FILE)
            incoming_definition = _read_json_object(package_root / PROVIDER_MANIFEST_FILE)
        except (OSError, ValueError) as exc:
            raise BadRequestError(
                "本地供应商定义无效，无法执行只更新适配规则。"
            ) from exc
        if local_definition.get("id") != provider_id:
            raise BadRequestError("本地供应商 ID 与目录不一致，无法更新。")
        if (
            local_definition.get("schemaVersion") != incoming_definition.get("schemaVersion")
            or local_definition.get("profileId") != incoming_definition.get("profileId")
        ):
            raise ConflictError(
                "此版本改变了供应商适配身份，不能作为兼容更新；请使用新的供应商 ID 发布。",
                details={
                    "reason": "provider_incompatible_update",
                    "provider_id": provider_id,
                },
            )

    @staticmethod
    def _validate_index_payload(
        source: str,
        payload: dict[str, object],
    ) -> ProviderMarketRemoteIndex:
        try:
            index = ProviderMarketRemoteIndex.model_validate(payload)
        except ValueError as exc:
            raise BadRequestError("在线供应商索引格式无效。") from exc
        if len(index.providers) != len({entry.id for entry in index.providers}):
            raise BadRequestError("在线供应商索引包含重复供应商 ID。")
        for entry in index.providers:
            _validate_market_entry(source, entry)
        return index

    def _to_response(
        self,
        index: ProviderMarketRemoteIndex,
        *,
        source: str,
        cached: bool,
    ) -> ProviderMarketIndexResponse:
        providers: list[ProviderMarketProviderResponse] = []
        for entry in index.providers:
            local_exists = self._file_store.has_provider_directory(entry.id)
            manifest = self._read_local_market_manifest(entry.id) if local_exists else None
            if manifest is None:
                status = "update-available" if local_exists else "not-installed"
                local_version = None
            else:
                local_version = manifest.version
                status = (
                    "update-available"
                    if _version_tuple(entry.version) > _version_tuple(local_version)
                    else "installed"
                )
            providers.append(ProviderMarketProviderResponse(
                **entry.model_dump(),
                installationStatus=status,
                localVersion=local_version,
                localProjectId=provider_project_id(entry.id) if local_exists else None,
            ))
        return ProviderMarketIndexResponse(
            schemaVersion=1,
            kind=index.kind,
            name=index.name,
            updatedAt=index.updated_at,
            source=source,
            cached=cached,
            providers=providers,
        )

    def _read_local_market_manifest(self, provider_id: str) -> ProviderPackageManifest | None:
        try:
            manifest = ProviderPackageManifest.model_validate_json(
                (self._file_store.provider_dir(provider_id) / MARKET_MANIFEST_FILE).read_text(
                    encoding="utf-8"
                )
            )
            return manifest if manifest.id == provider_id else None
        except (OSError, ValueError):
            return None

    def _require_compatible(self, entry: ProviderMarketEntry) -> None:
        if _version_tuple(entry.compatibility.min_tiance_version) > _version_tuple(
            self._app_version
        ):
            raise BadRequestError("当前天策版本无法安装此供应商。")


def _validate_market_entry(source: str, entry: ProviderMarketEntry) -> None:
    if _PROVIDER_ID_PATTERN.fullmatch(entry.id) is None:
        raise BadRequestError("在线供应商索引包含无效供应商 ID。")
    if _SEMVER_PATTERN.fullmatch(entry.version) is None:
        raise BadRequestError("在线供应商索引包含无效版本号。")
    if _SEMVER_PATTERN.fullmatch(entry.compatibility.min_tiance_version) is None:
        raise BadRequestError("在线供应商索引包含无效兼容版本。")
    if entry.size < 1 or not re.fullmatch(r"[a-f0-9]{64}", entry.sha256):
        raise BadRequestError("在线供应商索引包含无效供应商包信息。")
    if entry.model_count < 0:
        raise BadRequestError("在线供应商索引包含无效模型数量。")
    if entry.protocol not in {protocol.value for protocol in ProviderProtocolFamily}:
        raise BadRequestError("在线供应商索引包含不支持的协议。")
    for value, label, maximum in (
        (entry.name, "名称", 80),
        (entry.author, "作者", 80),
        (entry.summary, "简介", 300),
        (entry.license, "许可证", 80),
        (entry.protocol, "协议", 80),
    ):
        if not value.strip() or len(value) > maximum:
            raise BadRequestError(f"在线供应商索引包含无效{label}。")
    resolve_provider_market_asset_url(source, entry.package_url)


def _require_entry(index: ProviderMarketRemoteIndex, provider_id: str) -> ProviderMarketEntry:
    entry = next((item for item in index.providers if item.id == provider_id), None)
    if entry is None:
        raise NotFoundError("在线供应商不存在。")
    return entry


def _normalize_filters(filters: ProviderMarketFilterSettings) -> ProviderMarketFilterSettings:
    return ProviderMarketFilterSettings(
        authors=sorted({value.strip() for value in filters.authors if value.strip()}),
        protocols=sorted({value.strip() for value in filters.protocols if value.strip()}),
        statuses=sorted(set(filters.statuses)),
    )


def _version_tuple(version: str) -> tuple[int, int, int]:
    match = _SEMVER_PATTERN.fullmatch(version)
    if match is None:
        return 0, 0, 0
    return tuple(int(value) for value in match.groups())


def _read_json_object(path: Path | None) -> dict[str, object]:
    if path is None:
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise BadRequestError(f"{path.name} 必须是 JSON 对象。")
    return payload


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _atomic_copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
    try:
        shutil.copy2(source, temporary)
        atomic_replace_path(temporary, target)
    finally:
        with suppress(OSError):
            temporary.unlink(missing_ok=True)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


@lru_cache
def get_provider_market_application_service() -> ProviderMarketApplicationService:
    settings = get_settings()
    return ProviderMarketApplicationService(
        app_version=settings.app_version,
        providers_root=settings.providers_data_path,
        settings_repository=get_provider_market_settings_repository(),
        cache_repository=ProviderMarketCacheRepository(
            settings.providers_data_path / ".market-cache",
        ),
        remote_client=ProviderMarketRemoteClient(),
        archive=ProviderPackageArchive(),
        file_store=get_provider_file_store(),
        catalog_repository=get_provider_catalog_repository(),
        workspace_registry=get_provider_workspace_registry_service(),
        project_service=get_project_service(),
    )
