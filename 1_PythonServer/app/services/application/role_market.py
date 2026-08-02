from __future__ import annotations

import asyncio
from contextlib import suppress
from functools import lru_cache
import json
from pathlib import Path
import re
import shutil
from uuid import uuid4

from app.core.atomic_replace import atomic_replace_path
from app.core.config import get_settings
from app.core.errors import BadRequestError, ConflictError, NotFoundError
from app.domain.project import Project, ProjectKind
from app.infra.role_market import (
    RoleMarketConnectionError,
    RoleMarketRemoteClient,
    RolePackageArchive,
    normalize_role_market_source,
    remove_role_staging_path,
    resolve_role_market_asset_url,
)
from app.repositories.project import FileProjectCatalog, get_project_repository
from app.repositories.roles import (
    RoleMarketCacheRepository,
    RoleMarketSettingsRepository,
    get_role_market_settings_repository,
)
from app.schemas.roles import (
    ROLE_PACKAGE_FILE_NAMES,
    RoleMarketFilterSettings,
    RoleMarketIndexResponse,
    RoleMarketInstallResponse,
    RoleMarketRemoteIndex,
    RoleMarketRoleEntry,
    RoleMarketRoleResponse,
    RoleMarketSettingsResponse,
)
from app.services.application.project_creation import (
    ProjectCreationApplicationService,
    get_project_creation_application_service,
)
from app.services.application.online_market import OnlineMarketIndexGateway
from app.services.project import ProjectService, get_project_service


_ROLE_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_SEMVER_PATTERN = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-[0-9A-Za-z.-]+)?$"
)


