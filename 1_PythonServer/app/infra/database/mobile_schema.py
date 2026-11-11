"""Channel configuration and delivery bookkeeping; conversation contents stay in projects."""

MOBILE_SCHEMA = (
    """CREATE TABLE mobile_records (
        namespace TEXT NOT NULL, record_key TEXT NOT NULL,
        payload TEXT NOT NULL, updated_at REAL NOT NULL,
        connection_id TEXT NOT NULL DEFAULT '',
        PRIMARY KEY(namespace, record_key)
    )""",
    """CREATE TABLE mobile_receipts (
        channel TEXT NOT NULL, update_id TEXT NOT NULL, received_at REAL NOT NULL,
        PRIMARY KEY(channel, update_id)
    )""",
    """CREATE INDEX mobile_records_connection ON mobile_records(namespace, connection_id, updated_at)""",
    """CREATE TABLE mobile_connections (
        connection_id TEXT PRIMARY KEY, platform TEXT NOT NULL, remote_id TEXT NOT NULL,
        payload TEXT NOT NULL, updated_at REAL NOT NULL,
        UNIQUE(platform, remote_id)
    )""",
)
