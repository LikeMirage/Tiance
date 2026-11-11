from __future__ import annotations

import json
import time
from uuid import uuid4
from contextlib import contextmanager
from pathlib import Path
from app.infra.database import database_connection


class MobileRepository:
    ACTIVITY_LIMIT = 1000

    def __init__(self, path: Path, connection_id: str | None = None):
        self.path = path
        self.connection_id = connection_id

    def scoped(self, connection_id: str):
        return MobileRepository(self.path, connection_id)

    def record_connection(self, namespace, key):
        with database_connection(self.path) as connection:
            row = connection.execute('SELECT connection_id FROM mobile_records WHERE namespace=? AND record_key=?', (namespace, key)).fetchone()
        return row[0] if row else None

    def _scope(self):
        return (" AND connection_id=?", (self.connection_id,)) if self.connection_id is not None else ("", ())

    def connections(self, platform=None):
        with database_connection(self.path) as connection:
            rows = connection.execute(
                "SELECT connection_id,platform,remote_id,payload FROM mobile_connections" +
                (" WHERE platform=?" if platform else "") + " ORDER BY connection_id",
                (platform,) if platform else (),
            ).fetchall()
        return [dict(connection_id=r[0], platform=r[1], remote_id=r[2], config=json.loads(r[3])) for r in rows]

    def save_connection(self, connection_id, platform, remote_id, config, *, select=False):
        with self._transaction() as connection:
            previous = connection.execute("SELECT platform,remote_id FROM mobile_connections WHERE connection_id=?", (connection_id,)).fetchone()
            if previous and tuple(previous) != (platform, str(remote_id)):
                raise ValueError('连接身份不可更换，请创建新的连接。')
            connection.execute("INSERT INTO mobile_connections VALUES (?,?,?,?,?) ON CONFLICT(connection_id) "
                               "DO UPDATE SET payload=excluded.payload,updated_at=excluded.updated_at",
                               (connection_id, platform, str(remote_id), json.dumps(config, ensure_ascii=False), time.time()))
            if select:
                self._put(connection, 'settings', platform + '_selected', connection_id)

    @contextmanager
    def _transaction(self):
        # Serialize short read-modify-write operations before reading staged data.
        with database_connection(self.path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    def get(self, namespace: str, key: str, default=None):
        clause, args = self._scope()
        with database_connection(self.path) as connection:
            row = connection.execute(
                "SELECT payload FROM mobile_records WHERE namespace=? AND record_key=?" + clause,
                (namespace, key, *args),
            ).fetchone()
        return json.loads(row[0]) if row else default

    def put(self, namespace: str, key: str, payload) -> None:
        with self._transaction() as connection:
            self._put(connection, namespace, key, payload)

    def delete(self, namespace: str, key: str) -> None:
        clause, args = self._scope()
        with self._transaction() as connection:
            connection.execute("DELETE FROM mobile_records WHERE namespace=? AND record_key=?" + clause, (namespace, key, *args))

    def list(self, namespace: str) -> list[tuple[str, dict]]:
        clause, args = self._scope()
        with database_connection(self.path) as connection:
            rows = connection.execute(
                "SELECT record_key,payload FROM mobile_records WHERE namespace=?" + clause + " ORDER BY updated_at", (namespace, *args),
            ).fetchall()
        return [(row[0], json.loads(row[1])) for row in rows]

    def receive(self, channel: str, update_id: str, payload: dict) -> bool:
        """Persist before advancing a platform cursor. Duplicate deliveries never resubmit."""
        if self.connection_id is not None and channel != self.connection_id:
            raise ValueError('接收游标不属于当前连接。')
        key = f"{channel}:{update_id}"
        with self._transaction() as connection:
            inserted = connection.execute("INSERT OR IGNORE INTO mobile_receipts VALUES (?,?,?)",
                                          (channel, update_id, time.time())).rowcount
            if inserted:
                self._put(connection, "inbox", key, payload, scope=channel)
        return bool(inserted)

    def append_staged(self, key, references):
        with self._transaction() as connection:
            row = connection.execute("SELECT payload FROM mobile_records WHERE namespace='staged' AND record_key=?", (key,)).fetchone()
            refs = json.loads(row[0]) if row else []
            known = {r['reference']['id'] for r in refs}
            refs.extend(r for r in references if r['reference']['id'] not in known)
            self._put(connection, 'staged', key, refs)

    def discard_unowned_empty_staging(self):
        """Remove only empty placeholders created by the old global job writer.

        A peer belonging to this connection must identify the key. Never adopt
        another connection's records or discard actual staged references.
        """
        if not self.connection_id:
            return
        with self._transaction() as connection:
            connection.execute("""
                DELETE FROM mobile_records AS s
                WHERE s.namespace='staged' AND s.connection_id=''
                  AND json_type(s.payload)='array' AND json_array_length(s.payload)=0
                  AND EXISTS (
                    SELECT 1 FROM mobile_records p
                    WHERE p.namespace='peers' AND p.connection_id=?
                      AND substr(s.record_key,1,length(p.record_key)+1)=p.record_key||':'
                  )
            """, (self.connection_id,))

    def _put(self, connection, namespace, key, payload, *, scope=None):
        previous = connection.execute("SELECT connection_id FROM mobile_records WHERE namespace=? AND record_key=?", (namespace,key)).fetchone()
        scope = self.connection_id if scope is None else scope
        if previous and scope is not None and previous[0] != scope:
            raise ValueError('接入记录不属于当前连接。')
        scope = scope if scope is not None else (previous[0] if previous else '')
        connection.execute("INSERT INTO mobile_records(namespace,record_key,payload,updated_at,connection_id) VALUES (?,?,?,?,?) "
                           "ON CONFLICT(namespace,record_key) DO UPDATE SET payload=excluded.payload,updated_at=excluded.updated_at",
                           (namespace,key,json.dumps(payload,ensure_ascii=False),time.time(),scope))

    def create_job(self, key, job, staging_key=None):
        with self._transaction() as connection:
            peer = connection.execute("SELECT connection_id FROM mobile_records WHERE namespace='peers' AND record_key=?", (job.get('peer',''),)).fetchone()
            scope = peer[0] if peer else self.connection_id
            job = dict(job, connection_id=scope or '')
            self._put(connection,'jobs',key,job,scope=scope)
            if staging_key:
                row = connection.execute("SELECT payload,connection_id FROM mobile_records WHERE namespace='staged' AND record_key=?", (staging_key,)).fetchone()
                if row:
                    if scope is not None and row[1] != scope:
                        raise ValueError('接入记录不属于当前连接。')
                    refs = json.loads(row[0])
                    consumed = {r['reference']['id'] for r in job['references']}
                    self._put(connection,'staged',staging_key,[r for r in refs if r['reference']['id'] not in consumed],scope=scope)
                # A text-only submission has no staging record to consume.
                # Do not create an unscoped empty row from the global bridge.
        return job

    def delivery_progress(self, key, item, message_id):
        with self._transaction() as connection:
            self._put(connection,'messages',f"{item['peer']}:{message_id}",{'target':item['target']})
            self._put(connection,'outbox',key,item)

    def append_activity(self, event, level, details):
        """Bounded diagnostics, separate from inbox/outbox and deduplication facts."""
        scope = self.connection_id or ''
        payload = {'event': event, 'level': level, 'details': details, 'time': time.time()}
        with self._transaction() as connection:
            self._put(connection, 'activity', uuid4().hex, payload, scope=scope)
            connection.execute(
                "DELETE FROM mobile_records WHERE namespace='activity' AND connection_id=? AND record_key IN "
                "(SELECT record_key FROM mobile_records WHERE namespace='activity' AND connection_id=? "
                "ORDER BY updated_at DESC,record_key DESC LIMIT -1 OFFSET ?)",
                (scope, scope, self.ACTIVITY_LIMIT),
            )

    def activity_page(self, offset=0, limit=50):
        scope = self.connection_id or ''
        with database_connection(self.path) as connection:
            total = connection.execute(
                "SELECT COUNT(*) FROM mobile_records WHERE namespace='activity' AND connection_id=?", (scope,),
            ).fetchone()[0]
            rows = connection.execute(
                "SELECT record_key,payload FROM mobile_records WHERE namespace='activity' AND connection_id=? "
                "ORDER BY updated_at DESC,record_key DESC LIMIT ? OFFSET ?", (scope, limit, offset),
            ).fetchall()
        return {'items': [dict(json.loads(row[1]), id=row[0]) for row in rows],
                'total': total, 'offset': offset, 'limit': limit, 'retention': self.ACTIVITY_LIMIT}
