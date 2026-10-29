from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
import sqlite3
from threading import Barrier

import pytest

from app.domain.usage_statistics import StatisticsMonth
from app.repositories.llm.usage_repository import LlmUsageRepository
from app.repositories.llm.usage_sqlite_store import UsageSqliteStore
from tests.test_usage_batch_overview import _record


def assert_consistent(store):
    with store.transaction() as db:
        store._verify_totals(db)


def test_request_identity_replaces_counts_but_preserves_first_ownership_and_time(tmp_path):
    store = UsageSqliteStore(tmp_path)
    first = _record(request_id='request-1')
    store.append_upsert(first)
    store.append_upsert(replace(
        first, usage_id='replacement', project_id='elsewhere', session_id='elsewhere',
        message_id='elsewhere', created_at='2027-01-01T00:00:00+00:00',
        total_tokens=700, cost_amount=2, is_estimated=True,
    ))
    saved, = store.iter_records()
    assert saved == replace(first, total_tokens=700, cost_amount=2, is_estimated=True)
    # Two requests in one tool loop share an assistant message but remain distinct.
    store.append_upsert(replace(first, usage_id='second', request_id='request-2'))
    assert len(tuple(store.iter_records())) == 2
    assert_consistent(store)


def test_fallback_identity_and_unidentified_records(tmp_path):
    store = UsageSqliteStore(tmp_path)
    store.append_upsert(_record())
    store.append_upsert(_record(usage_id='updated', total_tokens=200))
    store.append_upsert(_record(usage_id='anonymous-1', message_id=None))
    store.append_upsert(_record(usage_id='anonymous-2', message_id=None))
    assert [row.total_tokens for row in store.iter_records()] == [200, 15, 15]
    assert_consistent(store)


def test_correction_moves_model_feature_currency_and_refreshes_latest_order(tmp_path):
    repository = LlmUsageRepository(tmp_path)
    store = repository._store
    for i, date in enumerate(('01', '03', '02')):
        store.append_upsert(_record(usage_id=f'u{i}', message_id=f'm{i}',
            model_id='other' if i == 2 else 'model', created_at=f'2026-10-{date}T00:00:00+00:00'))
    assert repository.get_model_summaries()[0].model_id == 'model'
    store.append_upsert(_record(usage_id='ignored', message_id='m1', provider_id='new-provider',
        model_id='moved', usage_feature_key='memory_compression', cost_currency='CNY',
        cost_amount=3, is_estimated=True))
    summaries = repository.get_model_summaries(provider_id='provider')
    assert [row.model_id for row in summaries] == ['other', 'model']
    assert all(row.record_count == 1 for row in summaries)
    total = repository.get_session_summary(project_id='p1', session_id='shared').total
    assert (total.record_count, total.estimated_record_count, total.total_tokens) == (3, 1, 45)
    assert total.cost_currency is None and total.cost_amount is None
    assert_consistent(store)


def test_replay_without_identity_can_replace_time_in_same_group(tmp_path):
    store = UsageSqliteStore(tmp_path)
    store.append_upsert(_record(message_id=None, created_at='2026-10-25T00:00:00+00:00'))
    store.append_upsert(_record(usage_id='u2', message_id=None))
    store.append_upsert(_record(message_id=None, created_at='2026-10-01T00:00:00+00:00'))
    assert store.model_totals()[0]['latest_created_at'] == '2026-10-21T00:00:00+00:00'
    assert_consistent(store)


def test_detail_and_total_write_failure_is_atomic(tmp_path, monkeypatch):
    store = UsageSqliteStore(tmp_path)
    store.append_upsert(_record())
    original_adjust = UsageSqliteStore._adjust
    def fail(db, record, ordinal, sign):
        original_adjust(db, record, ordinal, sign)
        if sign > 0:
            raise RuntimeError('crash after changing totals')
    with monkeypatch.context() as patch:
        patch.setattr(UsageSqliteStore, '_adjust', staticmethod(fail))
        with pytest.raises(RuntimeError):
            store.append_upsert(_record(total_tokens=999, model_id='changed'))
    assert tuple(store.iter_records()) == (_record(),)
    assert_consistent(store)


