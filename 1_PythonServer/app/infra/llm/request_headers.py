from __future__ import annotations

from collections.abc import Mapping

from app.core.config import get_settings
from app.core.errors import AppError
from app.domain.llm.provider_catalog import ProviderCatalogEntry
from app.repositories.llm.provider_adaptation_rules_repository import (
    get_provider_adaptation_rules_repository,
)


def resolve_request_headers(
    provider_template: ProviderCatalogEntry,
    *,
    model_id: str | None = None,
    session_id: str,
) -> dict[str, str]:
    """Resolve data-only header declarations once per logical operation."""
    rules = get_provider_adaptation_rules_repository().resolve(
        provider_id=provider_template.provider_id,
        model_id=model_id,
        expected_profile_id=provider_template.profile_id,
    )
    if rules is None or not rules.request.headers:
        return {}
    result: dict[str, str] = {}
    for header in rules.request.headers:
        if header.source == "session_id":
            value = session_id
        elif header.source == "client_user_agent":
            value = f"Tiance/{get_settings().app_version}"
        else:
            value = header.value
        if (
            not isinstance(value, str)
            or not value.strip()
            or any(not 32 <= ord(char) <= 126 for char in value)
        ):
            raise AppError(
                f"Request header '{header.name}' has no valid value for source '{header.source}'.",
                code="provider_request_header_value_invalid",
            )
        result[header.name] = value
    return result


def merge_request_headers(
    headers: Mapping[str, str],
    declared_headers: Mapping[str, str],
) -> dict[str, str]:
    """HTTP header names are case insensitive; never send duplicate spellings."""
    overridden = {name.lower() for name in declared_headers}
    return {
        **{name: value for name, value in headers.items() if name.lower() not in overridden},
        **declared_headers,
    }
