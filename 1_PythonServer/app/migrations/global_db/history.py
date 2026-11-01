"""Historical global steps. Keep export sources until their separate import succeeds."""

from datetime import UTC, datetime
from functools import lru_cache, partial
import json
from pathlib import Path
import sqlite3

from app.migrations.runner import Migration
from app.migrations.sql import execute_script

_STEPS = Path(__file__).with_name("steps")


def _upgrade(connection: sqlite3.Connection, definition: dict) -> None:
    for column in definition["add_columns"]:
        table, name = column["table_name"], column["column_name"]
        columns = {row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')}
        if not columns:
            raise RuntimeError(f"Historical migration source table is missing: {table}")
        if name not in columns:
            connection.execute(f'ALTER TABLE "{table}" ADD COLUMN "{name}" {column["column_definition"]}')
    version = definition["version"]
    try:
        execute_script(connection, (_STEPS / f"v{version:02d}.sql").read_text(encoding="utf-8"))
    except sqlite3.OperationalError as exc:
        raise RuntimeError(f"Unsupported global database structure before migration v{version}: {exc}") from exc
    connection.execute(
        "INSERT INTO schema_migrations(version,name,applied_at) VALUES (?,?,?)",
        (version, definition["name"], datetime.now(UTC).isoformat()),
    )


@lru_cache
def historical_steps() -> tuple[Migration, ...]:
    definitions = json.loads((_STEPS / "registry.json").read_text(encoding="utf-8"))
    # Versions 20–24 were never present in the surviving release registry.
    return tuple(
        Migration(source, definition["version"], definition["name"], partial(_upgrade, definition=definition))
        for source in range(48)
        if (definition := next((d for d in definitions if d["version"] > source), None))
    )
