from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any

from file_scanner import FileCandidate, ScanConfig, read_text_file, scan_files


SCHEMA_VERSION = 1
CHUNK_MAX_CHARACTERS = 12_000
CHUNK_MAX_LINES = 120
CHUNK_OVERLAP_LINES = 2


def connect(database_path: Path) -> sqlite3.Connection:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path, timeout=15)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA synchronous = NORMAL")
    ensure_schema(connection)
    return connection


def ensure_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY,
            path TEXT NOT NULL UNIQUE,
            extension TEXT NOT NULL,
            size INTEGER NOT NULL,
            modified_ns INTEGER NOT NULL,
            content_hash TEXT NOT NULL,
            encoding TEXT NOT NULL,
            indexed_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS chunks (
            id INTEGER PRIMARY KEY,
            file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
            chunk_index INTEGER NOT NULL,
            start_line INTEGER NOT NULL,
            end_line INTEGER NOT NULL,
            path TEXT NOT NULL,
            content TEXT NOT NULL,
            UNIQUE(file_id, chunk_index)
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
            content,
            path UNINDEXED,
            content='chunks',
            content_rowid='id',
            tokenize='trigram'
        );
        CREATE TRIGGER IF NOT EXISTS chunks_after_insert AFTER INSERT ON chunks BEGIN
            INSERT INTO chunks_fts(rowid, content, path) VALUES (new.id, new.content, new.path);
        END;
        CREATE TRIGGER IF NOT EXISTS chunks_before_delete BEFORE DELETE ON chunks BEGIN
            INSERT INTO chunks_fts(chunks_fts, rowid, content, path)
            VALUES ('delete', old.id, old.content, old.path);
        END;
        CREATE TRIGGER IF NOT EXISTS chunks_after_update AFTER UPDATE ON chunks BEGIN
            INSERT INTO chunks_fts(chunks_fts, rowid, content, path)
            VALUES ('delete', old.id, old.content, old.path);
            INSERT INTO chunks_fts(rowid, content, path) VALUES (new.id, new.content, new.path);
        END;
        CREATE INDEX IF NOT EXISTS files_extension_index ON files(extension);
        CREATE INDEX IF NOT EXISTS chunks_file_index ON chunks(file_id, chunk_index);
        """
    )
    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


def save_config(connection: sqlite3.Connection, config: ScanConfig) -> None:
    value = json.dumps(asdict(config), ensure_ascii=False, sort_keys=True)
    connection.execute(
        "INSERT INTO metadata(key, value) VALUES('scan_config', ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (value,),
    )


def load_config(connection: sqlite3.Connection) -> ScanConfig | None:
    row = connection.execute("SELECT value FROM metadata WHERE key='scan_config'").fetchone()
    if row is None:
        return None
    raw = json.loads(row["value"])
    return ScanConfig(
        source_path=str(raw.get("source_path") or "."),
        max_file_bytes=int(raw.get("max_file_bytes") or 5 * 1024 * 1024),
        include_globs=tuple(raw.get("include_globs") or ()),
        exclude_globs=tuple(raw.get("exclude_globs") or ()),
    )


def synchronize(
    database_path: Path,
    workspace_root: Path,
    source_root: Path,
    config: ScanConfig,
    *,
    rebuild: bool,
) -> dict[str, Any]:
    connection = connect(database_path)
    indexed = updated = unchanged = deleted = 0
    warnings: list[dict[str, str]] = []
    try:
        candidates, scan_issues, skipped = scan_files(workspace_root, source_root, database_path, config)
        warnings.extend({"path": issue.path, "reason": issue.reason} for issue in scan_issues)
        existing = {row["path"]: row for row in connection.execute("SELECT * FROM files")}
        seen: set[str] = set()
        with connection:
            if rebuild:
                connection.execute("DELETE FROM files")
                existing = {}
            save_config(connection, config)
            for candidate in candidates:
                seen.add(candidate.relative_path)
                previous = existing.get(candidate.relative_path)
                if (
                    previous is not None
                    and int(previous["size"]) == candidate.size
                    and int(previous["modified_ns"]) == candidate.modified_ns
                ):
                    unchanged += 1
                    continue
                try:
                    decoded = read_text_file(candidate)
                except (OSError, ValueError) as exc:
                    warnings.append({"path": candidate.relative_path, "reason": str(exc)})
                    continue
                digest = hashlib.sha256(decoded.content.encode("utf-8")).hexdigest()
                timestamp = _utc_now()
                if previous is not None and previous["content_hash"] == digest:
                    connection.execute(
                        "UPDATE files SET size=?, modified_ns=?, encoding=?, indexed_at=? WHERE id=?",
                        (candidate.size, candidate.modified_ns, decoded.encoding, timestamp, previous["id"]),
                    )
                    unchanged += 1
                    continue

                if previous is None:
                    cursor = connection.execute(
                        "INSERT INTO files(path, extension, size, modified_ns, content_hash, encoding, indexed_at) "
                        "VALUES(?, ?, ?, ?, ?, ?, ?)",
                        (
                            candidate.relative_path,
                            candidate.absolute_path.suffix.casefold(),
                            candidate.size,
                            candidate.modified_ns,
                            digest,
                            decoded.encoding,
                            timestamp,
                        ),
                    )
                    file_id = int(cursor.lastrowid)
                    indexed += 1
                else:
                    file_id = int(previous["id"])
                    connection.execute("DELETE FROM chunks WHERE file_id=?", (file_id,))
                    connection.execute(
                        "UPDATE files SET extension=?, size=?, modified_ns=?, content_hash=?, encoding=?, indexed_at=? "
                        "WHERE id=?",
                        (
                            candidate.absolute_path.suffix.casefold(),
                            candidate.size,
                            candidate.modified_ns,
                            digest,
                            decoded.encoding,
                            timestamp,
                            file_id,
                        ),
                    )
                    updated += 1

                for chunk_index, start_line, end_line, content in chunk_text(decoded.content):
                    connection.execute(
                        "INSERT INTO chunks(file_id, chunk_index, start_line, end_line, path, content) "
                        "VALUES(?, ?, ?, ?, ?, ?)",
                        (file_id, chunk_index, start_line, end_line, candidate.relative_path, content),
                    )

            if not scan_issues:
                missing = [path for path in existing if path not in seen]
                if missing:
                    placeholders = ",".join("?" for _ in missing)
                    connection.execute(f"DELETE FROM files WHERE path IN ({placeholders})", missing)
                    deleted = len(missing)

            connection.execute(
                "INSERT INTO metadata(key, value) VALUES('last_synchronized_at', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (_utc_now(),),
            )
        totals = database_totals(connection)
        return {
            "indexed": indexed,
            "updated": updated,
            "unchanged": unchanged,
            "deleted": deleted,
            "skipped_count": len(skipped),
            "skipped": skipped[:100],
            "warnings": warnings[:100],
            **totals,
        }
    finally:
        connection.close()


def check_changes(
    database_path: Path,
    workspace_root: Path,
    source_root: Path,
    config: ScanConfig,
    *,
    verification: str,
) -> dict[str, Any]:
    connection = connect(database_path)
    try:
        existing = {row["path"]: row for row in connection.execute("SELECT * FROM files")}
        candidates, scan_issues, _ = scan_files(workspace_root, source_root, database_path, config)
        changes: list[dict[str, Any]] = []
        seen: set[str] = set()
        for candidate in candidates:
            seen.add(candidate.relative_path)
            previous = existing.get(candidate.relative_path)
            if previous is None:
                changes.append({"state": "new", "path": candidate.relative_path})
                continue
            metadata_changed = (
                int(previous["size"]) != candidate.size
                or int(previous["modified_ns"]) != candidate.modified_ns
            )
            if verification == "hash":
                try:
                    decoded = read_text_file(candidate)
                    digest = hashlib.sha256(decoded.content.encode("utf-8")).hexdigest()
                except (OSError, ValueError) as exc:
                    changes.append({"state": "unreadable", "path": candidate.relative_path, "reason": str(exc)})
                    continue
                if digest != previous["content_hash"]:
                    changes.append({"state": "modified", "path": candidate.relative_path})
            elif metadata_changed:
                changes.append({"state": "modified", "path": candidate.relative_path})

        if not scan_issues:
            changes.extend({"state": "deleted", "path": path} for path in existing if path not in seen)
        changes.extend({"state": "unreadable", "path": issue.path, "reason": issue.reason} for issue in scan_issues)
        changes.sort(key=lambda item: (str(item["state"]), str(item["path"]).casefold()))
        counts = {state: 0 for state in ("new", "modified", "deleted", "unreadable")}
        for change in changes:
            counts[str(change["state"])] = counts.get(str(change["state"]), 0) + 1
        return {"stale": bool(changes), "counts": counts, "changes": changes}
    finally:
        connection.close()


def database_status(database_path: Path) -> dict[str, Any]:
    if not database_path.is_file():
        return {"exists": False, "file_count": 0, "chunk_count": 0, "database_size": 0}
    connection = connect(database_path)
    try:
        config = load_config(connection)
        metadata = {row["key"]: row["value"] for row in connection.execute("SELECT key, value FROM metadata")}
        return {
            "exists": True,
            "database_size": database_path.stat().st_size,
            "last_synchronized_at": metadata.get("last_synchronized_at"),
            "scan_config": asdict(config) if config is not None else None,
            **database_totals(connection),
        }
    finally:
        connection.close()


def database_totals(connection: sqlite3.Connection) -> dict[str, int]:
    file_count = int(connection.execute("SELECT COUNT(*) FROM files").fetchone()[0])
    chunk_count = int(connection.execute("SELECT COUNT(*) FROM chunks").fetchone()[0])
    return {"file_count": file_count, "chunk_count": chunk_count}


def chunk_text(text: str) -> list[tuple[int, int, int, str]]:
    source_lines = text.splitlines(keepends=True) or [""]
    units: list[tuple[int, str]] = []
    for line_number, line in enumerate(source_lines, start=1):
        if len(line) <= CHUNK_MAX_CHARACTERS:
            units.append((line_number, line))
            continue
        for start in range(0, len(line), CHUNK_MAX_CHARACTERS):
            units.append((line_number, line[start : start + CHUNK_MAX_CHARACTERS]))

    chunks: list[tuple[int, int, int, str]] = []
    start = 0
    index = 0
    while start < len(units):
        end = start
        size = 0
        while end < len(units) and end - start < CHUNK_MAX_LINES:
            next_size = len(units[end][1])
            if end > start and size + next_size > CHUNK_MAX_CHARACTERS:
                break
            size += next_size
            end += 1
        if end == start:
            end += 1
        content = "".join(unit[1] for unit in units[start:end])
        chunks.append((index, units[start][0], units[end - 1][0], content))
        index += 1
        if end >= len(units):
            break
        start = max(start + 1, end - CHUNK_OVERLAP_LINES)
    return chunks


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
