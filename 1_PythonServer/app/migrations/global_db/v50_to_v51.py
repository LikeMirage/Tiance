from datetime import UTC, datetime

# Historical migrations must not import the latest schema.
MOBILE_SCHEMA = (
    "CREATE TABLE mobile_records (namespace TEXT NOT NULL, record_key TEXT NOT NULL, "
    "payload TEXT NOT NULL, updated_at REAL NOT NULL, PRIMARY KEY(namespace, record_key))",
    "CREATE TABLE mobile_receipts (channel TEXT NOT NULL, update_id TEXT NOT NULL, "
    "received_at REAL NOT NULL, PRIMARY KEY(channel, update_id))",
)


def upgrade(connection):
    for statement in MOBILE_SCHEMA:
        connection.execute(statement)
    connection.execute("INSERT INTO schema_migrations VALUES (51, ?, ?)",
                       ("mobile_channel_state", datetime.now(UTC).isoformat()))
