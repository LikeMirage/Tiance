import pytest

from app.core.shutdown_tasks import shutdown_tasks


@pytest.fixture
def fake_system_recycle(monkeypatch, tmp_path):
    """Keep unit tests out of the real Recycle Bin; move only this test's fixtures."""
    from pathlib import Path
    from uuid import uuid4
    from app.infra.projects import project_storage
    recycled = []
    def recycle(source):
        source = Path(source).resolve()
        assert source.is_relative_to(tmp_path.resolve()) and source != tmp_path.resolve()
        target = tmp_path / 'fake-system-recycle' / uuid4().hex
        assert target.resolve().is_relative_to(tmp_path.resolve())
        target.parent.mkdir(exist_ok=True)
        source.rename(target)
        recycled.append((source, target))
    monkeypatch.setattr(project_storage, 'recycle_path', recycle)
    return recycled


@pytest.fixture(autouse=True)
def accepting_application_lifecycle():
    """Each test starts a new application lifecycle, including service-only tests."""
    shutdown_tasks.resume()
    try:
        yield
    finally:
        shutdown_tasks.resume()
