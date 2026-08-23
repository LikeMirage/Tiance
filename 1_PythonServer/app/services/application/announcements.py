from __future__ import annotations

import asyncio
from datetime import datetime
from functools import lru_cache
import json
import mimetypes
from pathlib import PurePosixPath
import re

from pydantic import ValidationError

from app.core.config import get_settings
from app.core.errors import AppError, BadRequestError, ConflictError, NotFoundError
from app.infra.online_market.remote_client import OnlineMarketRemoteClient
from app.repositories.announcement_cache_repository import AnnouncementCacheRepository
from app.repositories.announcement_state_repository import AnnouncementStateRepository
from app.repositories.announcement_settings_repository import AnnouncementSettingsRepository
from app.schemas.announcements import (
    AnnouncementCheckResponse,
    AnnouncementContentResponse,
    AnnouncementItem,
    AnnouncementReadResponse,
    AnnouncementRootIndex,
    AnnouncementSettings,
    AnnouncementYearIndex,
)
from app.services.application.online_market import OnlineMarketIndexGateway


DEFAULT_ANNOUNCEMENT_SOURCE = "https://github.com/LikeMirage/Tiance-announcements.git"
ROOT_INDEX_MAXIMUM_BYTES = 1024 * 1024
YEAR_INDEX_MAXIMUM_BYTES = 4 * 1024 * 1024
CONTENT_MAXIMUM_BYTES = 2 * 1024 * 1024
ASSET_MAXIMUM_BYTES = 25 * 1024 * 1024
_ANNOUNCEMENT_ID = re.compile(r"^(\d{4})-(\d{2})-(\d{2})-([1-9]\d*)$")


class AnnouncementConnectionError(BadRequestError):
    pass


class AnnouncementCatalogEmptyError(AppError):
    def __init__(self) -> None:
        super().__init__(
            "公告仓库尚未发布可用索引，或当前账号无权读取。",
            code="announcement_catalog_empty",
            status_code=404,
        )


