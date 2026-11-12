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

    def remove_peer(self, peer):
        if not self.connection_id:
            raise ValueError('删除用户需要明确的连接标识。')
        with self._transaction() as connection:
            identity = connection.execute("SELECT 1 FROM mobile_records WHERE namespace='peers' AND record_key=? AND connection_id=?",
                                          (peer, self.connection_id)).fetchone()
            if not identity:
                raise ValueError('该接入用户不存在。')
            # Keep only the deletion decision, not the profile or routing data.
            # Otherwise the next inbound event would register this peer anew.
            self._put(connection, 'deleted_peers', peer, True)
            # Exact ownership checks, not LIKE: platform identities may contain
            # wildcard characters. Receipts remain so old input cannot replay.
            connection.execute("""DELETE FROM mobile_records WHERE connection_id=? AND (
                (namespace IN ('peers','selection','navigation','menus','reply_context') AND record_key=?)
                OR (namespace IN ('staged','messages') AND substr(record_key,1,length(?)+1)=?||':')
                OR (namespace IN ('callbacks','outbox','inbox') AND json_extract(payload,'$.peer')=?)
            )""", (self.connection_id, peer, peer, peer, peer))

    def confirm_peer(self, peer, identity):
        """Restore access only after an explicit, trusted identity confirmation."""
        if not self.connection_id:
            raise ValueError('确认用户需要明确的连接标识。')
        with self._transaction() as connection:
            self._put(connection, 'peers', peer, identity)
            connection.execute("DELETE FROM mobile_records WHERE namespace='deleted_peers' AND record_key=? AND connection_id=?",
                               (peer, self.connection_id))

    def remove_connection(self, platform):
        if not self.connection_id:
            raise ValueError('删除连接需要明确的连接标识。')
        with self._transaction() as connection:
            deleted = connection.execute('DELETE FROM mobile_connections WHERE connection_id=? AND platform=?',
                                         (self.connection_id, platform)).rowcount
            if not deleted:
                raise ValueError('连接不存在或不属于此平台。')
            connection.execute('DELETE FROM mobile_records WHERE connection_id=?', (self.connection_id,))
            # Keep dedup receipts: rebinding the same bot must not replay input.
            selected = connection.execute("SELECT payload FROM mobile_records WHERE namespace='settings' AND record_key=?",
                                          (platform + '_selected',)).fetchone()
            if selected and json.loads(selected[0]) == self.connection_id:
                remaining = connection.execute('SELECT connection_id FROM mobile_connections WHERE platform=? ORDER BY connection_id LIMIT 1',
                                               (platform,)).fetchone()
                if remaining:
                    self._put(connection, 'settings', platform + '_selected', remaining[0], scope='')
                else:
                    connection.execute("DELETE FROM mobile_records WHERE namespace='settings' AND record_key=?", (platform + '_selected',))

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

    def list_peers(self, platform: str) -> list[tuple[str, dict]]:
        """Read account ownership from the same column used for scoped access."""
        clause = ' AND p.connection_id=?' if self.connection_id is not None else ''
        args = (platform, self.connection_id) if self.connection_id is not None else (platform,)
        with database_connection(self.path) as connection:
            rows = connection.execute(
                "SELECT p.record_key,p.payload,p.connection_id,c.platform FROM mobile_records p "
                "JOIN mobile_connections c ON c.connection_id=p.connection_id "
                "WHERE p.namespace='peers' AND c.platform=?" + clause + " ORDER BY p.record_key", args,
            ).fetchall()
        # Older payloads need not duplicate these fields. Never let a payload
        # override the persisted ownership or move an account across channels.
        return [(r[0], dict(json.loads(r[1]), connection_id=r[2], platform=r[3])) for r in rows]

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
            self._put(connection,'messages',f"{item['peer']}:{message_id}",{'target':None if item.get('menu') else item['target']})
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
