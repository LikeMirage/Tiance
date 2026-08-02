from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
import re
from urllib.parse import urlsplit
from uuid import uuid4

from app.core.config import get_settings
from app.core.errors import AppError, BadRequestError, ConflictError, NotFoundError
from app.domain.project import ProjectKind
from app.infra.project_market.package_archive import (
    ProjectPackageArchive,
    remove_project_market_staging_path,
)
from app.infra.project_market.remote_client import (
    ProjectMarketConnectionError,
    ProjectMarketRemoteClient,
    normalize_project_market_source,
    resolve_project_asset_url,
    resolve_project_download,
)
from app.repositories.project.project_market_cache_repository import (
    ProjectMarketCacheRepository,
)
from app.repositories.project import FileProjectCatalog, get_project_repository
from app.repositories.project.project_market_settings_repository import (
    DEFAULT_EXPERIENCE_MARKET_SOURCE,
    DEFAULT_KNOWLEDGE_MARKET_SOURCE,
    DEFAULT_PROJECT_MARKET_SOURCE,
    ProjectMarketSettingsRepository,
    get_experience_market_settings_repository,
    get_knowledge_market_settings_repository,
    get_project_market_settings_repository,
)
from app.schemas.project.project_market import (
    ProjectMarketFilterSettings,
    ProjectMarketIndexResponse,
    ProjectMarketInstallOperation,
    ProjectMarketInstallResult,
    ProjectMarketProjectEntry,
    ProjectMarketProjectResponse,
    ProjectMarketRemoteIndex,
    ProjectMarketSettingsResponse,
)
from app.services.application.project_creation import (
    ProjectCreationApplicationService,
    get_project_creation_application_service,
)
from app.services.application.project_market_snapshot import (
    prepare_project_market_snapshot,
    read_project_market_origin,
)
from app.services.application.online_market import OnlineMarketIndexGateway
from app.services.project.projects import ProjectService, get_project_service


_MARKET_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_SEMVER_PATTERN = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
_PREVIEW_SUFFIXES = frozenset({".avif", ".jpeg", ".jpg", ".png", ".webp"})


@dataclass(frozen=True, slots=True)
class ProjectMarketPolicy:
    project_kind: ProjectKind
    index_kind: str
    default_source: str
    preview_api_prefix: str
    category_error: str


@dataclass(slots=True)
class _InstallOperationState:
    operation_id: str
    market_project_id: str
    phase: str = "queued"
    error: str | None = None
    result: ProjectMarketInstallResult | None = None

    def response(self) -> ProjectMarketInstallOperation:
        return ProjectMarketInstallOperation(
            operationId=self.operation_id,
            marketProjectId=self.market_project_id,
            phase=self.phase,
            error=self.error,
            result=self.result,
        )