class RoleMarketApplicationService:
    def __init__(
        self,
        *,
        app_version: str,
        roles_root: Path,
        settings_repository: RoleMarketSettingsRepository,
        cache_repository: RoleMarketCacheRepository,
        remote_client: RoleMarketRemoteClient,
        archive: RolePackageArchive,
        catalog: FileProjectCatalog,
        project_service: ProjectService,
        project_creation_service: ProjectCreationApplicationService,
    ) -> None:
        self._app_version = app_version
        self._roles_root = roles_root.resolve()
        self._settings_repository = settings_repository
        self._cache_repository = cache_repository
        self._remote_client = remote_client
        self._archive = archive
        self._catalog = catalog
        self._project_service = project_service
        self._project_creation_service = project_creation_service
        self._downloads_root = self._roles_root / ".downloads"
        self._index_gateway = OnlineMarketIndexGateway[RoleMarketRemoteIndex](
            settings_repository=settings_repository,
            cache_repository=cache_repository,
            remote_client=remote_client,
            normalize_source=normalize_role_market_source,
            validate_index=self._validate_index_payload,
            fallback_errors=(RoleMarketConnectionError,),
        )

    def get_settings(self) -> RoleMarketSettingsResponse:
        return self._settings_repository.ensure_settings_file()

    def save_filters(
        self,
        filters: RoleMarketFilterSettings,
    ) -> RoleMarketSettingsResponse:
        return self._settings_repository.save_filters(_normalize_filters(filters))

    async def connect(self, source: str) -> RoleMarketIndexResponse:
        loaded = await self._index_gateway.connect(source)
        return await loaded.build_response(self._to_response)

    async def get_index(self) -> RoleMarketIndexResponse:
        loaded = await self._index_gateway.get_index()
        return await loaded.build_response(self._to_response)

    async def install_role(
        self,
        *,
        role_id: str,
        category_id: str | None,
        replace_existing: bool = False,
    ) -> RoleMarketInstallResponse:
        if _ROLE_ID_PATTERN.fullmatch(role_id) is None:
            raise BadRequestError("在线角色 ID 无效。")

        installed_projects = await asyncio.to_thread(self._installed_projects, role_id)
        if len(installed_projects) > 1:
            raise ConflictError("本地存在多个同源角色，无法确定安全更新目标。")
        installed_project = installed_projects[0][0] if installed_projects else None
        if installed_project is not None and not replace_existing:
            raise ConflictError(
                "此角色已经安装。",
                details={"reason": "role_already_installed", "role_id": role_id},
            )

        category = None
        if installed_project is None:
            if category_id is None:
                raise BadRequestError("请选择有效的本地角色分类。")
            category = self._project_service.get_project_category(category_id)
            if category is None or category.category_kind is not ProjectKind.ROLE:
                raise BadRequestError("请选择有效的本地角色分类。")

        source = normalize_role_market_source(self.get_settings().source)
        remote_index = (await self._index_gateway.fetch(source)).index
        entry = _require_entry(remote_index, role_id)
        self._require_compatible(entry)
        if installed_project is not None:
            local_version = installed_projects[0][1]
            if _version_tuple(entry.version) <= _version_tuple(local_version):
                raise ConflictError("当前角色已经是最新版本。")

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
            if installed_project is None:
                project = await asyncio.to_thread(
                    self._install_new_role,
                    entry=entry,
                    package_root=package_root,
                    category_id=category.category_id if category is not None else "",
                )
                updated = False
            else:
                project = await asyncio.to_thread(
                    self._update_installed_role,
                    project=installed_project,
                    package_root=package_root,
                    backup_root=operation_root / "backup",
                )
                updated = True
            return RoleMarketInstallResponse(
                roleId=entry.id,
                projectId=project.project_id,
                categoryId=project.category_id,
                version=entry.version,
                updated=updated,
            )
        finally:
            await asyncio.to_thread(
                remove_role_staging_path,
                operation_root,
                allowed_root=self._downloads_root,
            )

    def _install_new_role(
        self,
        *,
        entry: RoleMarketRoleEntry,
        package_root: Path,
        category_id: str,
    ) -> Project:
        project = self._project_creation_service.create_role_project(
            name=entry.name,
            category_id=category_id,
        )
        try:
            target_root = self._require_managed_role_root(project)
            self._replace_managed_files(package_root, target_root)
            return project
        except Exception:
            with suppress(Exception):
                self._project_service.delete_project(project.project_id)
            raise

    def _update_installed_role(
        self,
        *,
        project: Project,
        package_root: Path,
        backup_root: Path,
    ) -> Project:
        target_root = self._require_managed_role_root(project)
        backup_root.mkdir(parents=True, exist_ok=True)
        backed_up: set[str] = set()
        for file_name in ROLE_PACKAGE_FILE_NAMES:
            source = target_root / file_name
            if source.is_file():
                shutil.copy2(source, backup_root / file_name)
                backed_up.add(file_name)
        try:
            self._replace_managed_files(package_root, target_root)
        except Exception:
            for file_name in ROLE_PACKAGE_FILE_NAMES:
                target = target_root / file_name
                backup = backup_root / file_name
                if file_name in backed_up:
                    _atomic_copy(backup, target)
                else:
                    with suppress(OSError):
                        target.unlink(missing_ok=True)
            raise
        return project

    @staticmethod
    def _replace_managed_files(source_root: Path, target_root: Path) -> None:
        for file_name in sorted(ROLE_PACKAGE_FILE_NAMES):
            _atomic_copy(source_root / file_name, target_root / file_name)

    def _require_managed_role_root(self, project: Project) -> Path:
        if project.project_kind is not ProjectKind.ROLE:
            raise BadRequestError("市场角色目标不是角色项目。")
        root = Path(project.root_path).resolve()
        try:
            relative = root.relative_to(self._roles_root)
        except ValueError as exc:
            raise ConflictError("在线角色只能安装到天策托管的角色目录。") from exc
        if len(relative.parts) != 1:
            raise ConflictError("角色项目目录结构无效。")
        return root

    @staticmethod
    def _validate_index_payload(
        source: str,
        payload: dict[str, object],
    ) -> RoleMarketRemoteIndex:
        try:
            index = RoleMarketRemoteIndex.model_validate(payload)
        except ValueError as exc:
            raise BadRequestError("在线角色索引格式无效。") from exc
        if len(index.roles) != len({entry.id for entry in index.roles}):
            raise BadRequestError("在线角色索引包含重复角色 ID。")
        for entry in index.roles:
            _validate_market_entry(source, entry)
        return index

    def _to_response(
        self,
        index: RoleMarketRemoteIndex,
        *,
        source: str,
        cached: bool,
    ) -> RoleMarketIndexResponse:
        installed = _installed_market_roles(self._catalog)
        roles: list[RoleMarketRoleResponse] = []
        for entry in index.roles:
            matches = installed.get(entry.id, ())
            project = matches[0][0] if len(matches) == 1 else None
            local_version = matches[0][1] if len(matches) == 1 else None
            status = "not-installed"
            if matches:
                status = (
                    "update-available"
                    if local_version and _version_tuple(entry.version) > _version_tuple(local_version)
                    else "installed"
                )
            roles.append(RoleMarketRoleResponse(
                **entry.model_dump(),
                installationStatus=status,
                localVersion=local_version,
                localProjectId=project.project_id if project else None,
            ))
        return RoleMarketIndexResponse(
            schemaVersion=1,
            kind=index.kind,
            name=index.name,
            updatedAt=index.updated_at,
            source=source,
            cached=cached,
            roles=roles,
        )

    def _installed_projects(self, role_id: str) -> tuple[tuple[Project, str], ...]:
        return _installed_market_roles(self._catalog).get(role_id, ())

    def _require_compatible(self, entry: RoleMarketRoleEntry) -> None:
        if _version_tuple(entry.compatibility.min_tiance_version) > _version_tuple(
            self._app_version
        ):
            raise BadRequestError("当前天策版本无法安装此角色。")


