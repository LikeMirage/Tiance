import json
import sqlite3
from dataclasses import asdict, replace

import pytest

from app.domain.llm.chat import ChatUsage
from app.infra.database import ensure_database_schema, run_database_migrations
from app.infra.database.schema import MIGRATIONS
from app.repositories.llm.usage_repository import LlmUsageRepository
from app.repositories.llm.usage_sqlite_store import UsageSqliteStore
from app.services.application.usage_file_migration import ensure_usage_sqlite_storage
from tests.test_usage_batch_overview import _record


def test_legacy_global_database_is_imported_before_tables_are_removed(tmp_path):
    database_path = tmp_path / "tiance.db"
    usage_path = tmp_path / "usage"
    run_database_migrations(
        database_path,
        tuple(migration for migration in MIGRATIONS if migration.version <= 45),
    )
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO llm_usage_records (
                usage_id, project_id, session_id, message_id,
                provider_id, model_id, usage_feature_key,
                prompt_tokens, completion_tokens, total_tokens, reasoning_tokens,
                prompt_cache_hit_tokens, prompt_cache_miss_tokens,
                cost_amount, cost_currency, is_estimated, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "usage_legacy",
                "project-1",
                "session-1",
                "message-1",
                "deepseek",
                "deepseek-v4",
                "main_chat",
                12,
                3,
                15,
                2,
                5,
                7,
                0.25,
                "CNY",
                0,
                "2026-08-01T00:00:00+00:00",
            ),
        )

    ensure_usage_sqlite_storage(database_path, usage_path)
    original_content = tuple(UsageSqliteStore(usage_path).iter_records())
    ensure_usage_sqlite_storage(database_path, usage_path)
    assert tuple(UsageSqliteStore(usage_path).iter_records()) == original_content

    ensure_database_schema(database_path)

    with sqlite3.connect(database_path) as connection:
        table_names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    assert "llm_usage_records" not in table_names
    assert "llm_conversation_session_index" not in table_names

    summary = LlmUsageRepository(usage_path).get_session_summary(
        project_id="project-1",
        session_id="session-1",
    )
    assert summary.total.record_count == 1
    assert summary.total.total_tokens == 15
    assert summary.total.prompt_cache_hit_tokens == 5
    assert summary.total.cost_amount == 0.25


def write_legacy(path, events=None):
    path.mkdir(parents=True, exist_ok=True)
    ledger = path / 'usage_records.jsonl'
    if events is None:
        events = [{'version': 1, 'operation': 'upsert', 'record': asdict(_record())}]
    ledger.write_text(''.join(json.dumps(event) + '\n' for event in events), encoding='utf-8')
    return ledger


def add_usage(repository, message_id='new'):
    return repository.record_usage(project_id='p1', session_id='shared', message_id=message_id,
                                   provider_id='provider', model_id='model', usage=ChatUsage(total_tokens=12))


def test_replay_updates_preserve_first_location_date_and_cost_then_delete(tmp_path):
    first = _record(cost_amount=0.1, request_id='same')
    update = replace(first, usage_id='later', project_id='other', session_id='other',
                     created_at='2027-01-01T00:00:00+00:00', total_tokens=99, cost_amount=0.8,
                     cost_currency='CNY', is_estimated=True)
    events = [{'version': 1, 'operation': 'upsert', 'record': asdict(r)} for r in (first, update)]
    ledger = write_legacy(tmp_path, events)
    original = ledger.read_bytes()
    repo = LlmUsageRepository(tmp_path)
    summary = repo.get_session_summary(project_id='p1', session_id='shared').total
    assert (summary.record_count, summary.total_tokens, summary.cost_amount, summary.cost_currency, summary.estimated_record_count) == (1, 99, 0.8, 'CNY', 1)
    saved, = repo._store.iter_records()
    assert saved.usage_id == first.usage_id and saved.created_at == first.created_at
    repo.delete_model_usage(provider_id='provider', model_id='model')
    assert not tuple(UsageSqliteStore(tmp_path).iter_records())
    assert ledger.read_bytes() == original
    # Reinitialization never resurrects deleted usage from the retained backup.
    ensure_usage_sqlite_storage(tmp_path / 'unused.db', tmp_path)
    assert not tuple(UsageSqliteStore(tmp_path).iter_records())


def test_delete_event_applies_in_order_and_later_requests_survive(tmp_path):
    early, late = _record(request_id='same'), _record(usage_id='late', request_id='same', total_tokens=71)
    write_legacy(tmp_path, [
        {'version': 1, 'operation': 'upsert', 'record': asdict(early)},
        {'version': 1, 'operation': 'delete_model', 'provider_id': early.provider_id, 'model_id': early.model_id},
        {'version': 1, 'operation': 'upsert', 'record': asdict(late)},
    ])
    assert tuple(UsageSqliteStore(tmp_path).iter_records()) == (late,)


