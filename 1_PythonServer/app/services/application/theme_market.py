from __future__ import annotations

import asyncio
from contextlib import suppress
from functools import lru_cache
import json
from pathlib import Path
import re
import shutil
from urllib.parse import urlsplit
from uuid import uuid4

from app.core.config import get_settings
from app.core.errors import BadRequestError, ConflictError, NotFoundError
from app.domain.project import ProjectKind
from app.infra.theme_market import ThemeMarketRemoteClient, ThemePackageArchive
from app.infra.theme_market.package_archive import remove_theme_staging_path
from app.infra.theme_market.remote_client import (
    normalize_market_source,
    resolve_market_asset_url,
)
from app.repositories.project import FileProjectCatalog, get_project_repository
from app.repositories.themes import (
    ThemeMarketCacheRepository,
    ThemeMarketSettingsRepository,
    get_theme_market_settings_repository,
)
from app.schemas.themes.theme_market import (
    ThemeMarketFilterSettings,
    ThemeMarketIndexResponse,
    ThemeMarketInstallResponse,
    ThemeMarketRemoteIndex,
    ThemeMarketSettingsResponse,
    ThemeMarketThemeEntry,
    ThemeMarketThemeResponse,
)
from app.services.application.theme_workspace_reconciliation import (
    ThemeWorkspaceReconciliationService,
    get_theme_workspace_reconciliation_service,
)
from app.services.application.online_market import OnlineMarketIndexGateway
from app.services.project import ProjectService, get_project_service


_SEMVER_PATTERN = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:-[0-9A-Za-z.-]+)?$")
_MARKET_THEME_ROOT_FILES = frozenset(("theme.json", "manifest.json"))
_MARKET_THEME_IMAGE_SUFFIXES = frozenset((".avif", ".jpeg", ".jpg", ".png", ".webp"))


