from __future__ import annotations

import json

import pytest

from app.core.errors import BadRequestError
from app.repositories.announcement_cache_repository import AnnouncementCacheRepository
from app.repositories.announcement_state_repository import AnnouncementStateRepository
from app.services.application.announcements import (
    _validate_asset_path,
    _validate_root_index,
    _validate_year_index,
)


def _announcement(sequence: int) -> dict[str, object]:
    announcement_id = f"2026-08-23-{sequence}"
    return {
        "id": announcement_id,
        "revision": 1,
        "title": f"公告 {sequence}",
        "summary": "摘要",
        "publishedAt": f"2026-08-23T{sequence % 24:02d}:00:00+08:00",
        "importance": "normal",
        "status": "published",
        "contentPath": f"announcements/2026/08-23-{sequence}/r1/content.md",
    }


def test_year_index_preserves_every_announcement_without_recent_item_limit() -> None:
    payload = {
        "schemaVersion": 1,
        "year": 2026,
        "updatedAt": "2026-08-23T23:00:00+08:00",
        "announcements": [_announcement(sequence) for sequence in range(1, 151)],
    }

    validated = _validate_year_index(2026, payload)

    assert len(validated.announcements) == 150
    assert {item.id for item in validated.announcements} == {
        f"2026-08-23-{sequence}" for sequence in range(1, 151)
    }


def test_root_index_requires_exact_annual_index_contract() -> None:
    payload = {
        "schemaVersion": 1,
        "updatedAt": "2026-08-23T23:00:00+08:00",
        "latestAnnouncementId": "2026-08-23-2",
        "latestAnnouncementYear": 2026,
        "years": [{"year": 2026, "indexPath": "other/2026.json"}],
    }

    with pytest.raises(BadRequestError):
        _validate_root_index("https://example.invalid", payload)


def test_read_state_is_independent_from_reconstructible_cache(tmp_path) -> None:
    state = AnnouncementStateRepository(tmp_path / "announcements" / "read-state.json")
    cache = AnnouncementCacheRepository(tmp_path / "cache" / "announcements")
    read_at = state.mark_read("2026-08-23-1", 2)
    cache.save_bytes("https://example.invalid", "announcements/2026/08-23-1/r2/content.md", b"x")
    cache.path_for(
        "https://example.invalid",
        "announcements/2026/08-23-1/r2/content.md",
    ).unlink()

    saved = state.get_state()

    assert saved["readAnnouncements"] == {
        "2026-08-23-1": {"revision": 2, "readAt": read_at}
    }


def test_invalid_read_state_fails_instead_of_resetting_all_reads(tmp_path) -> None:
    state_path = tmp_path / "read-state.json"
    state_path.write_text(json.dumps({"schemaVersion": 1, "readAnnouncements": []}))

    with pytest.raises(BadRequestError):
        AnnouncementStateRepository(state_path).get_state()


@pytest.mark.parametrize(
    "path",
    ["https://example.com/image.png", "../assets/image.png", "file:///x.png", "image.png"],
)
def test_announcement_asset_path_rejects_external_or_escaping_paths(path: str) -> None:
    with pytest.raises(BadRequestError):
        _validate_asset_path(path)
