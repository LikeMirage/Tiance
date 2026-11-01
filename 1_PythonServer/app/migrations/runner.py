"""Shared SQLite migration mechanics; database schemas and data stay in their steps."""

from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
import logging
import os
from pathlib import Path
import sqlite3
from tempfile import mkstemp
from uuid import uuid4

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Migration:
    source: int
    target: int
    name: str
    apply: Callable[[sqlite3.Connection], object]


@contextmanager
def schema_transaction(connection: sqlite3.Connection) -> Iterator[None]:
    """Serialize initialization across connections and roll back the entire upgrade."""
    owns_transaction = not connection.in_transaction
    if owns_transaction:
        connection.execute("BEGIN IMMEDIATE")
    connection.execute("SAVEPOINT database_schema")
    try:
        yield
    except BaseException:
        connection.execute("ROLLBACK TO database_schema")
        connection.execute("RELEASE database_schema")
        if owns_transaction:
            connection.rollback()
        raise
    else:
        connection.execute("RELEASE database_schema")
        if owns_transaction:
            try:
                connection.commit()
            except BaseException:
                connection.rollback()
                raise


def migrate(
    connection: sqlite3.Connection,
    *,
    database: str,
    target: int,
    read_version: Callable[[sqlite3.Connection], int | None],
    migrations: tuple[Migration, ...],
) -> None:
    """Resolve the full path before any write; caller owns the schema transaction."""
    version = read_version(connection)
    if version == target:
        return
    by_source: dict[int, Migration] = {}
    for step in migrations:
        if step.source >= step.target or step.source in by_source:
            raise RuntimeError(f"Invalid {database} migration registry at version {step.source}.")
        by_source[step.source] = step
    chain = []
    current = version
    while current != target:
        step = by_source.get(current)
        if step is None or step.target > target:
            raise RuntimeError(
                f"Unsupported {database} database version: {version}; expected {target}. "
                "No data was converted or removed."
            )
        chain.append(step)
        current = step.target
    if not connection.in_transaction:
        raise RuntimeError("Database migrations require the schema transaction.")
    check_integrity(connection)
    backup = backup_database(connection, version, target)
    for step in chain:
        step.apply(connection)
        if read_version(connection) != step.target:
            raise RuntimeError(f"Migration {step.name} did not record version {step.target}.")
    check_integrity(connection)
    logger.info("Prepared %s database upgrade v%s to v%s; backup=%s", database, version, target, backup)


def check_integrity(connection: sqlite3.Connection) -> None:
    if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
        raise RuntimeError("Database migration failed the SQLite integrity check.")
    if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise RuntimeError("Database migration failed the SQLite foreign key check.")


def backup_database(connection: sqlite3.Connection, source: int | str, target: int | str) -> Path | None:
    """Use SQLite backup under the caller's write lock, including committed WAL data."""
    filename = next(row[2] for row in connection.execute("PRAGMA database_list") if row[1] == "main")
    if not filename:  # In-memory databases have no on-disk state to back up.
        return None
    path = Path(filename).resolve()
    suffix = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    backup = path.with_name(f"{path.name}.before-v{source}-to-v{target}.{suffix}.{uuid4().hex}.bak")
    fd, temp_name = mkstemp(prefix=f".{path.name}.backup-", suffix=".tmp", dir=path.parent)
    os.close(fd)
    temp = Path(temp_name)
    try:
        with (
            closing(sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)) as reader,
            closing(sqlite3.connect(temp)) as output,
        ):
            reader.backup(output)
            check_integrity(output)
        if backup.exists():
            raise FileExistsError(backup)
        os.replace(temp, backup)
        return backup
    finally:
        temp.unlink(missing_ok=True)
