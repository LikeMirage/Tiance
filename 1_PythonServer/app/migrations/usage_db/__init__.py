"""Usage database version boundary; v1 is currently the first supported schema."""

import sqlite3

from app.migrations.runner import Migration, migrate

MIGRATIONS: tuple[Migration, ...] = ()


def read_version(connection: sqlite3.Connection) -> int:
    return connection.execute("PRAGMA user_version").fetchone()[0]


def ensure_version(connection: sqlite3.Connection, target: int) -> None:
    migrate(connection, database="usage", target=target, read_version=read_version, migrations=MIGRATIONS)
