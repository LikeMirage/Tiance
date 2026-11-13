"""Frozen v56 preference rows survive the grid-only upgrade and its retries."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
import json
import sqlite3

import pytest

from app.migrations import global_db
from app.migrations.runner import schema_transaction


def old_database(path, payload):
    with closing(sqlite3.connect(path)) as db:
        db.executescript("""
            CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL);
            INSERT INTO schema_migrations VALUES(56, 'mobile_menu_paths', '2026-11-11');
            CREATE TABLE app_metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL);
            INSERT INTO app_metadata VALUES('user.custom', 'keep', '2026-11-11');
        """)
        if payload is not None:
            db.execute("INSERT INTO app_metadata VALUES('workspace.layout_preferences', ?, '2026-11-11')", (payload,))
        db.commit()


def upgrade(path):
    with closing(sqlite3.connect(path, timeout=30)) as db, schema_transaction(db):
        global_db.ensure_version(db, 57)


def test_grid_upgrade_preserves_other_preferences_and_wal_backup(tmp_path):
    path = tmp_path / 'global.db'
    before = {'version': 6, 'project_overview_layout_modes': {'category': 'stack'},
              'sidebar_width': 291, 'maximized_project_id': 'project',
              'nested_selection': {'category': ['project', 'session']}}
    old_database(path, json.dumps(before))
    with closing(sqlite3.connect(path)) as writer:
        writer.execute('PRAGMA journal_mode=WAL')
        writer.execute("INSERT INTO app_metadata VALUES('wal', 'committed', '2026-11-11')")
        writer.commit()
        with ThreadPoolExecutor(max_workers=4) as executor:
            list(executor.map(lambda _: upgrade(path), range(8)))
    expected = {key: value for key, value in before.items() if key != 'project_overview_layout_modes'}
    expected['version'] = 7
    with closing(sqlite3.connect(path)) as db:
        value, date = db.execute("SELECT value,updated_at FROM app_metadata WHERE key='workspace.layout_preferences'").fetchone()
        assert json.loads(value) == expected
        assert date == '2026-11-11'
        assert db.execute("SELECT value FROM app_metadata WHERE key='user.custom'").fetchone()[0] == 'keep'
        assert db.execute('SELECT COUNT(*) FROM schema_migrations WHERE version=57').fetchone()[0] == 1
    backups = list(tmp_path.glob('*.bak'))
    assert len(backups) == 1
    with closing(sqlite3.connect(backups[0])) as db:
        assert db.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0] == 56
        assert json.loads(db.execute("SELECT value FROM app_metadata WHERE key='workspace.layout_preferences'").fetchone()[0]) == before
        assert db.execute("SELECT value FROM app_metadata WHERE key='wal'").fetchone()[0] == 'committed'


@pytest.mark.parametrize('payload', [None, '{broken', 'null', '[1,2]', '"keep"'])
def test_missing_or_malformed_preferences_are_not_destroyed(tmp_path, payload):
    path = tmp_path / 'global.db'
    old_database(path, payload)
    upgrade(path)
    with closing(sqlite3.connect(path)) as db:
        row = db.execute("SELECT value FROM app_metadata WHERE key='workspace.layout_preferences'").fetchone()
        assert row == (None if payload is None else (payload,))


def test_failure_rolls_back_preferences_and_version_then_can_retry(tmp_path, monkeypatch):
    path = tmp_path / 'global.db'
    payload = '{"version":6,"project_overview_layout_modes":{"a":"wide"},"keep":true}'
    old_database(path, payload)
    step = global_db.MIGRATIONS[-1]

    def fail_after_write(db):
        step.apply(db)
        raise RuntimeError('injected failure')

    with monkeypatch.context() as patch:
        patch.setattr(global_db, 'MIGRATIONS', (*global_db.MIGRATIONS[:-1], replace(step, apply=fail_after_write)))
        with pytest.raises(RuntimeError, match='injected failure'):
            upgrade(path)
    with closing(sqlite3.connect(path)) as db:
        assert db.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0] == 56
        assert db.execute("SELECT value FROM app_metadata WHERE key='workspace.layout_preferences'").fetchone()[0] == payload
    upgrade(path)
    with closing(sqlite3.connect(path)) as db:
        assert json.loads(db.execute("SELECT value FROM app_metadata WHERE key='workspace.layout_preferences'").fetchone()[0]) == {'version': 7, 'keep': True}