class AnnouncementApplicationService:
    def __init__(self) -> None:
        settings = get_settings()
        self._settings_repository = AnnouncementSettingsRepository(
            settings.announcements_data_path / "settings.json",
            default_source=DEFAULT_ANNOUNCEMENT_SOURCE,
        )
        self._state_repository = AnnouncementStateRepository(
            settings.announcements_data_path / "read-state.json"
        )
        self._cache_repository = AnnouncementCacheRepository(
            settings.cache_data_path / "announcements"
        )
        self._remote = OnlineMarketRemoteClient(
            resource_label="公告",
            maximum_index_bytes=ROOT_INDEX_MAXIMUM_BYTES,
            maximum_package_bytes=ASSET_MAXIMUM_BYTES,
            connection_error_type=AnnouncementConnectionError,
        )
        self._index_gateway = OnlineMarketIndexGateway(
            settings_repository=self._settings_repository,
            cache_repository=self._cache_repository,
            remote_client=self._remote,
            normalize_source=self._remote.normalize_source,
            validate_index=_validate_root_index,
            fallback_errors=(AnnouncementConnectionError,),
        )
        self._check_lock = asyncio.Lock()

    async def get_settings(self) -> AnnouncementSettings:
        return await asyncio.to_thread(self._settings_repository.get_settings)

    async def update_settings(self, check_on_startup: bool) -> AnnouncementSettings:
        current = await self.get_settings()
        updated = current.model_copy(update={"check_on_startup": check_on_startup})
        return await asyncio.to_thread(self._settings_repository.save_settings, updated)

    async def check(self) -> AnnouncementCheckResponse:
        async with self._check_lock:
            try:
                root_load = await self._index_gateway.get_index()
            except AnnouncementConnectionError as exc:
                if isinstance(exc.details, dict) and exc.details.get("upstreamStatus") == 404:
                    raise AnnouncementCatalogEmptyError() from exc
                raise
            root = root_load.index
            year_reference = next(
                item for item in root.years if item.year == root.latest_announcement_year
            )
            year_index = await self._load_year(
                source=root_load.source,
                year=year_reference.year,
                index_path=year_reference.index_path,
                remote_first=not root_load.cached,
            )
            latest = next(
                (
                    item
                    for item in year_index.index.announcements
                    if item.id == root.latest_announcement_id
                ),
                None,
            )
            if latest is None or latest.status != "published":
                raise BadRequestError("公告根索引指向的最新公告不存在或未发布。")
            state = await asyncio.to_thread(self._state_repository.get_state)
            latest = _with_read_state(latest, state)
            last_successful = state.get("lastSuccessfulCheckAt")
            if not root_load.cached and not year_index.cached:
                last_successful = await asyncio.to_thread(
                    self._state_repository.set_last_successful_check
                )
            decorated_year = _decorate_year(year_index.index, state, year_index.cached)
            return AnnouncementCheckResponse(
                root=root,
                latest_year=decorated_year,
                latest=latest,
                latest_unread=not latest.read,
                cached=root_load.cached or year_index.cached,
                last_successful_check_at=(
                    last_successful if isinstance(last_successful, str) else None
                ),
            )

    async def get_year(self, year: int) -> AnnouncementYearIndex:
        root_load = await self._index_gateway.read_cached(
            (await self.get_settings()).source
        )
        if root_load is None:
            root_load = await self._index_gateway.get_index()
        reference = next((item for item in root_load.index.years if item.year == year), None)
        if reference is None:
            raise NotFoundError("公告年度索引不存在。")
        loaded = await self._load_year(
            source=root_load.source,
            year=year,
            index_path=reference.index_path,
            remote_first=True,
        )
        state = await asyncio.to_thread(self._state_repository.get_state)
        return _decorate_year(loaded.index, state, loaded.cached)

    async def get_content(
        self,
        announcement_id: str,
        revision: int,
    ) -> AnnouncementContentResponse:
        source, item = await self._resolve_item(announcement_id, revision)
        cached_payload = await asyncio.to_thread(
            self._cache_repository.read_bytes, source, item.content_path
        )
        if cached_payload is not None:
            content = _decode_content(cached_payload)
            cached = True
        else:
            payload = await self._remote.download_resource(
                source=source,
                resource_url=item.content_path,
                maximum_bytes=CONTENT_MAXIMUM_BYTES,
                accept="text/markdown, text/plain",
            )
            content = _decode_content(payload)
            await asyncio.to_thread(
                self._cache_repository.save_bytes,
                source,
                item.content_path,
                payload,
            )
            cached = False
        state = await asyncio.to_thread(self._state_repository.get_state)
        return AnnouncementContentResponse(
            announcement=_with_read_state(item, state),
            content=content,
            cached=cached,
        )

    async def mark_read(self, announcement_id: str, revision: int) -> AnnouncementReadResponse:
        _parse_announcement_id(announcement_id)
        if revision < 1:
            raise BadRequestError("公告修订号必须为正整数。")
        read_at = await asyncio.to_thread(
            self._state_repository.mark_read,
            announcement_id,
            revision,
        )
        return AnnouncementReadResponse(
            announcement_id=announcement_id,
            revision=revision,
            read_at=read_at,
        )

    async def get_asset(
        self,
        announcement_id: str,
        revision: int,
        asset_path: str,
    ) -> tuple[bytes, str | None]:
        source, item = await self._resolve_item(announcement_id, revision)
        normalized_asset = _validate_asset_path(asset_path)
        content_parent = PurePosixPath(item.content_path).parent
        resource_path = str(content_parent / normalized_asset)
        cached_payload = await asyncio.to_thread(
            self._cache_repository.read_bytes, source, resource_path
        )
        if cached_payload is None:
            cached_payload = await self._remote.download_resource(
                source=source,
                resource_url=resource_path,
                maximum_bytes=ASSET_MAXIMUM_BYTES,
                accept="image/*, application/octet-stream",
            )
            await asyncio.to_thread(
                self._cache_repository.save_bytes,
                source,
                resource_path,
                cached_payload,
            )
        media_type, _encoding = mimetypes.guess_type(normalized_asset)
        return cached_payload, media_type

    async def _resolve_item(
        self,
        announcement_id: str,
        revision: int,
    ) -> tuple[str, AnnouncementItem]:
        year, _month, _day, _sequence = _parse_announcement_id(announcement_id)
        if revision < 1:
            raise BadRequestError("公告修订号必须为正整数。")
        settings = await self.get_settings()
        root_load = await self._index_gateway.read_cached(settings.source)
        if root_load is None:
            root_load = await self._index_gateway.get_index()
        reference = next((item for item in root_load.index.years if item.year == year), None)
        if reference is None:
            raise NotFoundError("公告不存在。")
        year_load = await self._load_year(
            source=root_load.source,
            year=year,
            index_path=reference.index_path,
            remote_first=False,
        )
        item = next(
            (candidate for candidate in year_load.index.announcements if candidate.id == announcement_id),
            None,
        )
        if item is None:
            raise NotFoundError("公告不存在。")
        if item.revision != revision:
            raise ConflictError("公告修订号已变化，请重新加载公告索引。")
        return root_load.source, item

    async def _load_year(
        self,
        *,
        source: str,
        year: int,
        index_path: str,
        remote_first: bool,
    ) -> "_YearLoad":
        if not remote_first:
            cached = await asyncio.to_thread(
                self._cache_repository.read_json, source, index_path
            )
            if cached is not None:
                try:
                    return _YearLoad(_validate_year_index(year, cached), True)
                except BadRequestError:
                    pass
        try:
            payload_bytes = await self._remote.download_resource(
                source=source,
                resource_url=index_path,
                maximum_bytes=YEAR_INDEX_MAXIMUM_BYTES,
                accept="application/json",
            )
        except AnnouncementConnectionError:
            cached = await asyncio.to_thread(
                self._cache_repository.read_json, source, index_path
            )
            if cached is None:
                raise
            return _YearLoad(_validate_year_index(year, cached), True)
        payload = _decode_json_object(payload_bytes, "公告年度索引")
        index = _validate_year_index(year, payload)
        await asyncio.to_thread(
            self._cache_repository.save_json, source, index_path, payload
        )
        return _YearLoad(index, False)


