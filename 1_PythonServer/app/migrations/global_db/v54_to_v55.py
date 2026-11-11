"""Keep each WeChat receive cursor under its owning connection's key."""
from datetime import UTC, datetime


def upgrade(connection):
    connection.execute("""
        UPDATE mobile_records SET record_key=connection_id
        WHERE namespace='offsets' AND record_key='wechat'
          AND connection_id LIKE 'wechat:%'
    """)
    connection.execute('INSERT INTO schema_migrations VALUES (55, ?, ?)',
                       ('wechat_connection_cursor', datetime.now(UTC).isoformat()))
