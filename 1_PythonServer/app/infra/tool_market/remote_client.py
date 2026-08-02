from __future__ import annotations

from pathlib import Path

from app.core.errors import BadRequestError
from app.infra.online_market import OnlineMarketRemoteClient


MAX_TOOL_MARKET_INDEX_BYTES = 1024 * 1024
MAX_TOOL_PACKAGE_BYTES = 64 * 1024 * 1024


class ToolMarketConnectionError(BadRequestError):
    pass


_REMOTE = OnlineMarketRemoteClient(
    resource_label="工具",
    maximum_index_bytes=MAX_TOOL_MARKET_INDEX_BYTES,
    maximum_package_bytes=MAX_TOOL_PACKAGE_BYTES,
    connection_error_type=ToolMarketConnectionError,
)


class ToolMarketRemoteClient:
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


def normalize_tool_market_source(raw_source: str) -> str:
    return _REMOTE.normalize_source(raw_source)


def resolve_tool_market_asset_url(source: str, raw_url: str) -> str:
    return _REMOTE.resolve_asset_url(source, raw_url)
