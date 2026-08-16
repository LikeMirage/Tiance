from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager
from json import dumps, loads
import logging
from pathlib import Path
import sqlite3
from threading import Lock
from typing import Any, Iterator


LOGGER = logging.getLogger(__name__)
CACHE_DIRECTORY = "cache"
CACHE_DATABASE_FILE = "conversation-index.db"
CACHE_SCHEMA_VERSION = 1
_initialization_lock = Lock()
_initialized_paths: set[Path] = set()

MessageLoader = Callable[[], list[dict[str, Any]]]


def cache_database_path(session_dir: Path) -> Path:
    workspace_dir = session_dir.parent.parent.parent
    return workspace_dir / CACHE_DIRECTORY / CACHE_DATABASE_FILE


def list_payloads(session_dir: Path, loader: MessageLoader) -> list[dict[str, Any]]:
    try:
        with _current_connection(session_dir, loader) as connection:
            rows = connection.execute(
                "SELECT payload_json FROM message_index WHERE session_id = ? ORDER BY ordinal",
                (_session_id(session_dir),),
            ).fetchall()
        return [_decode(row[0]) for row in rows]
    except (OSError, sqlite3.Error, ValueError) as exc:
        LOGGER.warning("Message cache unavailable; reading canonical files: %s", exc)
        return loader()


def count_payloads(session_dir: Path, loader: MessageLoader) -> int:
    try:
        with _current_connection(session_dir, loader) as connection:
            row = connection.execute(
                "SELECT COUNT(*) FROM message_index WHERE session_id = ?",
                (_session_id(session_dir),),
            ).fetchone()
        return int(row[0]) if row is not None else 0
    except (OSError, sqlite3.Error, ValueError) as exc:
        LOGGER.warning("Message cache unavailable; counting canonical files: %s", exc)
        return len(loader())


def find_ordinal(session_dir: Path, message_id: str, loader: MessageLoader) -> int | None:
    try:
        with _current_connection(session_dir, loader) as connection:
            row = connection.execute(
                """
                SELECT ordinal FROM message_index
                WHERE session_id = ? AND message_id = ?
                """,
                (_session_id(session_dir), message_id),
            ).fetchone()
        return int(row[0]) if row is not None else None
    except (OSError, sqlite3.Error, ValueError) as exc:
        LOGGER.warning("Message cache unavailable; searching canonical files: %s", exc)
        return next(
            (
                ordinal
                for ordinal, payload in enumerate(loader())
                if str(payload.get("message_id") or "") == message_id
            ),
            None,
        )


def list_payload_range(
    session_dir: Path,
    *,
    start_ordinal: int,
    end_ordinal: int,
    loader: MessageLoader,
) -> list[dict[str, Any]]:
    try:
        with _current_connection(session_dir, loader) as connection:
            rows = connection.execute(
                """
                SELECT payload_json FROM message_index
                WHERE session_id = ? AND ordinal >= ? AND ordinal < ?
                ORDER BY ordinal
                """,
                (_session_id(session_dir), start_ordinal, end_ordinal),
            ).fetchall()
        return [_decode(row[0]) for row in rows]
    except (OSError, sqlite3.Error, ValueError) as exc:
        LOGGER.warning("Message cache unavailable; slicing canonical files: %s", exc)
        return loader()[start_ordinal:end_ordinal]


