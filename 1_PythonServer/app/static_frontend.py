import logging

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import Settings

logger = logging.getLogger(__name__)


class FrontendStaticFiles(StaticFiles):
    def file_response(self, full_path, stat_result, scope, status_code=200):
        response = super().file_response(full_path, stat_result, scope, status_code=status_code)
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response


def mount_frontend_dist(application: FastAPI, settings: Settings) -> None:
    dist_path = settings.frontend_dist_path
    index_file = dist_path / "index.html"
    if not dist_path.is_dir() or not index_file.is_file():
        logger.info("Frontend dist not mounted because index.html is missing: %s", dist_path)
        return

    @application.get("/app", include_in_schema=False)
    async def frontend_app_redirect():
        return RedirectResponse(url="/app/")

    application.mount(
        "/app",
        FrontendStaticFiles(directory=str(dist_path), html=True),
        name="frontend",
    )
    logger.info("Frontend dist mounted at /app from %s", dist_path)
