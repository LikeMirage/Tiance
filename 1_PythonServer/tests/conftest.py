import pytest

from app.core.shutdown_tasks import shutdown_tasks


@pytest.fixture(autouse=True)
def accepting_application_lifecycle():
    """Each test starts a new application lifecycle, including service-only tests."""
    shutdown_tasks.resume()
    try:
        yield
    finally:
        shutdown_tasks.resume()