class ProjectMarketApplicationService:
    def __init__(
        self,
        *,
        settings_repository: ProjectMarketSettingsRepository,
        cache_repository: ProjectMarketCacheRepository,
        remote_client: ProjectMarketRemoteClient,
        archive: ProjectPackageArchive,
        catalog: FileProjectCatalog,
        project_service: ProjectService,
        creation_service: ProjectCreationApplicationService,
        policy: ProjectMarketPolicy,
    ) -> None:
        self._settings_repository = settings_repository
        self._cache_repository = cache_repository
        self._remote_client = remote_client
        self._archive = archive
        self._catalog = catalog
        self._project_service = project_service
        self._creation_service = creation_service
        self._policy = policy
        self._index_gateway = OnlineMarketIndexGateway[ProjectMarketRemoteIndex](
            settings_repository=settings_repository,
            cache_repository=cache_repository,
            remote_client=remote_client,
            normalize_source=normalize_project_market_source,
            validate_index=self._validate_index_payload,
            fallback_errors=(ProjectMarketConnectionError,),
        )
        self._operations: dict[str, _InstallOperationState] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._active_market_projects: set[str] = set()
        self._operation_lock = asyncio.Lock()

    def prepare(self) -> None:
        self._settings_repository.ensure_settings_file()
        operations_root = self._cache_repository.operations_root
        if operations_root.exists():
            for child in operations_root.iterdir():
                if child.is_dir():
                    remove_project_market_staging_path(
                        child,
                        allowed_root=operations_root,
                    )
                else:
                    child.unlink(missing_ok=True)
        operations_root.mkdir(parents=True, exist_ok=True)

    async def close(self) -> None:
        tasks = tuple(self._tasks.items())
        for operation_id, task in tasks:
            state = self._operations.get(operation_id)
            if state is not None and state.phase in {"queued", "downloading"}:
                task.cancel()
        for operation_id, task in tasks:
            with suppress(asyncio.CancelledError, Exception):
                await task
            state = self._operations.get(operation_id)
            if state is not None and task.cancelled() and state.phase != "failed":
                state.phase = "failed"
                state.error = "项目安装已停止。"
                self._active_market_projects.discard(state.market_project_id)
                remove_project_market_staging_path(
                    self._cache_repository.operations_root / operation_id,
                    allowed_root=self._cache_repository.operations_root,
                )
        self._tasks.clear()
        self._active_market_projects.clear()

    def get_settings(self) -> ProjectMarketSettingsResponse:
        return self._settings_repository.get_settings()

    def save_filters(
        self,
        filters: ProjectMarketFilterSettings,
    ) -> ProjectMarketSettingsResponse:
        return self._settings_repository.save_filters(_normalize_filters(filters))

    def select_source(self, source: str) -> ProjectMarketSettingsResponse:
        return self._settings_repository.save_source(normalize_project_market_source(source))

    async def connect(self, source: str) -> ProjectMarketIndexResponse:
        loaded = await self._index_gateway.connect(source)
        return await loaded.build_response(self._to_response)

    async def restore_default_source(self) -> ProjectMarketIndexResponse:
        return await self.connect(self._policy.default_source)

    async def get_index(self) -> ProjectMarketIndexResponse:
        loaded = await self._index_gateway.get_index()
        return await loaded.build_response(self._to_response)

    async def get_preview_path(self, market_project_id: str) -> Path:
        _require_market_project_id(market_project_id)
        source = normalize_project_market_source(self.get_settings().source)
        loaded = await self._index_gateway.read_cached(source)
        if loaded is None:
            loaded = await self._index_gateway.fetch(source)
        remote_index = loaded.index
        entry = _require_entry(remote_index, market_project_id)
        if not entry.preview_url:
            raise NotFoundError("在线项目没有预览图。")
        suffix = Path(urlsplit(entry.preview_url).path).suffix.lower()
        if suffix not in _PREVIEW_SUFFIXES:
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
            default_ref=remote_index.default_ref,
        )
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = cache_path.with_name(f".{cache_path.name}.{uuid4().hex}.tmp")
        try:
            temporary_path.write_bytes(content)
            _verify_preview_image(temporary_path)
            temporary_path.replace(cache_path)
        finally:
            temporary_path.unlink(missing_ok=True)
        return cache_path

    async def start_install(
        self,
        *,
        market_project_id: str,
        category_id: str,
    ) -> ProjectMarketInstallOperation:
        _require_market_project_id(market_project_id)
        category = self._project_service.get_project_category(category_id)
        if category is None or category.category_kind is not self._policy.project_kind:
            raise BadRequestError(self._policy.category_error)

        async with self._operation_lock:
            if market_project_id in self._active_market_projects:
                raise ConflictError("该项目正在安装，请勿重复操作。")
            source = normalize_project_market_source(self.get_settings().source)
            if _find_installed_project(
                self._catalog,
                source=source,
                market_project_id=market_project_id,
            ) is not None:
                raise ConflictError("该在线项目已经安装。")
            operation_id = uuid4().hex
            state = _InstallOperationState(
                operation_id=operation_id,
                market_project_id=market_project_id,
            )
            self._operations[operation_id] = state
            self._active_market_projects.add(market_project_id)
            task = asyncio.create_task(
                self._run_install(
                    state,
                    source=source,
                    category_id=category.category_id,
                )
            )
            self._tasks[operation_id] = task
            task.add_done_callback(
                lambda _task, key=operation_id: self._tasks.pop(key, None)
            )
            return state.response()

    def get_operation(self, operation_id: str) -> ProjectMarketInstallOperation:
        state = self._operations.get(operation_id)
        if state is None:
            raise NotFoundError("项目安装任务不存在。")
        return state.response()

    async def _run_install(
        self,
        state: _InstallOperationState,
        *,
        source: str,
        category_id: str,
    ) -> None:
        operation_root = self._cache_repository.operations_root / state.operation_id
        installed_project_id: str | None = None
        staged_project_root: Path | None = None
        try:
            operation_root.mkdir(parents=True, exist_ok=False)
            remote_index = (await self._index_gateway.fetch(source)).index
            entry = _require_entry(remote_index, state.market_project_id)
            if _find_installed_project(
                self._catalog,
                source=source,
                market_project_id=entry.id,
            ) is not None:
                raise ConflictError("该在线项目已经安装。")

            state.phase = "downloading"
            archive_path = operation_root / "package.zip"
            source_path = await self._remote_client.download_package(
                source=source,
                download=entry.download,
                default_ref=remote_index.default_ref,
                target=archive_path,
            )
            state.phase = "extracting"
            staged_project_root = await asyncio.to_thread(
                self._archive.validate_and_extract,
                archive_path=archive_path,
                staging_root=operation_root,
                source_path=source_path,
            )
            state.phase = "importing"
            installed_at = datetime.now(UTC).isoformat()
            installed_project_id = str(uuid4())
            await asyncio.to_thread(
                prepare_project_market_snapshot,
                staged_project_root,
                project_id=installed_project_id,
                project_name=entry.name,
                market_project_id=entry.id,
                source=source,
                version=entry.version,
                installed_at=installed_at,
                project_kind=self._policy.project_kind,
            )
            project = await asyncio.to_thread(
                self._project_service.install_managed_project_snapshot,
                staged_root=staged_project_root,
                project_id=installed_project_id,
                name=entry.name,
                category_id=category_id,
                project_kind=self._policy.project_kind,
            )
            try:
                await asyncio.to_thread(
                    self._creation_service.ensure_initial_conversation,
                    project.project_id,
                )
            except Exception:
                await asyncio.to_thread(
                    self._project_service.rollback_managed_project_snapshot,
                    project.project_id,
                    staged_root=staged_project_root,
                    project_kind=self._policy.project_kind,
                )
                installed_project_id = None
                raise
            state.result = ProjectMarketInstallResult(
                marketProjectId=entry.id,
                projectId=project.project_id,
                categoryId=project.category_id,
                version=entry.version,
            )
            state.phase = "completed"
        except asyncio.CancelledError:
            state.phase = "failed"
            state.error = "项目安装已停止。"
            raise
        except Exception as exc:
            state.phase = "failed"
            state.error = exc.message if isinstance(exc, AppError) else "项目安装失败。"
        finally:
            self._active_market_projects.discard(state.market_project_id)
            if installed_project_id is None or state.phase == "completed":
                remove_project_market_staging_path(
                    operation_root,
                    allowed_root=self._cache_repository.operations_root,
                )

    def _validate_index_payload(
        self,
        source: str,
        payload: dict[str, object],
    ) -> ProjectMarketRemoteIndex:
        return _validate_remote_index(
            source,
            payload,
            expected_kind=self._policy.index_kind,
        )

    def _to_response(
        self,
        index: ProjectMarketRemoteIndex,
        *,
        source: str,
        cached: bool,
    ) -> ProjectMarketIndexResponse:
        projects: list[ProjectMarketProjectResponse] = []
        for entry in index.projects:
            installed = _find_installed_project(
                self._catalog,
                source=source,
                market_project_id=entry.id,
            )
            projects.append(ProjectMarketProjectResponse(
                **entry.model_dump(),
                installationStatus="installed" if installed is not None else "not-installed",
                localProjectId=None if installed is None else installed.project_id,
                previewPath=(
                    f"{self._policy.preview_api_prefix}/{entry.id}"
                    if entry.preview_url
                    else None
                ),
            ))
        return ProjectMarketIndexResponse(
            schemaVersion=1,
            kind=index.kind,
            name=index.name,
            updatedAt=index.updated_at,
            source=source,
            cached=cached,
            projects=projects,
        )


