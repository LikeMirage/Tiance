"""Default existing WeChat and Feishu connections to the project collection."""
import json
from datetime import UTC, datetime


def upgrade(connection):
    rows = connection.execute("SELECT connection_id,payload FROM mobile_connections WHERE platform IN ('wechat','feishu')").fetchall()
    for key, raw in rows:
        config = json.loads(raw)
        config.setdefault('allowed_collections', ['project'])
        connection.execute('UPDATE mobile_connections SET payload=? WHERE connection_id=?',
                           (json.dumps(config, ensure_ascii=False), key))
    connection.execute('INSERT INTO schema_migrations VALUES (54, ?, ?)',
                       ('mobile_collection_access', datetime.now(UTC).isoformat()))
