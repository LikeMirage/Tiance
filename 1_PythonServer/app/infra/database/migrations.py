# 数据库迁移执行器
# 按版本顺序应用未执行的迁移，记录到 schema_migrations 表

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
import re
import sqlite3

from app.infra.database.sqlite import connect_database, database_transaction


_SQL_IDENTIFIER_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


@dataclass(frozen=True, slots=True)
class AddColumnIfMissing:
    """Idempotent schema step for migrations that add columns."""

    table_name: str
    column_name: str
    column_definition: str

    def execute(self, connection: sqlite3.Connection) -> None:
        table_name = _validate_identifier(self.table_name)
        column_name = _validate_identifier(self.column_name)
        table_exists = connection.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table' AND name = ?
            """,
            (table_name,),
        ).fetchone()
        if table_exists is None:
            raise RuntimeError(f"Database table '{table_name}' does not exist.")
        columns = {
            str(row["name"])
            for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
        }
        if column_name in columns:
            return
        connection.execute(
            f"ALTER TABLE {table_name} ADD COLUMN {column_name} {self.column_definition}"
        )


MigrationStatement = str | AddColumnIfMissing


@dataclass(frozen=True, slots=True)
class Migration:
    """单个迁移定义：版本号、名称、SQL 语句列表"""
    version: int
    name: str
    statements: tuple[MigrationStatement, ...]
    foreign_keys_disabled: bool = False


def run_database_migrations(database_path: Path, migrations: tuple[Migration, ...]) -> None:
    """按版本顺序执行所有未应用的迁移，每个迁移独立保持原子性。"""
    with database_transaction(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT NOT NULL
            )
            """
        )
        applied_versions = {
            int(row["version"])
            for row in connection.execute("SELECT version FROM schema_migrations").fetchall()
        }

    for migration in sorted(migrations, key=lambda item: item.version):
        if migration.version in applied_versions:
            continue
        if migration.foreign_keys_disabled:
            _run_migration_without_foreign_keys(database_path, migration)
        else:
            with database_transaction(database_path) as connection:
                _execute_migration(connection, migration)
        applied_versions.add(migration.version)


def _run_migration_without_foreign_keys(
    database_path: Path,
    migration: Migration,
) -> None:
    """仅供需要重建被外键引用表的迁移使用。"""
    connection = connect_database(database_path)
    try:
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute("BEGIN")
        _execute_migration(connection, migration)
        violations = connection.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise RuntimeError(
                f"Migration {migration.version} left foreign key violations."
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _execute_migration(
    connection: sqlite3.Connection,
    migration: Migration,
) -> None:
    for statement in migration.statements:
        if isinstance(statement, str):
            connection.execute(statement)
        else:
            statement.execute(connection)
    connection.execute(
        """
        INSERT INTO schema_migrations (version, name, applied_at)
        VALUES (?, ?, ?)
        """,
        (
            migration.version,
            migration.name,
            datetime.now(UTC).isoformat(),
        ),
    )


def _validate_identifier(value: str) -> str:
    if not _SQL_IDENTIFIER_PATTERN.fullmatch(value):
        raise ValueError(f"Unsafe SQL identifier: {value!r}")
    return value
