from __future__ import annotations

from pathlib import Path

from app.infra.online_market import OnlineMarketRemoteClient


MAX_MARKET_INDEX_BYTES = 2 * 1024 * 1024
MAX_THEME_PACKAGE_BYTES = 32 * 1024 * 1024
MAX_THEME_PREVIEW_BYTES = 3 * 1024 * 1024


_REMOTE = OnlineMarketRemoteClient(
    resource_label="主题",
    maximum_index_bytes=MAX_MARKET_INDEX_BYTES,
    maximum_package_bytes=MAX_THEME_PACKAGE_BYTES,
    allow_asset_query=True,
)


class ThemeMarketRemoteClient:
    async def fetch_index(self, source: str) -> dict[str, object]:
        return await _REMOTE.fetch_index(source)

    async def download_package(
        self,
        *,
        source: str,
        package_url: str,
        expected_size: int,
        expected_sha256: str,
        target: Path,
    ) -> None:
        await _REMOTE.download_package(
            source=source,
            package_url=package_url,
            expected_size=expected_size,
            expected_sha256=expected_sha256,
            target=target,
        )

    async def download_preview(self, *, source: str, preview_url: str) -> bytes:
        return await _REMOTE.download_resource(
            source=source,
            resource_url=preview_url,
            maximum_bytes=MAX_THEME_PREVIEW_BYTES,
            accept="image/*",
        )


def normalize_market_source(raw_source: str) -> str:
    return _REMOTE.normalize_source(raw_source)


def resolve_market_asset_url(source: str, raw_url: str) -> str:
    return _REMOTE.resolve_asset_url(source, raw_url)
