"""Project database migration registry, shared by every project collection."""

import sqlite3

from app.migrations.runner import Migration, migrate


def read_version(connection: sqlite3.Connection) -> int | None:
    try:
        rows = connection.execute("SELECT version FROM conversation_schema").fetchall()
    except sqlite3.OperationalError:
        return None
    return rows[0][0] if len(rows) == 1 and type(rows[0][0]) is int else None


def ensure_version(connection: sqlite3.Connection, target: int) -> None:
    from app.migrations.project_db.v1_to_v2 import upgrade as v2
    from app.migrations.project_db.v2_to_v3 import upgrade as v3
    from app.migrations.project_db.v3_to_v4 import upgrade as v4
    from app.migrations.project_db.v4_to_v5 import upgrade as v5
    # Audit storage codecs are loaded only when schema initialization is requested.
    from app.migrations.project_db.v5_to_v6 import upgrade
    from app.migrations.project_db.v6_to_v7 import upgrade as upgrade_indexes
    from app.migrations.project_db.v7_to_v8 import upgrade as upgrade_payloads

    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    required = {"conversation_schema", "conversation_meta", "conversation_sessions", "conversation_messages",
                "conversation_session_documents", "conversation_session_events", "conversation_project_events"}
    if not required <= tables:
        raise RuntimeError("Unsupported project database structure; original data was preserved.")
    migrate(
        connection, database="project conversation", target=target, read_version=read_version,
        migrations=(
            Migration(1, 2, "artifacts_and_journal", v2),
            Migration(2, 3, "embedded_artifacts", v3),
            Migration(3, 4, "separate_session_state", v4),
            Migration(4, 5, "conversation_runs", v5),
            Migration(5, 6, "incremental_audit_snapshots", upgrade),
            Migration(6, 7, "compression_record_indexes", upgrade_indexes),
            Migration(7, 8, "legacy_payload_contracts", upgrade_payloads),
        ),
    )