@pytest.mark.parametrize('attempt', range(8))
def test_concurrent_first_open_and_writes_are_deduplicated_without_lost_totals(tmp_path, attempt):
    barrier = Barrier(6)
    def write(index):
        store = UsageSqliteStore(tmp_path)
        barrier.wait(timeout=10)
        for sequence in range(10):
            store.append_upsert(_record(usage_id=f'{index}-{sequence}', message_id=f'{index}-{sequence}'))
        store.append_upsert(_record(usage_id=f'redundant-{index}', request_id='same-request'))
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(write, range(6)))
    store = UsageSqliteStore(tmp_path)
    assert len(tuple(store.iter_records())) == 61
    assert store.model_totals()[0]['total_tokens'] == 61 * 15
    assert_consistent(store)


def test_initialization_checks_schema_in_one_transaction(tmp_path, monkeypatch):
    store = UsageSqliteStore(tmp_path)
    original_connect = store._connect
    observations = []

    @contextmanager
    def traced_connection():
        with original_connect() as db:
            def trace(statement):
                if statement == 'PRAGMA user_version' or statement.startswith('SELECT 1 FROM sqlite_master'):
                    observations.append((statement, db.in_transaction))
            db.set_trace_callback(trace)
            yield db

    monkeypatch.setattr(store, '_connect', traced_connection)
    store.ensure_ready()
    assert len(observations) == 2
    assert all(in_transaction for _, in_transaction in observations)
    with original_connect() as db:
        assert db.execute('PRAGMA auto_vacuum').fetchone()[0] == 2
        assert db.execute('PRAGMA journal_mode').fetchone()[0] == 'wal'


def test_failed_initial_creation_leaves_no_partial_schema_and_can_retry(tmp_path, monkeypatch):
    store = UsageSqliteStore(tmp_path)
    create = store._create_schema
    def fail(db):
        create(db)
        raise RuntimeError('initialization interrupted')
    with monkeypatch.context() as patch:
        patch.setattr(store, '_create_schema', fail)
        with pytest.raises(RuntimeError, match='initialization interrupted'):
            store.ensure_ready()
    with store._connect() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 0
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE type='table'").fetchone()
    store.ensure_ready()
    assert tuple(store.iter_records()) == ()


def test_cumulative_queries_never_read_detail_table_and_daily_query_uses_time_index(tmp_path, monkeypatch):
    repository = LlmUsageRepository(tmp_path)
    store = repository._store
    store.append_upsert(_record())
    original_connect = store._connect
    @contextmanager
    def guarded_connection():
        with original_connect() as db:
            def authorize(action, table, column, database, trigger):
                if action == sqlite3.SQLITE_READ and table == 'usage_records':
                    return sqlite3.SQLITE_DENY
                return sqlite3.SQLITE_OK
            db.set_authorizer(authorize)
            yield db
    with monkeypatch.context() as patch:
        patch.setattr(store, '_connect', guarded_connection)
        assert repository.get_model_summaries()[0].total_tokens == 15
        assert repository.get_model_summaries(provider_id='provider')[0].total_tokens == 15
        assert repository.get_session_summary(project_id='p1', session_id='shared').total.total_tokens == 15
        assert repository.get_projects_session_totals({'p1': ('shared',)})['p1']['shared'].total_tokens == 15
    with store.transaction() as db:
        plan = ' '.join(str(row[3]) for row in db.execute(
            'EXPLAIN QUERY PLAN SELECT SUM(total_tokens) FROM usage_records WHERE created_at_us>=? AND created_at_us<?', (0, 100)))
        assert 'SEARCH' in plan and 'COVERING INDEX usage_records_time' in plan
        plan = ' '.join(str(row[3]) for row in db.execute(
            "EXPLAIN QUERY PLAN SELECT * FROM usage_totals WHERE scope='session' AND scope_id=?", ('test',)))
        assert 'SEARCH' in plan and 'PRIMARY KEY' in plan