class ThemeMarketApplicationService:
    def __init__(
        self,
        *,
        app_version: str,
        settings_repository: ThemeMarketSettingsRepository,
        cache_repository: ThemeMarketCacheRepository,
        remote_client: ThemeMarketRemoteClient,
        archive: ThemePackageArchive,
        catalog: FileProjectCatalog,
        project_service: ProjectService,
        reconciliation_service: ThemeWorkspaceReconciliationService,
    ) -> None:
        self._app_version = app_version
        self._settings_repository = settings_repository
        self._cache_repository = cache_repository
        self._remote_client = remote_client
        self._archive = archive
        self._catalog = catalog
        self._project_service = project_service
        self._reconciliation_service = reconciliation_service
        self._themes_root = reconciliation_service.themes_root
        self._downloads_root = self._themes_root / ".downloads"
        self._index_gateway = OnlineMarketIndexGateway[ThemeMarketRemoteIndex](
            settings_repository=settings_repository,
            cache_repository=cache_repository,
            remote_client=remote_client,
            normalize_source=normalize_market_source,
            validate_index=self._validate_index_payload,
            fallback_errors=(BadRequestError,),
        )

    def get_settings(self) -> ThemeMarketSettingsResponse:
        return self._settings_repository.ensure_settings_file()

    def save_filters(
        self,
        filters: ThemeMarketFilterSettings,
    ) -> ThemeMarketSettingsResponse:
        return self._settings_repository.save_filters(_normalize_filters(filters))

    async def connect(self, source: str) -> ThemeMarketIndexResponse:
        loaded = await self._index_gateway.connect(source)
        return await loaded.build_response(self._to_response)

    async def get_index(self) -> ThemeMarketIndexResponse:
        loaded = await self._index_gateway.get_index()
        return await loaded.build_response(self._to_response)

    async def get_preview_path(self, theme_id: str) -> Path:
        source = normalize_market_source(self.get_settings().source)
        loaded = await self._index_gateway.read_cached(source)
        if loaded is None:
            loaded = await self._index_gateway.fetch(source)
        entry = _require_entry(loaded.index, theme_id)
        suffix = Path(urlsplit(entry.preview_url).path).suffix.lower()
        if suffix not in {".avif", ".jpeg", ".jpg", ".png", ".webp"}:
            suffix = ".webp"
        cache_path = self._cache_repository.preview_path(
            source,
            f"{entry.id}-{entry.version}{suffix}",
        )
        if cache_path.is_file():
            return cache_path
        content = await self._remote_client.download_preview(
            source=source,
            preview_url=entry.preview_url,
        )
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = cache_path.with_name(f".{cache_path.name}.{uuid4().hex}.tmp")
        try:
            temporary_path.write_bytes(content)
            _verify_preview_image(temporary_path)
            temporary_path.replace(cache_path)
        finally:
            with suppress(OSError):
                temporary_path.unlink(missing_ok=True)
        return cache_path

    async def install_theme(
        self,
        *,
        theme_id: str,
        category_id: str | None,
        replace_existing: bool = False,
    ) -> ThemeMarketInstallResponse:
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", theme_id):
            raise BadRequestError("在线主题 ID 无效。")
        target_root = self._themes_root / theme_id
        existing_project = self._catalog.get_project_by_root_path(str(target_root))
        if target_root.exists() != (existing_project is not None):
            raise ConflictError("本地主题目录和主题索引不一致，请先刷新主题集后重试。")
        is_installed = target_root.exists() or existing_project is not None
        if is_installed and not replace_existing:
            raise ConflictError(
                "此主题已经安装。",
                details={"reason": "theme_already_installed", "theme_id": theme_id},
            )

        category = None
        if not is_installed:
            if category_id is None:
                raise BadRequestError("请选择有效的本地主题分类。")
            category = self._project_service.get_project_category(category_id)
            if category is None or category.category_kind is not ProjectKind.THEME:
                raise BadRequestError("请选择有效的本地主题分类。")
        elif existing_project is None:
            raise ConflictError("本地主题目录未登记，暂时不能安全更新。")

        source = normalize_market_source(self.get_settings().source)
        remote_index = (await self._index_gateway.fetch(source)).index
        entry = _require_entry(remote_index, theme_id)
        self._require_compatible(entry)
        if is_installed:
            local_version = _installed_version(target_root)
            if local_version is None:
                raise ConflictError("本地主题没有版本信息，暂时不能自动更新。")
            if _version_tuple(entry.version) <= _version_tuple(local_version):
                raise ConflictError("当前主题已经是最新版本。")

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
            return await asyncio.to_thread(
                self._commit_theme_install,
                archive_path=archive_path,
                staging_root=staging_root,
                target_root=target_root,
                entry=entry,
                is_installed=is_installed,
                category_id=category.category_id if category is not None else None,
            )
        finally:
            await asyncio.to_thread(
                remove_theme_staging_path,
                operation_root,
                allowed_root=self._downloads_root,
            )

    def _commit_theme_install(
        self,
        *,
        archive_path: Path,
        staging_root: Path,
        target_root: Path,
        entry: ThemeMarketThemeEntry,
        is_installed: bool,
        category_id: str | None,
    ) -> ThemeMarketInstallResponse:
        staged_theme_root = self._archive.validate_and_extract(
            archive_path=archive_path,
            staging_root=staging_root,
            market_entry=entry,
        )
        previous_root: Path | None = None
        if is_installed:
            previous_root = staging_root.parent / "rollback"
            if previous_root.exists():
                shutil.rmtree(previous_root)
            target_root.replace(previous_root)
        elif target_root.exists():
            raise ConflictError("此主题已经安装。")
        activated = False
        try:
            staged_theme_root.replace(target_root)
            activated = True
            if previous_root is not None:
                _move_local_theme_entries(previous_root, target_root)
        except Exception:
            if previous_root is not None and previous_root.exists():
                if activated and target_root.exists():
                    _restore_local_theme_entries(target_root, previous_root)
                    target_root.replace(staged_theme_root)
                previous_root.replace(target_root)
            raise
        try:
            self._reconciliation_service.synchronize()
            project = self._catalog.get_project_by_root_path(str(target_root))
            if project is None:
                raise RuntimeError("主题安装后未能登记到本地主题集。")
            if category_id is not None and project.category_id != category_id:
                project = self._project_service.move_project_to_category(
                    project.project_id,
                    category_id=category_id,
                )
        except Exception:
            if activated and target_root.exists():
                if previous_root is not None and previous_root.exists():
                    _restore_local_theme_entries(target_root, previous_root)
                target_root.replace(staged_theme_root)
            if previous_root is not None and previous_root.exists():
                previous_root.replace(target_root)
            self._reconciliation_service.synchronize()
            raise
        if previous_root is not None:
            with suppress(OSError):
                shutil.rmtree(previous_root)
        return ThemeMarketInstallResponse(
            themeId=entry.id,
            projectId=project.project_id,
            categoryId=project.category_id,
            version=entry.version,
        )

    @staticmethod
    def _validate_index_payload(
        source: str,
        payload: dict[str, object],
    ) -> ThemeMarketRemoteIndex:
        try:
            index = ThemeMarketRemoteIndex.model_validate(payload)
        except ValueError as exc:
            raise BadRequestError("在线主题索引格式无效。") from exc
        if len(index.themes) != len({entry.id for entry in index.themes}):
            raise BadRequestError("在线主题索引包含重复主题 ID。")
        for entry in index.themes:
            _validate_market_entry(source, entry)
        return index

    def _to_response(
        self,
        index: ThemeMarketRemoteIndex,
        *,
        source: str,
        cached: bool,
    ) -> ThemeMarketIndexResponse:
        installed_by_id = _installed_versions(self._catalog)
        themes: list[ThemeMarketThemeResponse] = []
        for entry in index.themes:
            is_installed, local_version = installed_by_id.get(entry.id, (False, None))
            status = "not-installed"
            if is_installed:
                status = (
                    "update-available"
                    if local_version and _version_tuple(entry.version) > _version_tuple(local_version)
                    else "installed"
                )
            themes.append(ThemeMarketThemeResponse(
                **entry.model_dump(),
                installationStatus=status,
                localVersion=local_version,
                previewPath=f"/api/themes/market/previews/{entry.id}",
            ))
        return ThemeMarketIndexResponse(
            schemaVersion=1,
            kind=index.kind,
            name=index.name,
            updatedAt=index.updated_at,
            source=source,
            cached=cached,
            themes=themes,
        )

    def _require_compatible(self, entry: ThemeMarketThemeEntry) -> None:
        if entry.compatibility.theme_schema_version != 2:
            raise BadRequestError("主题合同版本不受支持。")
        if _version_tuple(entry.compatibility.min_tiance_version) > _version_tuple(self._app_version):
            raise BadRequestError("当前天策版本无法安装此主题。")