def _validate_market_entry(source: str, entry: RoleMarketRoleEntry) -> None:
    if _ROLE_ID_PATTERN.fullmatch(entry.id) is None:
        raise BadRequestError("在线角色索引包含无效角色 ID。")
    if _SEMVER_PATTERN.fullmatch(entry.version) is None:
        raise BadRequestError("在线角色索引包含无效版本号。")
    if _SEMVER_PATTERN.fullmatch(entry.compatibility.min_tiance_version) is None:
        raise BadRequestError("在线角色索引包含无效兼容版本。")
    if entry.size < 1 or not re.fullmatch(r"[a-f0-9]{64}", entry.sha256):
        raise BadRequestError("在线角色索引包含无效角色包信息。")
    for value, label, maximum in (
        (entry.name, "名称", 80),
        (entry.author, "作者", 80),
        (entry.summary, "简介", 300),
        (entry.license, "许可证", 80),
    ):
        if not value.strip() or len(value) > maximum:
            raise BadRequestError(f"在线角色索引包含无效{label}。")
    resolve_role_market_asset_url(source, entry.package_url)


def _installed_market_roles(
    catalog: FileProjectCatalog,
) -> dict[str, tuple[tuple[Project, str], ...]]:
    collected: dict[str, list[tuple[Project, str]]] = {}
    for project in catalog.list_projects():
        try:
            payload = json.loads(
                (Path(project.root_path) / "manifest.json").read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict) or payload.get("kind") != "tiance-role-package":
            continue
        role_id = payload.get("id")
        version = payload.get("version")
        if (
            not isinstance(role_id, str)
            or _ROLE_ID_PATTERN.fullmatch(role_id) is None
            or not isinstance(version, str)
            or _SEMVER_PATTERN.fullmatch(version) is None
        ):
            continue
        collected.setdefault(role_id, []).append((project, version))
    return {
        role_id: tuple(sorted(items, key=lambda item: item[0].project_id))
        for role_id, items in collected.items()
    }


def _require_entry(index: RoleMarketRemoteIndex, role_id: str) -> RoleMarketRoleEntry:
    entry = next((item for item in index.roles if item.id == role_id), None)
    if entry is None:
        raise NotFoundError("在线角色不存在。")
    return entry


def _normalize_filters(filters: RoleMarketFilterSettings) -> RoleMarketFilterSettings:
    return RoleMarketFilterSettings(
        authors=sorted({value.strip() for value in filters.authors if value.strip()}),
        statuses=sorted(set(filters.statuses)),
    )


def _version_tuple(version: str) -> tuple[int, int, int]:
    match = _SEMVER_PATTERN.fullmatch(version)
    if match is None:
        return 0, 0, 0
    return tuple(int(value) for value in match.groups())


def _atomic_copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
    try:
        shutil.copy2(source, temporary)
        atomic_replace_path(temporary, target)
    finally:
        with suppress(OSError):
            temporary.unlink(missing_ok=True)


@lru_cache
def get_role_market_application_service() -> RoleMarketApplicationService:
    settings = get_settings()
    catalog = get_project_repository().get_file_catalog(ProjectKind.ROLE)
    if catalog is None:
        raise RuntimeError("角色集未配置文件目录索引。")
    return RoleMarketApplicationService(
        app_version=settings.app_version,
        roles_root=settings.roles_data_path,
        settings_repository=get_role_market_settings_repository(),
        cache_repository=RoleMarketCacheRepository(
            settings.roles_data_path / ".market-cache",
        ),
        remote_client=RoleMarketRemoteClient(),
        archive=RolePackageArchive(),
        catalog=catalog,
        project_service=get_project_service(),
        project_creation_service=get_project_creation_application_service(),
    )