def test_explicit_delete_removes_details_and_totals_and_allows_space_reclamation(tmp_path):
    store = UsageSqliteStore(tmp_path)
    with store.transaction(write=True) as db:
        for i in range(1500):
            store._upsert(db, _record(usage_id=f'u{i}', message_id=f'm{i}', session_id=f's{i}'))
    before = store.database_path.stat().st_size
    store.append_delete_model(provider_id='provider', model_id='model')
    assert tuple(store.iter_records()) == () and store.model_totals() == ()
    store.maintain(full=True)
    assert store.database_path.stat().st_size < before
    store.append_upsert(_record())
    assert tuple(UsageSqliteStore(tmp_path).iter_records()) == (_record(),)
    assert_consistent(store)


def test_completed_migration_never_reads_or_replays_old_backup(tmp_path, monkeypatch):
    store = UsageSqliteStore(tmp_path)
    store.append_upsert(_record())
    (tmp_path / 'usage_records.jsonl').write_text('intentionally invalid backup', encoding='utf-8')
    assert len(tuple(UsageSqliteStore(tmp_path).iter_records())) == 1
    original_open = Path.open
    def guard(path, *args, **kwargs):
        if path.name == 'usage_records.jsonl':
            raise AssertionError('backup read after migration')
        return original_open(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', guard)
    assert UsageSqliteStore(tmp_path).model_totals()[0]['record_count'] == 1


def test_date_index_normalizes_offsets_and_correction_keeps_first_month(tmp_path):
    store = UsageSqliteStore(tmp_path)
    store.append_upsert(_record(created_at='2026-11-01T00:30:00+08:00'))
    store.append_upsert(_record(created_at='2026-12-01T00:00:00+08:00', total_tokens=100))
    october = store.monthly_statistics(StatisticsMonth.parse('2026-10', 'UTC'))
    november = store.monthly_statistics(StatisticsMonth.parse('2026-11', 'Asia/Shanghai'))
    assert october['daily'][-1] == november['daily'][0] == 100
    assert sum(october['daily']) == sum(november['daily']) == 100
    assert october['total'] == 100


def test_verification_rejects_wrong_currency_group_and_estimated_count(tmp_path):
    store = UsageSqliteStore(tmp_path)
    store.append_upsert(_record())
    for statement in (
        "UPDATE usage_totals SET estimated_record_count=100",
        "UPDATE usage_totals SET currency_key='wrong'",
        "UPDATE usage_totals SET cost_amount=999",
    ):
        with pytest.raises(RuntimeError, match='totals'):
            with store.transaction(write=True) as db:
                db.execute(statement)
                store._verify_totals(db)
    assert_consistent(store)


def test_rebuild_uses_preserved_costs_and_commits_atomically(tmp_path, monkeypatch):
    store = UsageSqliteStore(tmp_path)
    store.append_upsert(_record(cost_amount=123.4, is_estimated=True))
    before = tuple(dict(row) for row in store.model_totals())
    def fail(db):
        raise RuntimeError('interrupted rebuild')
    with monkeypatch.context() as patch:
        patch.setattr(store, '_verify_totals', fail)
        with pytest.raises(RuntimeError, match='interrupted'):
            store.rebuild_totals()
    assert tuple(dict(row) for row in store.model_totals()) == before
    with store.transaction(write=True) as db:
        db.execute('DELETE FROM usage_totals')
    store.rebuild_totals()
    assert tuple(dict(row) for row in store.model_totals()) == before
    assert tuple(store.iter_records()) == (_record(cost_amount=123.4, is_estimated=True),)
    assert_consistent(store)
