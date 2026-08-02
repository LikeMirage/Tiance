from pathlib import Path

from app.repositories.online_market_cache_repository import OnlineMarketCacheRepository


class ProjectMarketCacheRepository(OnlineMarketCacheRepository):
    def __init__(self, cache_root: Path) -> None:
        super().__init__(cache_root, sources_directory="sources")
