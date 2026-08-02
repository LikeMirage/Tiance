from json import loads

from app.infra.database import ensure_database_schema
from app.repositories.project import ProjectRepository
from app.services.desktop_window_preferences import (
    DEFAULT_WINDOW_HEIGHT,
    DEFAULT_WINDOW_MAXIMIZED,
    DEFAULT_WINDOW_WIDTH,
    DESKTOP_WINDOW_SIZE_PREFERENCES_KEY,
    MAX_WINDOW_HEIGHT,
    MAX_WINDOW_WIDTH,
    MIN_WINDOW_HEIGHT,
    MIN_WINDOW_WIDTH,
    DesktopWindowPreferencesService,
)


def test_desktop_window_size_preferences_are_default_by_default(tmp_path):
    service, _repository = _create_service(tmp_path)

    preferences = service.get_size_preferences()

    assert preferences.width == DEFAULT_WINDOW_WIDTH
    assert preferences.height == DEFAULT_WINDOW_HEIGHT
    assert preferences.maximized is DEFAULT_WINDOW_MAXIMIZED


def test_desktop_window_size_preferences_persist_size_and_maximized(tmp_path):
    service, repository = _create_service(tmp_path)

    saved = service.save_size_preferences(width=1500, height=920, maximized=True)
    loaded = service.get_size_preferences()

    assert saved == loaded
    assert loaded.width == 1500
    assert loaded.height == 920
    assert loaded.maximized is True

    raw = repository.get_metadata_value(DESKTOP_WINDOW_SIZE_PREFERENCES_KEY)
    assert raw is not None
    payload = loads(raw)
    assert payload == {
        "version": 1,
        "width": 1500,
        "height": 920,
        "maximized": True,
    }


def test_desktop_window_size_preferences_clamp_invalid_size(tmp_path):
    service, _repository = _create_service(tmp_path)

    too_small = service.save_size_preferences(width=1, height=1, maximized=False)
    too_large = service.save_size_preferences(width=99999, height=99999, maximized=True)

    assert too_small.width == MIN_WINDOW_WIDTH
    assert too_small.height == MIN_WINDOW_HEIGHT
    assert too_large.width == MAX_WINDOW_WIDTH
    assert too_large.height == MAX_WINDOW_HEIGHT
    assert too_large.maximized is True


def _create_service(tmp_path):
    database_path = tmp_path / "tiance.db"
    ensure_database_schema(database_path)
    repository = ProjectRepository(database_path)
    return DesktopWindowPreferencesService(repository), repository