def _validate_remote_index(
    source: str,
    payload: dict[str, object],
    *,
    expected_kind: str,
) -> ProjectMarketRemoteIndex:
    try:
        index = ProjectMarketRemoteIndex.model_validate(payload)
    except ValueError as exc:
        raise BadRequestError("在线项目索引格式无效。") from exc
    if index.kind != expected_kind:
        raise BadRequestError("在线项目索引类型与当前市场不匹配。")
    if len(index.projects) != len({entry.id for entry in index.projects}):
        raise BadRequestError("在线项目索引包含重复项目 ID。")
    for entry in index.projects:
        _validate_entry(source, index.default_ref, entry)
    return index


def _validate_entry(
    source: str,
    default_ref: str,
    entry: ProjectMarketProjectEntry,
) -> None:
    _require_market_project_id(entry.id)
    if not entry.name.strip() or not entry.summary.strip() or not entry.author.strip():
        raise BadRequestError("在线项目索引包含空的项目信息。")
    if _SEMVER_PATTERN.fullmatch(entry.version) is None:
        raise BadRequestError("在线项目索引包含无效版本号。")
    resolve_project_download(source, entry.download, default_ref=default_ref)
    if entry.preview_url:
        resolve_project_asset_url(source, entry.preview_url, default_ref=default_ref)


