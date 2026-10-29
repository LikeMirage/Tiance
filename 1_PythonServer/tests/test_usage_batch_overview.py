from collections import Counter
from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.core.errors import NotFoundError
from app.domain.llm.usage import LlmUsageRecord
from app.domain.project import Project, ProjectCategory
from app.repositories.llm.usage_repository import LlmUsageRepository
from app.services.llm.usage.service import LlmUsageService
from app.services.project.project_category_overview import ProjectCategoryOverviewService
from tests.test_project_category_overview import _session


NOW = "2026-10-21T00:00:00+00:00"


def _record(project_id="p1", session_id="shared", **changes):
    record = LlmUsageRecord(
        usage_id="u1", project_id=project_id, session_id=session_id,
        message_id="m1", provider_id="provider", model_id="model",
        usage_feature_key="main_chat", prompt_tokens=10, completion_tokens=5,
        total_tokens=15, reasoning_tokens=3, prompt_cache_hit_tokens=7,
        prompt_cache_miss_tokens=3, cost_amount=0.2, cost_currency="USD",
        is_estimated=False, created_at=NOW,
    )
    return replace(record, **changes)


class _CountingStore:
    def __init__(self, store):
        self.store = store
        self.scans = 0
        self.visits = 0

    def session_totals(self, requests):
        result = self.store.session_totals(requests)
        if any(requests.values()):
            self.scans += 1
            self.visits += sum(len(rows) for sessions in result.values() for rows in sessions.values())
        return result

    def append(self, record):
        self.store.append_upsert(record)


def _repository(tmp_path, records):
    repository = LlmUsageRepository(tmp_path / "usage")
    with repository._store.transaction(write=True) as db:
        for index, record in enumerate(records):
            # These are separate requests, not repeated updates of the same ID.
            repository._store._upsert(db, replace(record, usage_id=f"u{index}", message_id=f"m{index}"))
    store = _CountingStore(repository._store)
    repository._store = store
    return repository, store


def test_batch_separates_projects_and_preserves_all_usage_fields(tmp_path):
    repository, store = _repository(tmp_path, [
        _record(), _record(is_estimated=True),
        _record("p2", total_tokens=99, cost_currency="CNY"),
        _record("p2", cost_currency="USD"),
        _record("unrequested"), _record("p1", "unrequested"),
        _record(None, None),
    ])
    totals = repository.get_projects_session_totals({
        "p1": ("shared", "empty"), "p2": ("shared",), "empty": (),
    })
    assert store.scans == 1
    assert store.visits == 3  # Only the requested currency/feature totals.
    assert totals["empty"] == {}
    assert "empty" not in totals["p1"]
    first = totals["p1"]["shared"]
    assert (first.prompt_tokens, first.completion_tokens, first.total_tokens) == (20, 10, 30)
    assert (first.reasoning_tokens, first.prompt_cache_hit_tokens, first.prompt_cache_miss_tokens) == (6, 14, 6)
    assert (first.cost_amount, first.cost_currency) == (0.4, "USD")
    assert (first.record_count, first.estimated_record_count) == (2, 1)
    second = totals["p2"]["shared"]
    assert second.total_tokens == 114
    assert second.cost_amount is None and second.cost_currency is None
    for project_id in ("p1", "p2"):
        assert totals[project_id]["shared"] == repository.get_session_summary(
            project_id=project_id, session_id="shared",
        ).total


@pytest.mark.parametrize("requests", [{}, {"empty": ()}])
def test_no_sessions_does_not_scan_usage(tmp_path, requests):
    repository, store = _repository(tmp_path, [_record()])
    assert repository.get_projects_session_totals(requests) == {key: {} for key in requests}
    assert store.scans == 0


def test_category_overview_reads_20_totals_for_50000_records_and_sees_new_usage(tmp_path):
    category = ProjectCategory("cat", "Category", False, 0, NOW, NOW)
    projects = tuple(Project(
        project_id=f"p{i}", name=f"Project {i}", root_path=str(tmp_path / str(i)),
        category_id="cat", is_default=False, sort_order=i, created_at=NOW, updated_at=NOW,
    ) for i in range(20))
    project_map = {project.project_id: project for project in projects}
    project_service = SimpleNamespace(
        list_project_categories=lambda: (category,), list_projects=lambda: projects,
        get_project=project_map.get,
    )
    calls = Counter()

    def session_data(project_id):
        calls[project_id] += 1
        return (_session("shared", 1, "Chat", 1, NOW),), (), "shared", {}

    repository, store = _repository(tmp_path, [
        _record(f"p{i % 20}", usage_id=f"u{i}") for i in range(50_000)
    ])
    usage_service = LlmUsageService(repository, project_service, None, None)
    overview_service = ProjectCategoryOverviewService(
        project_service, SimpleNamespace(get_overview_data=session_data), usage_service,
    )
    overview = overview_service.get_category_overview("cat")
    assert (store.scans, store.visits) == (1, 20)
    assert calls == Counter({project.project_id: 1 for project in projects})
    assert overview.project_count == 20 and overview.session_count == 20
    assert all(item.usage.total_tokens == 37_500 for item in overview.projects)

    store.append(_record("p0", usage_id="new", message_id="new-message"))
    refreshed = overview_service.get_category_overview("cat")
    assert store.scans == 2
    assert refreshed.projects[0].usage.total_tokens == 37_515
    assert refreshed.projects[1].usage.total_tokens == 37_500
    assert overview_service.get_project_overview("p0") == refreshed.projects[0]


def test_batch_service_rejects_unknown_project_before_scanning(tmp_path):
    repository, store = _repository(tmp_path, [_record()])
    service = LlmUsageService(
        repository, SimpleNamespace(get_project=lambda _: None), None, None,
    )
    with pytest.raises(NotFoundError):
        service.get_projects_session_totals({"missing": ("shared",)})
    assert store.scans == 0
