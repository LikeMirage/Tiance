from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Callable, Generic, Protocol, TypeVar

from app.core.errors import BadRequestError


IndexT = TypeVar("IndexT")
ResponseT = TypeVar("ResponseT")


class _MarketSettings(Protocol):
    source: str


class _MarketSettingsRepository(Protocol):
    def get_settings(self) -> _MarketSettings: ...
    def save_source(self, source: str) -> _MarketSettings: ...


class _MarketCacheRepository(Protocol):
    def read_index(self, source: str) -> dict[str, object] | None: ...
    def save_index(self, source: str, payload: dict[str, object]) -> None: ...


class _MarketRemoteClient(Protocol):
    async def fetch_index(self, source: str) -> dict[str, object]: ...


@dataclass(frozen=True, slots=True)
class OnlineMarketIndexLoad(Generic[IndexT]):
    index: IndexT
    source: str
    cached: bool

    async def build_response(
        self,
        builder: Callable[..., ResponseT],
    ) -> ResponseT:
        return await asyncio.to_thread(
            builder,
            self.index,
            source=self.source,
            cached=self.cached,
        )


class OnlineMarketIndexGateway(Generic[IndexT]):
    """在线市场共用的连接、索引校验、缓存写入与离线回退流程。"""

    def __init__(
        self,
        *,
        settings_repository: _MarketSettingsRepository,
        cache_repository: _MarketCacheRepository,
        remote_client: _MarketRemoteClient,
        normalize_source: Callable[[str], str],
        validate_index: Callable[[str, dict[str, object]], IndexT],
        fallback_errors: tuple[type[Exception], ...],
    ) -> None:
        self._settings_repository = settings_repository
        self._cache_repository = cache_repository
        self._remote_client = remote_client
        self._normalize_source = normalize_source
        self._validate_index = validate_index
        self._fallback_errors = fallback_errors

    async def connect(self, raw_source: str) -> OnlineMarketIndexLoad[IndexT]:
        source = self._normalize_source(raw_source)
        index = await self._fetch_remote_index(source)
        await asyncio.to_thread(self._settings_repository.save_source, source)
        return OnlineMarketIndexLoad(index=index, source=source, cached=False)

    async def get_index(self) -> OnlineMarketIndexLoad[IndexT]:
        settings = await asyncio.to_thread(self._settings_repository.get_settings)
        source = self._normalize_source(settings.source)
        try:
            index = await self._fetch_remote_index(source)
            return OnlineMarketIndexLoad(index=index, source=source, cached=False)
        except self._fallback_errors:
            index = await asyncio.to_thread(self._read_cached_index, source)
            if index is None:
                raise
            return OnlineMarketIndexLoad(index=index, source=source, cached=True)

    async def fetch(self, raw_source: str) -> OnlineMarketIndexLoad[IndexT]:
        source = self._normalize_source(raw_source)
        index = await self._fetch_remote_index(source)
        return OnlineMarketIndexLoad(index=index, source=source, cached=False)

    async def read_cached(self, raw_source: str) -> OnlineMarketIndexLoad[IndexT] | None:
        source = self._normalize_source(raw_source)
        index = await asyncio.to_thread(self._read_cached_index, source)
        if index is None:
            return None
        return OnlineMarketIndexLoad(index=index, source=source, cached=True)

    async def _fetch_remote_index(self, source: str) -> IndexT:
        payload = await self._remote_client.fetch_index(source)
        index = await asyncio.to_thread(self._validate_index, source, payload)
        await asyncio.to_thread(self._cache_repository.save_index, source, payload)
        return index

    def _read_cached_index(self, source: str) -> IndexT | None:
        payload = self._cache_repository.read_index(source)
        if payload is None:
            return None
        try:
            return self._validate_index(source, payload)
        except (BadRequestError, ValueError):
            return None