def _validate_market_entry(source: str, entry: ThemeMarketThemeEntry) -> None:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", entry.id):
        raise BadRequestError("在线主题索引包含无效主题 ID。")
    if entry.size < 1 or not re.fullmatch(r"[a-f0-9]{64}", entry.sha256):
        raise BadRequestError("在线主题索引包含无效主题包信息。")
    if _SEMVER_PATTERN.fullmatch(entry.version) is None:
        raise BadRequestError("在线主题索引包含无效版本号。")
    resolve_market_asset_url(source, entry.preview_url)
    resolve_market_asset_url(source, entry.package_url)


def _installed_versions(catalog: FileProjectCatalog) -> dict[str, tuple[bool, str | None]]:
    installed: dict[str, tuple[bool, str | None]] = {}
    for project in catalog.list_projects():
        root = Path(project.root_path)
        try:
            theme_payload = json.loads((root / "theme.json").read_text(encoding="utf-8"))
            theme_id = str(theme_payload.get("id") or "").strip()
        except (OSError, json.JSONDecodeError, AttributeError):
            continue
        if not theme_id:
            continue
        local_version = _installed_version(root)
        installed[theme_id] = (True, local_version)
    return installed


def _installed_version(root: Path) -> str | None:
    try:
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        value = manifest.get("version") if isinstance(manifest, dict) else None
        return value if isinstance(value, str) and _SEMVER_PATTERN.fullmatch(value) else None
    except (OSError, json.JSONDecodeError):
        return None


def _require_entry(index: ThemeMarketRemoteIndex, theme_id: str) -> ThemeMarketThemeEntry:
    entry = next((item for item in index.themes if item.id == theme_id), None)
    if entry is None:
        raise NotFoundError("在线主题不存在。")
    return entry


def _normalize_filters(filters: ThemeMarketFilterSettings) -> ThemeMarketFilterSettings:
    return ThemeMarketFilterSettings(
        modes=sorted(set(filters.modes)),
        authors=sorted({value.strip() for value in filters.authors if value.strip()}),
        baseColors=sorted({value.strip() for value in filters.base_colors if value.strip()}),
        statuses=sorted(set(filters.statuses)),
    )


def _move_local_theme_entries(source_root: Path, target_root: Path) -> None:
    for source in source_root.iterdir():
        if _is_market_owned_theme_entry(source):
            continue
        target = target_root / source.name
        if target.exists():
            raise ConflictError(f"新版主题包与本地文件冲突：{source.name}")
        source.replace(target)


def _restore_local_theme_entries(source_root: Path, target_root: Path) -> None:
    for source in source_root.iterdir():
        if _is_market_owned_theme_entry(source):
            continue
        target = target_root / source.name
        if not target.exists():
            source.replace(target)


def _is_market_owned_theme_entry(path: Path) -> bool:
    return (
        path.name in _MARKET_THEME_ROOT_FILES
        or path.name == "assets"
        or (path.is_file() and path.suffix.lower() in _MARKET_THEME_IMAGE_SUFFIXES)
    )


def _version_tuple(version: str) -> tuple[int, int, int]:
    match = _SEMVER_PATTERN.fullmatch(version)
    if match is None:
        return 0, 0, 0
    return tuple(int(value) for value in match.groups())


def _verify_preview_image(path: Path) -> None:
    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(path) as image:
            if image.width * image.height > 50_000_000:
                raise BadRequestError("主题预览图尺寸超过允许范围。")
            image.verify()
    except BadRequestError:
        raise
    except (OSError, UnidentifiedImageError) as exc:
        raise BadRequestError("主题预览图格式无效。") from exc


@lru_cache
def get_theme_market_application_service() -> ThemeMarketApplicationService:
    settings = get_settings()
    catalog = get_project_repository().get_file_catalog(ProjectKind.THEME)
    if catalog is None:
        raise RuntimeError("主题集未配置文件目录索引。")
    return ThemeMarketApplicationService(
        app_version=settings.app_version,
        settings_repository=get_theme_market_settings_repository(),
        cache_repository=ThemeMarketCacheRepository(
            settings.themes_data_path / ".market-cache"
        ),
        remote_client=ThemeMarketRemoteClient(),
        archive=ThemePackageArchive(),
        catalog=catalog,
        project_service=get_project_service(),
        reconciliation_service=get_theme_workspace_reconciliation_service(),
    )