def read_turn(
    session_dir: Path,
    message_id: str,
    loader: MessageLoader,
) -> tuple[str | None, list[dict[str, Any]]]:
    try:
        with _current_connection(session_dir, loader) as connection:
            target = connection.execute(
                """
                SELECT ordinal, role FROM message_index
                WHERE session_id = ? AND message_id = ?
                """,
                (_session_id(session_dir), message_id),
            ).fetchone()
            if target is None:
                return None, []
            target_ordinal, target_role = int(target[0]), str(target[1])
            if target_role != "user":
                return target_role, []
            boundary = connection.execute(
                """
                SELECT MIN(ordinal) FROM message_index
                WHERE session_id = ? AND ordinal > ? AND role = 'user'
                """,
                (_session_id(session_dir), target_ordinal),
            ).fetchone()[0]
            if boundary is None:
                rows = connection.execute(
                    """
                    SELECT payload_json FROM message_index
                    WHERE session_id = ? AND ordinal >= ? ORDER BY ordinal
                    """,
                    (_session_id(session_dir), target_ordinal),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT payload_json FROM message_index
                    WHERE session_id = ? AND ordinal >= ? AND ordinal < ?
                    ORDER BY ordinal
                    """,
                    (_session_id(session_dir), target_ordinal, int(boundary)),
                ).fetchall()
        return target_role, [_decode(row[0]) for row in rows]
    except (OSError, sqlite3.Error, ValueError) as exc:
        LOGGER.warning("Message cache unavailable; resolving turn from canonical files: %s", exc)
        payloads = loader()
        target_ordinal = next(
            (
                ordinal
                for ordinal, payload in enumerate(payloads)
                if str(payload.get("message_id") or "") == message_id
            ),
            None,
        )
        if target_ordinal is None:
            return None, []
        role = str(payloads[target_ordinal].get("role") or "")
        if role != "user":
            return role, []
        end = next(
            (
                ordinal
                for ordinal in range(target_ordinal + 1, len(payloads))
                if payloads[ordinal].get("role") == "user"
            ),
            len(payloads),
        )
        return role, payloads[target_ordinal:end]


def update_after_append(
    session_dir: Path,
    *,
    payload: dict[str, Any],
    previous_fingerprint: tuple[int, int] | None,
    current_fingerprint: tuple[int, int] | None,
) -> None:
    if current_fingerprint is None:
        return
    try:
        path = cache_database_path(session_dir)
        _ensure_database(path)
        with _connection(path) as connection:
            row = connection.execute(
                "SELECT source_size, source_mtime_ns FROM message_sources WHERE session_id = ?",
                (_session_id(session_dir),),
            ).fetchone()
            cached = (int(row[0]), int(row[1])) if row is not None else None
            if cached != previous_fingerprint:
                connection.execute(
                    "DELETE FROM message_sources WHERE session_id = ?",
                    (_session_id(session_dir),),
                )
                return
            ordinal = connection.execute(
                "SELECT COALESCE(MAX(ordinal), -1) + 1 FROM message_index WHERE session_id = ?",
                (_session_id(session_dir),),
            ).fetchone()[0]
            connection.execute(
                """
                INSERT INTO message_index(session_id, ordinal, message_id, role, payload_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    _session_id(session_dir),
                    int(ordinal),
                    str(payload.get("message_id") or ""),
                    str(payload.get("role") or ""),
                    _encode(payload),
                ),
            )
            _write_source(connection, _session_id(session_dir), current_fingerprint)
    except (OSError, sqlite3.Error, ValueError) as exc:
        LOGGER.warning("Could not update disposable message cache: %s", exc)


def rebuild(session_dir: Path, payloads: list[dict[str, Any]]) -> None:
    fingerprint = source_fingerprint(_messages_path(session_dir))
    try:
        path = cache_database_path(session_dir)
        _ensure_database(path)
        with _connection(path) as connection:
            _replace_session_rows(connection, _session_id(session_dir), payloads)
            if fingerprint is None:
                connection.execute(
                    "DELETE FROM message_sources WHERE session_id = ?",
                    (_session_id(session_dir),),
                )
            else:
                _write_source(connection, _session_id(session_dir), fingerprint)
    except (OSError, sqlite3.Error, ValueError) as exc:
        LOGGER.warning("Could not rebuild disposable message cache: %s", exc)


def remove_session(session_dir: Path) -> None:
    try:
        path = cache_database_path(session_dir)
        if not path.is_file():
            return
        with _connection(path) as connection:
            connection.execute(
                "DELETE FROM message_index WHERE session_id = ?",
                (_session_id(session_dir),),
            )
            connection.execute(
                "DELETE FROM message_sources WHERE session_id = ?",
                (_session_id(session_dir),),
            )
    except (OSError, sqlite3.Error):
        return


