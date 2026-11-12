"""Global database migration registry."""

import sqlite3

from app.migrations.global_db.v48_to_v49 import upgrade
from app.migrations.global_db.v49_to_v50 import upgrade as upgrade_default_roles
from app.migrations.global_db.v50_to_v51 import upgrade as upgrade_mobile
from app.migrations.global_db.v51_to_v52 import upgrade as upgrade_mobile_connections
from app.migrations.global_db.v52_to_v53 import upgrade as upgrade_telegram_scope
from app.migrations.global_db.v53_to_v54 import upgrade as upgrade_mobile_scope
from app.migrations.global_db.v54_to_v55 import upgrade as upgrade_wechat_cursor
from app.migrations.global_db.v55_to_v56 import upgrade as upgrade_menu_paths
from app.migrations.global_db.history import historical_steps
from app.migrations.runner import Migration, migrate

MIGRATIONS = (
    Migration(48, 49, "workspace_activity_run_identity", upgrade),
    Migration(49, 50, "collection_default_roles", upgrade_default_roles),
    Migration(50, 51, "mobile_channel_state", upgrade_mobile),
    Migration(51, 52, "mobile_connections", upgrade_mobile_connections),
    Migration(52, 53, "telegram_collection_access", upgrade_telegram_scope),
    Migration(53, 54, "mobile_collection_access", upgrade_mobile_scope),
    Migration(54, 55, "wechat_connection_cursor", upgrade_wechat_cursor),
    Migration(55, 56, "mobile_menu_paths", upgrade_menu_paths),
)


def read_version(connection: sqlite3.Connection) -> int | None:
    try:
        row = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
    except sqlite3.OperationalError:
        return None
    return row[0] if row and type(row[0]) is int else None


def ensure_version(connection: sqlite3.Connection, target: int) -> None:
    migrate(connection, database="global", target=target, read_version=read_version, migrations=historical_steps() + MIGRATIONS)
