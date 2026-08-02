from functools import lru_cache
from pathlib import Path

from app.core.config import get_settings
from app.repositories.online_market_settings_repository import OnlineMarketSettingsRepository
from app.schemas.themes.theme_market import ThemeMarketSettingsResponse


THEME_MARKET_SETTINGS_FILE = "market-settings.json"
DEFAULT_THEME_MARKET_SOURCE = "https://likemirage.github.io/Tiance-themes"


class ThemeMarketSettingsRepository(
    OnlineMarketSettingsRepository[ThemeMarketSettingsResponse]
):
    def __init__(self, settings_path: Path) -> None:
        super().__init__(
            settings_path,
            settings_model=ThemeMarketSettingsResponse,
            default_source=DEFAULT_THEME_MARKET_SOURCE,
        )


@lru_cache
def get_theme_market_settings_repository() -> ThemeMarketSettingsRepository:
    return ThemeMarketSettingsRepository(
        get_settings().themes_data_path / THEME_MARKET_SETTINGS_FILE
    )