class _YearLoad:
    def __init__(self, index: AnnouncementYearIndex, cached: bool) -> None:
        self.index = index
        self.cached = cached


def _validate_root_index(_source: str, payload: dict[str, object]) -> AnnouncementRootIndex:
    try:
        index = AnnouncementRootIndex.model_validate(payload)
    except ValidationError as exc:
        raise BadRequestError("公告根索引格式无效。") from exc
    if index.schema_version != 1:
        raise BadRequestError("公告根索引版本不受支持。")
    _parse_datetime(index.updated_at, "公告根索引更新时间")
    latest_year, _month, _day, _sequence = _parse_announcement_id(
        index.latest_announcement_id
    )
    if latest_year != index.latest_announcement_year:
        raise BadRequestError("公告根索引的最新公告年份不一致。")
    seen_years: set[int] = set()
    for reference in index.years:
        if reference.year in seen_years:
            raise BadRequestError("公告根索引包含重复年份。")
        seen_years.add(reference.year)
        if reference.index_path != f"indexes/{reference.year}.json":
            raise BadRequestError("公告年度索引路径不符合发布契约。")
    if index.latest_announcement_year not in seen_years:
        raise BadRequestError("公告根索引缺少最新公告所在年份。")
    return index


def _validate_year_index(year: int, payload: dict[str, object]) -> AnnouncementYearIndex:
    try:
        index = AnnouncementYearIndex.model_validate(payload)
    except ValidationError as exc:
        raise BadRequestError("公告年度索引格式无效。") from exc
    if index.schema_version != 1 or index.year != year:
        raise BadRequestError("公告年度索引版本或年份无效。")
    _parse_datetime(index.updated_at, "公告年度索引更新时间")
    seen_ids: set[str] = set()
    validated_items: list[AnnouncementItem] = []
    for item in index.announcements:
        item_year, month, day, sequence = _parse_announcement_id(item.id)
        if item_year != year or item.id in seen_ids:
            raise BadRequestError("公告年度索引包含重复或跨年度公告。")
        seen_ids.add(item.id)
        if item.revision < 1 or not item.title.strip():
            raise BadRequestError("公告标题或修订号无效。")
        published_at = _parse_datetime(item.published_at, "公告发布时间")
        if (published_at.year, published_at.month, published_at.day) != (
            item_year,
            month,
            day,
        ):
            raise BadRequestError("公告 ID 日期与发布时间不一致。")
        expected_path = (
            f"announcements/{year}/{month:02d}-{day:02d}-{sequence}/"
            f"r{item.revision}/content.md"
        )
        if item.content_path != expected_path:
            raise BadRequestError("公告正文路径不符合发布契约。")
        validated_items.append(item.model_copy(update={"read": False}))
    return index.model_copy(
        update={
            "announcements": sorted(
                validated_items,
                key=lambda item: (_parse_datetime(item.published_at, "公告发布时间"), item.id),
                reverse=True,
            ),
            "cached": False,
        }
    )


