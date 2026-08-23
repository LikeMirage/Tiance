from functools import lru_cache
import json
from pathlib import Path
from uuid import uuid4

from app.core.config import get_settings
from app.core.atomic_replace import atomic_replace_path
from app.repositories.online_market_settings_repository import OnlineMarketSettingsRepository
from app.schemas.llm.provider_market import ProviderMarketSettingsResponse


PROVIDER_MARKET_SETTINGS_FILE = "market-settings.json"
DEFAULT_PROVIDER_MARKET_SOURCE = "https://likemirage.github.io/Tiance-providers"


class ProviderMarketSettingsRepository(
    OnlineMarketSettingsRepository[ProviderMarketSettingsResponse]
):
    def __init__(self, settings_path: Path) -> None:
        _remove_obsolete_conflict_filter(settings_path)
        super().__init__(
            settings_path,
            settings_model=ProviderMarketSettingsResponse,
            default_source=DEFAULT_PROVIDER_MARKET_SOURCE,
        )


def _remove_obsolete_conflict_filter(settings_path: Path) -> None:
    """Keep the user's source and other filters when removing the old conflict state."""
    try:
        payload = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    filters = payload.get("filters") if isinstance(payload, dict) else None
    statuses = filters.get("statuses") if isinstance(filters, dict) else None
    if not isinstance(statuses, list) or "local-conflict" not in statuses:
        return
    filters["statuses"] = [status for status in statuses if status != "local-conflict"]
    temporary = settings_path.with_name(f".{settings_path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        atomic_replace_path(temporary, settings_path)
    finally:
        temporary.unlink(missing_ok=True)


@lru_cache
def get_provider_market_settings_repository() -> ProviderMarketSettingsRepository:
    return ProviderMarketSettingsRepository(
        get_settings().providers_data_path / PROVIDER_MARKET_SETTINGS_FILE
    )
