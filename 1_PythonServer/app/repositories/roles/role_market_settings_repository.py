from functools import lru_cache
from pathlib import Path

from app.core.config import get_settings
from app.repositories.online_market_settings_repository import OnlineMarketSettingsRepository
from app.schemas.roles.role_market import RoleMarketSettingsResponse


ROLE_MARKET_SETTINGS_FILE = "market-settings.json"
DEFAULT_ROLE_MARKET_SOURCE = "https://likemirage.github.io/Tiance-roles"


class RoleMarketSettingsRepository(
    OnlineMarketSettingsRepository[RoleMarketSettingsResponse]
):
    def __init__(self, settings_path: Path) -> None:
        super().__init__(
            settings_path,
            settings_model=RoleMarketSettingsResponse,
            default_source=DEFAULT_ROLE_MARKET_SOURCE,
        )


@lru_cache
def get_role_market_settings_repository() -> RoleMarketSettingsRepository:
    return RoleMarketSettingsRepository(
        get_settings().roles_data_path / ROLE_MARKET_SETTINGS_FILE
    )
