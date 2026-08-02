from fastapi import APIRouter, HTTPException, Query, status

from app.schemas.locales import (
    LocaleDefinitionResponse,
    LocaleListResponse,
    LocaleSettingsResponse,
    LocaleSettingsUpdateRequest,
    LocaleSummaryResponse,
)
from app.services.locales import (
    LocaleCatalogError,
    get_active_locale,
    get_locale_settings,
    list_locales as list_available_locales,
    update_locale_settings,
)

router = APIRouter(prefix="/locales", tags=["locales"])


@router.get("/settings", response_model=LocaleSettingsResponse)
def read_locale_settings() -> LocaleSettingsResponse:
    try:
        return LocaleSettingsResponse.model_validate(get_locale_settings())
    except LocaleCatalogError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc


@router.put("/settings", response_model=LocaleSettingsResponse)
def save_locale_settings(payload: LocaleSettingsUpdateRequest) -> LocaleSettingsResponse:
    try:
        settings = update_locale_settings(payload.mode, payload.active_locale)
        return LocaleSettingsResponse.model_validate(settings)
    except LocaleCatalogError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get("", response_model=LocaleListResponse)
def list_locales(
    preferred_locale: str | None = Query(default=None, alias="preferredLocale"),
) -> LocaleListResponse:
    try:
        active_locale, locales = list_available_locales(preferred_locale)
        return LocaleListResponse(
            activeLocale=active_locale,
            locales=[LocaleSummaryResponse.model_validate(locale) for locale in locales],
        )
    except LocaleCatalogError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc


@router.get("/active", response_model=LocaleDefinitionResponse)
def read_active_locale(
    preferred_locale: str | None = Query(default=None, alias="preferredLocale"),
) -> LocaleDefinitionResponse:
    try:
        return LocaleDefinitionResponse.model_validate(get_active_locale(preferred_locale))
    except LocaleCatalogError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc
