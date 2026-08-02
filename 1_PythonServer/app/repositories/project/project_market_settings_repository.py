from functools import lru_cache
from pathlib import Path

from app.core.config import get_settings
from app.repositories.online_market_settings_repository import OnlineMarketSettingsRepository
from app.schemas.project.project_market import ProjectMarketSettingsResponse


PROJECT_MARKET_SETTINGS_FILE = "market-settings.json"
DEFAULT_PROJECT_MARKET_SOURCE = "https://likemirage.github.io/Tiance-projects"
DEFAULT_KNOWLEDGE_MARKET_SOURCE = "https://likemirage.github.io/Tiance-knowledge"
DEFAULT_EXPERIENCE_MARKET_SOURCE = "https://likemirage.github.io/Tiance-experience"


class ProjectMarketSettingsRepository(
    OnlineMarketSettingsRepository[ProjectMarketSettingsResponse]
):
    def __init__(
        self,
        settings_path: Path,
        *,
        default_source: str = DEFAULT_PROJECT_MARKET_SOURCE,
    ) -> None:
        super().__init__(
            settings_path,
            settings_model=ProjectMarketSettingsResponse,
            default_source=default_source,
        )


@lru_cache
def get_project_market_settings_repository() -> ProjectMarketSettingsRepository:
    return ProjectMarketSettingsRepository(
        get_settings().projects_data_path / PROJECT_MARKET_SETTINGS_FILE
    )


@lru_cache
def get_knowledge_market_settings_repository() -> ProjectMarketSettingsRepository:
    return ProjectMarketSettingsRepository(
        get_settings().knowledge_data_path / PROJECT_MARKET_SETTINGS_FILE,
        default_source=DEFAULT_KNOWLEDGE_MARKET_SOURCE,
    )


@lru_cache
def get_experience_market_settings_repository() -> ProjectMarketSettingsRepository:
    return ProjectMarketSettingsRepository(
        get_settings().experience_data_path / PROJECT_MARKET_SETTINGS_FILE,
        default_source=DEFAULT_EXPERIENCE_MARKET_SOURCE,
    )
