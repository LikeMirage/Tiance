from functools import lru_cache
from pathlib import Path

from app.core.config import get_settings
from app.repositories.online_market_settings_repository import OnlineMarketSettingsRepository
from app.schemas.llm.provider_market import ProviderMarketSettingsResponse


PROVIDER_MARKET_SETTINGS_FILE = "market-settings.json"
DEFAULT_PROVIDER_MARKET_SOURCE = "https://likemirage.github.io/Tiance-providers"


class ProviderMarketSettingsRepository(
    OnlineMarketSettingsRepository[ProviderMarketSettingsResponse]
):
    def __init__(self, settings_path: Path) -> None:
        super().__init__(
            settings_path,
            settings_model=ProviderMarketSettingsResponse,
            default_source=DEFAULT_PROVIDER_MARKET_SOURCE,
        )


@lru_cache
def get_provider_market_settings_repository() -> ProviderMarketSettingsRepository:
    return ProviderMarketSettingsRepository(
        get_settings().providers_data_path / PROVIDER_MARKET_SETTINGS_FILE
    )
