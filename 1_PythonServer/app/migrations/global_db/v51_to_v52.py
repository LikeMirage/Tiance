"""Scope existing transport state without touching project conversation history."""
import json
import re
from datetime import UTC, datetime


def upgrade(connection):
    connection.execute("ALTER TABLE mobile_records ADD COLUMN connection_id TEXT NOT NULL DEFAULT ''")
    connection.execute("CREATE INDEX mobile_records_connection ON mobile_records(namespace, connection_id, updated_at)")
    connection.execute("CREATE TABLE mobile_connections (connection_id TEXT PRIMARY KEY, platform TEXT NOT NULL, "
                       "remote_id TEXT NOT NULL, payload TEXT NOT NULL, updated_at REAL NOT NULL, UNIQUE(platform, remote_id))")
    rows = connection.execute("SELECT namespace,record_key,payload,updated_at FROM mobile_records").fetchall()
    scopes = {}
    job_scopes = {}
    for namespace, key, raw, updated_at in rows:
        item = json.loads(raw)
        candidate = (item.get('peer') or item.get('channel')) if isinstance(item, dict) else None
        match = re.match(r'^(telegram:\d+)(?::|$)', candidate or key)
        if match:
            scopes[(namespace, key)] = match[1]
            if namespace == 'jobs' and isinstance(item, dict) and item.get('user_message_id'):
                job_scopes[item['user_message_id']] = match[1]
    for namespace, key, raw, updated_at in rows:
        scope = scopes.get((namespace, key), '')
        if namespace == 'delivered':
            scope = scopes.get(('outbox', key), job_scopes.get(key.split(':', 1)[0], scope))
        if scope:
            connection.execute("UPDATE mobile_records SET connection_id=? WHERE namespace=? AND record_key=?",
                               (scope, namespace, key))
        if namespace == 'settings' and key == 'telegram':
            config = json.loads(raw)
            bot_id = config.get('bot', {}).get('id')
            if bot_id is not None:
                connection_id = f'telegram:{bot_id}'
                connection.execute("INSERT INTO mobile_connections VALUES (?,?,?,?,?)",
                                   (connection_id, 'telegram', str(bot_id), raw, updated_at))
                connection.execute("INSERT INTO mobile_records(namespace,record_key,payload,updated_at) VALUES (?,?,?,?)",
                                   ('settings', 'telegram_selected', json.dumps(connection_id), updated_at))
                connection.execute("DELETE FROM mobile_records WHERE namespace='settings' AND record_key='telegram'")
            # Invalid/incomplete old settings are retained for diagnosis, never guessed.
    # The old single-config page could replace a bot while its jobs were still
    # pending. Keep those bot identities disabled, without inventing credentials;
    # their results can be queued safely and delivered after reconnection.
    for scope in set(scopes.values()):
        remote_id = scope.split(':', 1)[1]
        dormant = dict(enabled=False, api_base='https://api.telegram.org',
                       bot={'id': int(remote_id), 'first_name': f'Telegram {remote_id}'})
        connection.execute('INSERT OR IGNORE INTO mobile_connections VALUES (?,?,?,?,?)',
                           (scope, 'telegram', remote_id, json.dumps(dormant), 0))
    connection.execute("INSERT INTO schema_migrations VALUES (52, ?, ?)",
                       ('mobile_connections', datetime.now(UTC).isoformat()))
