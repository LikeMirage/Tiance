from functools import lru_cache
from pathlib import Path

from app.core.config import get_settings
from app.repositories.online_market_settings_repository import OnlineMarketSettingsRepository
from app.schemas.tools.tool_market import ToolMarketSettingsResponse


TOOL_MARKET_SETTINGS_FILE = "market-settings.json"
DEFAULT_TOOL_MARKET_SOURCE = "https://likemirage.github.io/Tiance-tools"


class ToolMarketSettingsRepository(
    OnlineMarketSettingsRepository[ToolMarketSettingsResponse]
):
    def __init__(self, settings_path: Path) -> None:
        super().__init__(
            settings_path,
            settings_model=ToolMarketSettingsResponse,
            default_source=DEFAULT_TOOL_MARKET_SOURCE,
        )


@lru_cache
def get_tool_market_settings_repository() -> ToolMarketSettingsRepository:
    return ToolMarketSettingsRepository(
        get_settings().tools_data_path / TOOL_MARKET_SETTINGS_FILE
    )