def _find_installed_project(
    catalog: FileProjectCatalog,
    *,
    source: str,
    market_project_id: str,
):
    for project in catalog.list_projects():
        origin = read_project_market_origin(project.root_path)
        if origin is None:
            continue
        try:
            origin_source = normalize_project_market_source(str(origin.get("source") or ""))
        except BadRequestError:
            continue
        if (
            origin_source == source
            and origin.get("market_project_id") == market_project_id
        ):
            return project
    return None


def _require_entry(
    index: ProjectMarketRemoteIndex,
    market_project_id: str,
) -> ProjectMarketProjectEntry:
    for entry in index.projects:
        if entry.id == market_project_id:
            return entry
    raise NotFoundError("在线项目不存在。")


def _require_market_project_id(value: str) -> None:
    if _MARKET_ID_PATTERN.fullmatch(value) is None:
        raise BadRequestError("在线项目 ID 无效。")


def _normalize_filters(filters: ProjectMarketFilterSettings) -> ProjectMarketFilterSettings:
    return ProjectMarketFilterSettings(
        authors=sorted({value.strip() for value in filters.authors if value.strip()}),
        tags=sorted({value.strip() for value in filters.tags if value.strip()}),
        statuses=sorted(set(filters.statuses)),
    )


def _verify_preview_image(path: Path) -> None:
    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(path) as image:
            if image.width * image.height > 50_000_000:
                raise BadRequestError("项目预览图尺寸超过允许范围。")
            image.verify()
    except BadRequestError:
        raise
    except (OSError, UnidentifiedImageError) as exc:
        raise BadRequestError("项目预览图格式无效。") from exc


@lru_cache
def get_project_market_application_service() -> ProjectMarketApplicationService:
    settings = get_settings()
    catalog = get_project_repository().get_file_catalog(ProjectKind.PROJECT)
    if catalog is None:
        raise RuntimeError("普通项目集未配置文件目录索引。")
    return ProjectMarketApplicationService(
        settings_repository=get_project_market_settings_repository(),
        cache_repository=ProjectMarketCacheRepository(
            settings.projects_data_path / ".market-cache"
        ),
        remote_client=ProjectMarketRemoteClient(),
        archive=ProjectPackageArchive(),
        catalog=catalog,
        project_service=get_project_service(),
        creation_service=get_project_creation_application_service(),
        policy=ProjectMarketPolicy(
            project_kind=ProjectKind.PROJECT,
            index_kind="tiance-project-market",
            default_source=DEFAULT_PROJECT_MARKET_SOURCE,
            preview_api_prefix="/api/projects/market/previews",
            category_error="请选择有效的普通项目分类。",
        ),
    )


@lru_cache
def get_knowledge_market_application_service() -> ProjectMarketApplicationService:
    settings = get_settings()
    catalog = get_project_repository().get_file_catalog(ProjectKind.KNOWLEDGE)
    if catalog is None:
        raise RuntimeError("知识集未配置文件目录索引。")
    return ProjectMarketApplicationService(
        settings_repository=get_knowledge_market_settings_repository(),
        cache_repository=ProjectMarketCacheRepository(
            settings.knowledge_data_path / ".market-cache"
        ),
        remote_client=ProjectMarketRemoteClient(),
        archive=ProjectPackageArchive(),
        catalog=catalog,
        project_service=get_project_service(),
        creation_service=get_project_creation_application_service(),
        policy=ProjectMarketPolicy(
            project_kind=ProjectKind.KNOWLEDGE,
            index_kind="tiance-knowledge-market",
            default_source=DEFAULT_KNOWLEDGE_MARKET_SOURCE,
            preview_api_prefix="/api/knowledge/market/previews",
            category_error="请选择有效的知识分类。",
        ),
    )


@lru_cache
def get_experience_market_application_service() -> ProjectMarketApplicationService:
    settings = get_settings()
    catalog = get_project_repository().get_file_catalog(ProjectKind.EXPERIENCE)
    if catalog is None:
        raise RuntimeError("经验集未配置文件目录索引。")
    return ProjectMarketApplicationService(
        settings_repository=get_experience_market_settings_repository(),
        cache_repository=ProjectMarketCacheRepository(
            settings.experience_data_path / ".market-cache"
        ),
        remote_client=ProjectMarketRemoteClient(),
        archive=ProjectPackageArchive(),
        catalog=catalog,
        project_service=get_project_service(),
        creation_service=get_project_creation_application_service(),
        policy=ProjectMarketPolicy(
            project_kind=ProjectKind.EXPERIENCE,
            index_kind="tiance-experience-market",
            default_source=DEFAULT_EXPERIENCE_MARKET_SOURCE,
            preview_api_prefix="/api/experience/market/previews",
            category_error="请选择有效的经验分类。",
        ),
    )
