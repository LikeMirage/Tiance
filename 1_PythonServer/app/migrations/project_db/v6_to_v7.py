"""Version the compression indexes that were previously added without a version bump."""

import sqlite3


_INDEXES = {
    "idx_compression_record_id": """CREATE INDEX idx_compression_record_id
        ON conversation_session_events(session_id, json_extract(payload_json, '$.compression_id'))
        WHERE kind = 'compressions'""",
    "idx_compression_status": """CREATE INDEX idx_compression_status
        ON conversation_session_events(session_id, json_extract(payload_json, '$.source_type'),
            json_extract(payload_json, '$.status'), ordinal DESC)
        WHERE kind = 'compressions'""",
}


def upgrade(connection: sqlite3.Connection) -> None:
    for name, statement in _INDEXES.items():
        existing = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' AND name=?", (name,),
        ).fetchone()
        if existing is None:
            connection.execute(statement)
        elif _normalized(existing[0]) != _normalized(statement):
            raise RuntimeError(f"Project compression index {name} has an unexpected definition.")
    connection.execute("UPDATE conversation_schema SET version=7 WHERE version=6")


def _normalized(statement: str) -> str:
    return "".join(statement.split()).lower().replace("ifnotexists", "").rstrip(";")