def source_fingerprint(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return int(stat.st_size), int(stat.st_mtime_ns)


@contextmanager
def _current_connection(
    session_dir: Path,
    loader: MessageLoader,
) -> Iterator[sqlite3.Connection]:
    path = cache_database_path(session_dir)
    _ensure_database(path)
    fingerprint = source_fingerprint(_messages_path(session_dir))
    with _connection(path) as connection:
        row = connection.execute(
            "SELECT source_size, source_mtime_ns FROM message_sources WHERE session_id = ?",
            (_session_id(session_dir),),
        ).fetchone()
        cached = (int(row[0]), int(row[1])) if row is not None else None
        if cached != fingerprint:
            payloads = loader()
            _replace_session_rows(connection, _session_id(session_dir), payloads)
            if fingerprint is None:
                connection.execute(
                    "DELETE FROM message_sources WHERE session_id = ?",
                    (_session_id(session_dir),),
                )
            else:
                _write_source(connection, _session_id(session_dir), fingerprint)
        yield connection


def _replace_session_rows(
    connection: sqlite3.Connection,
    session_id: str,
    payloads: list[dict[str, Any]],
) -> None:
    connection.execute("DELETE FROM message_index WHERE session_id = ?", (session_id,))
    connection.executemany(
        """
        INSERT INTO message_index(session_id, ordinal, message_id, role, payload_json)
        VALUES (?, ?, ?, ?, ?)
        """,
        [
            (
                session_id,
                ordinal,
                str(payload.get("message_id") or ""),
                str(payload.get("role") or ""),
                _encode(payload),
            )
            for ordinal, payload in enumerate(payloads)
        ],
    )


def _write_source(
    connection: sqlite3.Connection,
    session_id: str,
    fingerprint: tuple[int, int],
) -> None:
    connection.execute(
        """
        INSERT INTO message_sources(session_id, source_size, source_mtime_ns)
        VALUES (?, ?, ?)
        ON CONFLICT(session_id) DO UPDATE SET
            source_size = excluded.source_size,
            source_mtime_ns = excluded.source_mtime_ns
        """,
        (session_id, fingerprint[0], fingerprint[1]),
    )


def _ensure_database(path: Path) -> None:
    resolved = path.resolve()
    with _initialization_lock:
        if resolved in _initialized_paths and resolved.is_file():
            return
        resolved.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(resolved, timeout=2.0)
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS cache_schema(version INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS message_sources(
                    session_id TEXT PRIMARY KEY,
                    source_size INTEGER NOT NULL,
                    source_mtime_ns INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS message_index(
                    session_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL,
                    message_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    PRIMARY KEY(session_id, ordinal),
                    UNIQUE(session_id, message_id)
                );
                CREATE INDEX IF NOT EXISTS idx_message_index_id
                    ON message_index(session_id, message_id);
                """
            )
            row = connection.execute("SELECT version FROM cache_schema LIMIT 1").fetchone()
            if row is None:
                connection.execute(
                    "INSERT INTO cache_schema(version) VALUES (?)",
                    (CACHE_SCHEMA_VERSION,),
                )
            elif int(row[0]) != CACHE_SCHEMA_VERSION:
                raise sqlite3.DatabaseError("unsupported conversation cache schema")
            connection.commit()
        finally:
            connection.close()
        _initialized_paths.add(resolved)


@contextmanager
def _connection(path: Path) -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(path, timeout=2.0)
    connection.execute("PRAGMA busy_timeout=2000")
    connection.execute("PRAGMA synchronous=NORMAL")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _session_id(session_dir: Path) -> str:
    return session_dir.name.split(".tmp-", 1)[0]


def _messages_path(session_dir: Path) -> Path:
    return session_dir / "messages.jsonl"


def _encode(value: Any) -> str:
    return dumps(value, ensure_ascii=False, separators=(",", ":"))


def _decode(value: str) -> dict[str, Any]:
    decoded = loads(value)
    if not isinstance(decoded, dict):
        raise ValueError("cached message is not an object")
    return decoded
