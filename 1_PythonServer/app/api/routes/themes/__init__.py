from fastapi import APIRouter, HTTPException, WebSocket, status
from contextlib import aclosing
import json

from fastapi.responses import FileResponse, StreamingResponse
from app.api.event_socket import serve_event_socket

from app.schemas.themes import (
    ThemeDefinition,
    ThemeListResponse,
    ThemeMarketConnectRequest,
    ThemeMarketIndexResponse,
    ThemeMarketInstallRequest,
    ThemeMarketInstallResponse,
    ThemeMarketSettingsResponse,
    ThemeMarketSettingsUpdateRequest,
    ThemeSelectionUpdateRequest,
)
from app.services.application.theme_market import get_theme_market_application_service
from app.services.themes.theme_workspace_watcher import get_theme_workspace_event_broker
from app.services.themes import (
    ThemeAssetNotFoundError,
    ThemeCatalogError,
    ThemeNotFoundError,
    ThemeSaveRejectedError,
    get_active_theme,
    get_active_theme_id,
    get_theme_asset_path,
    get_theme,
    list_themes as list_available_themes,
    save_theme,
    set_active_theme,
)

router = APIRouter(prefix="/themes", tags=["themes"])


@router.get("/market/settings", response_model=ThemeMarketSettingsResponse)
def read_theme_market_settings() -> ThemeMarketSettingsResponse:
    return get_theme_market_application_service().get_settings()


@router.put("/market/settings", response_model=ThemeMarketSettingsResponse)
def update_theme_market_settings(
    payload: ThemeMarketSettingsUpdateRequest,
) -> ThemeMarketSettingsResponse:
    return get_theme_market_application_service().save_filters(payload.filters)


@router.get("/market/index", response_model=ThemeMarketIndexResponse)
async def read_theme_market_index() -> ThemeMarketIndexResponse:
    return await get_theme_market_application_service().get_index()


@router.post("/market/connect", response_model=ThemeMarketIndexResponse)
async def connect_theme_market(
    payload: ThemeMarketConnectRequest,
) -> ThemeMarketIndexResponse:
    return await get_theme_market_application_service().connect(payload.source)


@router.get("/market/previews/{theme_id}", response_class=FileResponse)
async def read_theme_market_preview(theme_id: str) -> FileResponse:
    path = await get_theme_market_application_service().get_preview_path(theme_id)
    return FileResponse(path)


@router.post(
    "/market/themes/{theme_id}/install",
    response_model=ThemeMarketInstallResponse,
    status_code=status.HTTP_201_CREATED,
)
async def install_theme_market_theme(
    theme_id: str,
    payload: ThemeMarketInstallRequest,
) -> ThemeMarketInstallResponse:
    return await get_theme_market_application_service().install_theme(
        theme_id=theme_id,
        category_id=payload.category_id,
        replace_existing=payload.replace_existing,
    )


@router.get("", response_model=ThemeListResponse)
def list_themes() -> ThemeListResponse:
    try:
        return ThemeListResponse(
            active_theme_id=get_active_theme_id(),
            themes=list_available_themes(),
        )
    except ThemeCatalogError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc


@router.get("/active", response_model=ThemeDefinition)
def read_active_theme() -> ThemeDefinition:
    try:
        return get_active_theme()
    except ThemeCatalogError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc


@router.put("/active", response_model=ThemeDefinition)
def update_active_theme(payload: ThemeSelectionUpdateRequest) -> ThemeDefinition:
    try:
        return set_active_theme(payload.theme_id)
    except ThemeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Theme not found") from exc
    except ThemeCatalogError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc


@router.get("/events", summary="Watch theme workspace changes")
async def watch_theme_events() -> StreamingResponse:
    async def event_generator():
        async with aclosing(_theme_workspace_events()) as events:
            async for payload in events:
                yield _sse_event(payload)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.websocket("/events")
async def watch_theme_events_socket(websocket: WebSocket) -> None:
    await serve_event_socket(websocket, _theme_workspace_events())


async def _theme_workspace_events():
    async with aclosing(get_theme_workspace_event_broker().subscribe()) as changes:
        yield {"kind": "ready"}
        async for paths in changes:
            yield {"kind": "changed", "paths": paths}


@router.get("/assets/{asset_path:path}", response_class=FileResponse)
def read_theme_asset(asset_path: str) -> FileResponse:
    try:
        return FileResponse(get_theme_asset_path(asset_path))
    except ThemeAssetNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Theme asset not found") from exc


@router.get("/{theme_id}", response_model=ThemeDefinition)
def read_theme(theme_id: str) -> ThemeDefinition:
    try:
        return get_theme(theme_id)
    except ThemeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Theme not found") from exc
    except ThemeCatalogError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc


@router.put("/{theme_id}", response_model=ThemeDefinition)
def update_theme(theme_id: str, payload: ThemeDefinition) -> ThemeDefinition:
    try:
        return save_theme(theme_id, payload)
    except ThemeSaveRejectedError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ThemeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Theme not found") from exc
    except ThemeCatalogError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc


def _sse_event(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
