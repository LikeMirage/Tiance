from concurrent.futures import ThreadPoolExecutor
from threading import Event
import sqlite3

import pytest

from app.repositories.project import conversation_database as db


def test_all_writer_entry_points_share_nested_transaction_and_rollback(tmp_path):
    folder = tmp_path / '.Tiance' / 'conversations'
    path = db.ensure_database(folder.parent)
    with pytest.raises(ValueError):
        with db.connection_for_path(path) as outer:
            db.write_meta(folder, 'first', 1)
            with db.transaction_for_conversations(folder) as inner:
                assert inner is outer
                db.write_meta(folder, 'second', 2)
            raise ValueError('rollback both')
    assert db.read_meta(folder, 'first') is None
    assert db.read_meta(folder, 'second') is None


def test_writers_wait_in_project_order_while_wal_reads_and_other_projects_continue(tmp_path, monkeypatch):
    folder = tmp_path / 'one' / '.Tiance' / 'conversations'
    other = tmp_path / 'two' / '.Tiance' / 'conversations'
    db.write_meta(folder, 'value', 'committed')
    db.write_meta(other, 'value', 'other')
    real_open = db._open_connection
    def open_with_short_sqlite_timeout(path):
        connection = real_open(path)
        connection.execute('PRAGMA busy_timeout=1')
        return connection
    monkeypatch.setattr(db, '_open_connection', open_with_short_sqlite_timeout)
    started, release, second_started = Event(), Event(), Event()
    def first_writer():
        with db.transaction_for_conversations(folder):
            db.write_meta(folder, 'value', 'new')
            started.set()
            assert release.wait(4)
    def second_writer():
        second_started.set()
        db.write_meta(folder, 'second', 'saved')
    with ThreadPoolExecutor(4) as pool:
        first = pool.submit(first_writer)
        try:
            assert started.wait(2)
            second = pool.submit(second_writer)
            assert second_started.wait(2)
            assert pool.submit(db.read_meta, folder, 'value').result(2) == 'committed'
            pool.submit(db.write_meta, other, 'value', 'changed').result(2)
            # The second writer cannot fail with SQLite busy_timeout or race the first.
            assert not second.done()
        finally:
            release.set()
        first.result(2)
        second.result(2)
    assert db.read_meta(folder, 'value') == 'new'
    assert db.read_meta(folder, 'second') == 'saved'
    assert db.read_meta(other, 'value') == 'changed'


def test_failed_begin_closes_connection_and_allows_retry(tmp_path, monkeypatch):
    path = db.ensure_database(tmp_path)
    class BrokenConnection:
        closed = False
        def execute(self, _sql):
            raise sqlite3.OperationalError('injected BEGIN failure')
        def rollback(self):
            pass
        def close(self):
            self.closed = True
    broken = BrokenConnection()
    real_open = db._open_connection
    monkeypatch.setattr(db, '_open_connection', lambda _: broken)
    with pytest.raises(sqlite3.OperationalError):
        with db.connection_for_path(path):
            pytest.fail('must not enter')
    assert broken.closed
    monkeypatch.setattr(db, '_open_connection', real_open)
    with db.connection_for_path(path) as connection:
        assert connection.execute('SELECT 1').fetchone()[0] == 1


def test_audit_compression_does_not_hold_project_write_transaction(tmp_path, monkeypatch):
    folder = tmp_path / '.Tiance' / 'conversations'
    session = folder / 'sessions' / 's'
    db.write_meta(folder, 'ready', True)
    db.write_session(folder, 's', {'session_id': 's'})
    preparing, release = Event(), Event()
    real_prepare = db.prepare_audit_snapshot
    def prepare(payload):
        preparing.set()
        assert release.wait(3)
        return real_prepare(payload)
    monkeypatch.setattr(db, 'prepare_audit_snapshot', prepare)
    with ThreadPoolExecutor(2) as pool:
        audit = pool.submit(db.append_event, session, 'model_exchanges', {'content': 'large' * 1000})
        try:
            assert preparing.wait(2)
            pool.submit(db.write_meta, folder, 'during_compression', True).result(1)
        finally:
            release.set()
        audit.result(2)
    assert db.read_meta(folder, 'during_compression') is True