def _decorate_year(
    index: AnnouncementYearIndex,
    state: dict[str, object],
    cached: bool,
) -> AnnouncementYearIndex:
    return index.model_copy(
        update={
            "announcements": [_with_read_state(item, state) for item in index.announcements],
            "cached": cached,
        }
    )


def _with_read_state(item: AnnouncementItem, state: dict[str, object]) -> AnnouncementItem:
    entries = state.get("readAnnouncements")
    entry = entries.get(item.id) if isinstance(entries, dict) else None
    read = isinstance(entry, dict) and entry.get("revision") == item.revision
    return item.model_copy(update={"read": read})


def _parse_announcement_id(value: str) -> tuple[int, int, int, int]:
    match = _ANNOUNCEMENT_ID.fullmatch(value)
    if match is None:
        raise BadRequestError("公告 ID 格式无效。")
    year, month, day, sequence = (int(part) for part in match.groups())
    try:
        datetime(year, month, day)
    except ValueError as exc:
        raise BadRequestError("公告 ID 日期无效。") from exc
    return year, month, day, sequence


def _parse_datetime(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise BadRequestError(f"{label}无效。") from exc
    if parsed.tzinfo is None:
        raise BadRequestError(f"{label}必须包含时区。")
    return parsed


def _decode_json_object(payload: bytes, label: str) -> dict[str, object]:
    try:
        decoded = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BadRequestError(f"{label}不是有效 JSON。") from exc
    if not isinstance(decoded, dict):
        raise BadRequestError(f"{label}格式无效。")
    return decoded


def _decode_content(payload: bytes) -> str:
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BadRequestError("公告正文必须使用 UTF-8 编码。") from exc


def _validate_asset_path(asset_path: str) -> str:
    normalized = PurePosixPath(asset_path.replace("\\", "/"))
    if (
        normalized.is_absolute()
        or len(normalized.parts) < 2
        or normalized.parts[0] != "assets"
        or any(part in {"", ".", ".."} for part in normalized.parts)
    ):
        raise BadRequestError("公告图片只能引用正文同修订目录下的 assets 路径。")
    return str(normalized)


@lru_cache
def get_announcement_application_service() -> AnnouncementApplicationService:
    return AnnouncementApplicationService()