@pytest.mark.parametrize('tail', [b'{"version":1,"record":', b'{"text":"\xe4\xb8', b'\x00\x00'])
def test_torn_tail_is_backed_up_and_original_is_not_modified(tmp_path, tail):
    ledger = write_legacy(tmp_path)
    original = ledger.read_bytes() + tail
    ledger.write_bytes(original)
    ensure_usage_sqlite_storage(tmp_path / 'unused.db', tmp_path)
    assert ledger.read_bytes() == original
    backups = list(tmp_path.glob('*.corrupt-tail'))
    assert len(backups) == 1 and backups[0].read_bytes() == tail
    add_usage(LlmUsageRepository(tmp_path))
    assert len(tuple(UsageSqliteStore(tmp_path).iter_records())) == 2
    ensure_usage_sqlite_storage(tmp_path / 'unused.db', tmp_path)
    assert len(tuple(UsageSqliteStore(tmp_path).iter_records())) == 2
    assert ledger.read_bytes() == original


def test_complete_event_without_newline_is_preserved(tmp_path):
    ledger = write_legacy(tmp_path)
    original = ledger.read_bytes().rstrip(b'\r\n')
    ledger.write_bytes(original)
    add_usage(LlmUsageRepository(tmp_path))
    assert len(tuple(UsageSqliteStore(tmp_path).iter_records())) == 2
    assert ledger.read_bytes() == original
    assert not list(tmp_path.glob('*.corrupt-tail'))


@pytest.mark.parametrize('suffix', [b'\n', b'\n{"version":1}\n'])
def test_complete_corrupt_line_is_not_silently_discarded(tmp_path, suffix):
    ledger = write_legacy(tmp_path)
    original = ledger.read_bytes() + b'{"partial":' + suffix
    ledger.write_bytes(original)
    with pytest.raises(ValueError, match='line 2'):
        UsageSqliteStore(tmp_path).ensure_ready()
    assert ledger.read_bytes() == original
    assert not list(tmp_path.glob('*.corrupt-tail'))


@pytest.mark.parametrize('tail', [b'{"version":2}', b'{"version":1,"operation":"unknown"}', b'{"version":1,"operation":"upsert","record":{}}'])
def test_semantically_invalid_tail_fails_migration(tmp_path, tail):
    ledger = tmp_path / 'usage_records.jsonl'
    ledger.write_bytes(tail)
    with pytest.raises(ValueError):
        UsageSqliteStore(tmp_path).ensure_ready()
    assert ledger.read_bytes() == tail
    assert not list(tmp_path.glob('*.corrupt-tail'))


def test_failed_tail_backup_does_not_commit_or_modify_source(tmp_path, monkeypatch):
    from pathlib import Path
    ledger = write_legacy(tmp_path)
    original = ledger.read_bytes() + b'{"partial":'
    ledger.write_bytes(original)
    real_open = Path.open
    def failing_backup(path, *args, **kwargs):
        if path.name.endswith('.corrupt-tail'):
            raise OSError('backup disk full')
        return real_open(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', failing_backup)
    with pytest.raises(OSError, match='backup disk full'):
        UsageSqliteStore(tmp_path).ensure_ready()
    assert ledger.read_bytes() == original
    monkeypatch.undo()
    assert len(tuple(UsageSqliteStore(tmp_path).iter_records())) == 1


def test_single_partial_first_record_can_migrate_and_append(tmp_path):
    ledger = tmp_path / 'usage_records.jsonl'
    ledger.write_bytes(b'{"version":')
    ensure_usage_sqlite_storage(tmp_path / 'unused.db', tmp_path)
    add_usage(LlmUsageRepository(tmp_path))
    assert len(tuple(UsageSqliteStore(tmp_path).iter_records())) == 1
    assert ledger.read_bytes() == b'{"version":'


def test_interrupted_migration_rolls_back_and_retries_once(tmp_path, monkeypatch):
    ledger = write_legacy(tmp_path)
    original = ledger.read_bytes()
    verify = UsageSqliteStore._verify_totals
    def interrupt(db):
        raise RuntimeError('injected crash before migration commit')
    monkeypatch.setattr(UsageSqliteStore, '_verify_totals', staticmethod(interrupt))
    with pytest.raises(RuntimeError, match='injected crash'):
        UsageSqliteStore(tmp_path).ensure_ready()
    monkeypatch.setattr(UsageSqliteStore, '_verify_totals', staticmethod(verify))
    assert len(tuple(UsageSqliteStore(tmp_path).iter_records())) == 1
    assert len(tuple(UsageSqliteStore(tmp_path).iter_records())) == 1
    assert ledger.read_bytes() == original


def test_legacy_writer_change_during_import_rolls_back(tmp_path, monkeypatch):
    ledger = write_legacy(tmp_path)
    upsert = UsageSqliteStore._upsert
    def modify_source(cls, db, record):
        upsert(db, record)
        with ledger.open('ab') as out:
            out.write(b'\n')
    with monkeypatch.context() as patch:
        patch.setattr(UsageSqliteStore, '_upsert', classmethod(modify_source))
        with pytest.raises(RuntimeError, match='changed during migration'):
            UsageSqliteStore(tmp_path).ensure_ready()
    assert len(tuple(UsageSqliteStore(tmp_path).iter_records())) == 1
