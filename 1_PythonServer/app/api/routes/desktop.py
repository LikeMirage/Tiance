from fastapi import APIRouter, Response, status

from app.schemas.desktop_local_path import DesktopLocalPathRequest

from app.schemas.desktop_page_zoom import (
    DesktopPageZoomPreferencesResponse,
    DesktopPageZoomPreferencesSaveRequest,
)
from app.schemas.desktop_window import (
    DesktopWindowSizePreferencesResponse,
    DesktopWindowSizePreferencesSaveRequest,
)
from app.services.desktop_page_zoom_preferences import (
    get_desktop_page_zoom_preferences_service,
)
from app.services.desktop_window_preferences import get_desktop_window_preferences_service
from app.services.desktop_local_path import get_desktop_local_path_service

router = APIRouter(prefix="/desktop", tags=["desktop"])


@router.get(
    "/window-size-preferences",
    response_model=DesktopWindowSizePreferencesResponse,
    summary="Get desktop window size preferences",
)
def get_desktop_window_size_preferences() -> DesktopWindowSizePreferencesResponse:
    service = get_desktop_window_preferences_service()
    return DesktopWindowSizePreferencesResponse.from_domain(service.get_size_preferences())


@router.put(
    "/window-size-preferences",
    response_model=DesktopWindowSizePreferencesResponse,
    summary="Save desktop window size preferences",
)
def save_desktop_window_size_preferences(
    payload: DesktopWindowSizePreferencesSaveRequest,
) -> DesktopWindowSizePreferencesResponse:
    service = get_desktop_window_preferences_service()
    return DesktopWindowSizePreferencesResponse.from_domain(
        service.save_size_preferences(
            width=payload.width,
            height=payload.height,
            maximized=payload.maximized,
        ),
    )


@router.get(
    "/page-zoom-preferences",
    response_model=DesktopPageZoomPreferencesResponse,
    summary="Get desktop page zoom preferences",
)
def get_desktop_page_zoom_preferences() -> DesktopPageZoomPreferencesResponse:
    service = get_desktop_page_zoom_preferences_service()
    return DesktopPageZoomPreferencesResponse.from_domain(service.get_preferences())


@router.put(
    "/page-zoom-preferences",
    response_model=DesktopPageZoomPreferencesResponse,
    summary="Save desktop page zoom preferences",
)
def save_desktop_page_zoom_preferences(
    payload: DesktopPageZoomPreferencesSaveRequest,
) -> DesktopPageZoomPreferencesResponse:
    service = get_desktop_page_zoom_preferences_service()
    return DesktopPageZoomPreferencesResponse.from_domain(
        service.save_preferences(zoom_factor=payload.zoom_factor),
    )


@router.post(
    "/local-path/reveal",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Reveal an explicit local path in the system file explorer",
)
def reveal_desktop_local_path(payload: DesktopLocalPathRequest) -> Response:
    get_desktop_local_path_service().reveal(payload.path)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/local-path/open-default",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Open an explicit local path with the system default application",
)
def open_desktop_local_path(payload: DesktopLocalPathRequest) -> Response:
    get_desktop_local_path_service().open_default(payload.path)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
