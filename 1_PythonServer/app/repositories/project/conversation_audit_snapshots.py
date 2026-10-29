"""Transactional, versioned audit snapshots; callers own the SQLite transaction."""
from __future__ import annotations

from copy import deepcopy
from gzip import compress, decompress
from hashlib import sha256
from json import loads
import sqlite3
from typing import Any
from zlib import error as zlib_error

from app.repositories.project.conversation_audit_delta import apply_delta, json_bytes, make_delta


from app.repositories.project.conversation_audit_streaming import (
    BLOCK_MIN_BYTES, PreparedAuditSnapshot, prepare_audit_snapshot, write_prepared_blocks,
)


MAX_DELTA_DEPTH = 32
MANIFEST_KEY = "__tiance_audit_manifest__"


def create_audit_snapshot_schema(connection: sqlite3.Connection) -> None:
    from app.repositories.project.conversation_schema import SCHEMA_STATEMENTS
    for statement in SCHEMA_STATEMENTS:
        if statement.startswith("CREATE TABLE conversation_audit_") or statement.startswith("CREATE INDEX idx_audit_"):
            connection.execute(statement)


def store_audit_snapshot(
    connection: sqlite3.Connection, session_id: str, stream: str, payload: dict[str, Any],
) -> dict[str, Any]:
    with prepare_audit_snapshot(payload) as prepared:
        return store_prepared_audit_snapshot(connection, session_id, stream, prepared)


def store_prepared_audit_snapshot(
    connection: sqlite3.Connection, session_id: str, stream: str, prepared: PreparedAuditSnapshot,
) -> dict[str, Any]:
    if not connection.in_transaction:
        raise RuntimeError("Audit snapshots must be stored in the owning record's transaction.")
    write_prepared_blocks(connection, prepared)
    tree = prepared.tree
    encoded_tree = json_bytes(tree)
    compressed = compress(encoded_tree, mtime=0)
    base_id, depth = None, 0
    linked_blocks = set(tree["external_values"].values())
    previous = connection.execute(
        """SELECT snapshot_id, depth FROM conversation_audit_snapshots
           WHERE session_id = ? AND stream = ? ORDER BY snapshot_id DESC LIMIT 1""",
        (session_id, stream),
    ).fetchone()
    if previous is not None and previous[1] < MAX_DELTA_DEPTH:
        before, _ = _read_tree(connection, int(previous[0]), session_id, stream)
        operations = make_delta(before, tree)
        if json_bytes(apply_delta(before, operations)) != encoded_tree:
            raise RuntimeError("Audit delta failed round-trip validation before writing.")
        delta_blob = compress(json_bytes(operations), mtime=0)
        if len(delta_blob) < len(compressed):
            base_id, depth, compressed = int(previous[0]), int(previous[1]) + 1, delta_blob
            # Inherited blocks remain owned by the base chain; do not repeat every link.
            linked_blocks -= set(before["external_values"].values())
    cursor = connection.execute(
        """INSERT INTO conversation_audit_snapshots(
            session_id, stream, base_snapshot_id, depth, payload_sha256,
            payload_size_bytes, tree_sha256, payload_blob
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (session_id, stream, base_id, depth, prepared.digest, prepared.size_bytes,
         sha256(encoded_tree).hexdigest(), compressed),
    )
    snapshot_id = int(cursor.lastrowid)
    connection.executemany(
        "INSERT INTO conversation_audit_snapshot_blocks(snapshot_id, digest) VALUES (?, ?)",
        [(snapshot_id, digest) for digest in sorted(linked_blocks)],
    )
    return {MANIFEST_KEY: 2, "snapshot_id": snapshot_id}


def restore_audit_snapshot(
    connection: sqlite3.Connection, session_id: str, stream: str, manifest: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(manifest, dict) or manifest.get(MANIFEST_KEY) != 2:
        raise RuntimeError("Invalid incremental audit manifest.")
    snapshot_id = manifest.get("snapshot_id")
    if type(snapshot_id) is not int or snapshot_id <= 0:
        raise RuntimeError("Invalid incremental audit manifest.")
    tree, metadata = _read_tree(connection, snapshot_id, session_id, stream)
    payload = tree["payload"]
    cache: dict[str, Any] = {}
    for encoded_path, digest in tree["external_values"].items():
        if digest not in cache:
            cache[digest] = _read_block(connection, digest)
        path = loads(encoded_path)
        target = payload
        for segment in path[:-1]:
            target = target[segment]
        if not path or target[path[-1]] is not None:
            raise RuntimeError("Invalid incremental audit block reference.")
        target[path[-1]] = deepcopy(cache[digest])
    content = json_bytes(payload)
    if len(content) != metadata[1] or sha256(content).hexdigest() != metadata[0]:
        raise RuntimeError(f"Audit snapshot {snapshot_id} failed payload integrity validation.")
    return payload


def collect_unreferenced_audit_blocks(connection: sqlite3.Connection) -> None:
    connection.execute(
        """DELETE FROM conversation_audit_blocks AS block WHERE NOT EXISTS (
            SELECT 1 FROM conversation_audit_snapshot_blocks AS link WHERE link.digest = block.digest
        )"""
    )


def _read_tree(
    connection: sqlite3.Connection, snapshot_id: int, session_id: str, stream: str,
) -> tuple[dict[str, Any], tuple[str, int]]:
    chain: list[tuple[Any, ...]] = []
    current = snapshot_id
    while True:
        row = connection.execute(
            """SELECT base_snapshot_id, depth, payload_sha256, payload_size_bytes,
                      tree_sha256, payload_blob FROM conversation_audit_snapshots
               WHERE snapshot_id = ? AND session_id = ? AND stream = ?""",
            (current, session_id, stream),
        ).fetchone()
        if row is None:
            raise RuntimeError(f"Audit snapshot {current} is missing or belongs to another stream.")
        if not 0 <= row[1] <= MAX_DELTA_DEPTH or len(chain) > MAX_DELTA_DEPTH:
            raise RuntimeError("Audit snapshot chain exceeds its depth limit.")
        if chain and chain[-1][1] != row[1] + 1:
            raise RuntimeError("Audit snapshot chain has inconsistent depths.")
        chain.append(row)
        if row[0] is None:
            if row[1] != 0:
                raise RuntimeError("Audit checkpoint has a nonzero depth.")
            break
        if not 0 < row[0] < current:
            raise RuntimeError("Audit snapshot base must precede its child.")
        current = row[0]
    tree = None
    for row in reversed(chain):
        try:
            data = loads(decompress(row[5]))
            tree = data if row[0] is None else apply_delta(tree, data)
        except (ValueError, KeyError, TypeError, IndexError, OSError, EOFError, zlib_error) as error:
            raise RuntimeError(f"Audit snapshot {snapshot_id} cannot be reconstructed.") from error
        if sha256(json_bytes(tree)).hexdigest() != row[4]:
            raise RuntimeError(f"Audit snapshot {snapshot_id} failed tree integrity validation.")
    if not isinstance(tree, dict) or not isinstance(tree.get("payload"), dict) or not isinstance(tree.get("external_values"), dict):
        raise RuntimeError("Audit snapshot has an invalid packed payload.")
    return tree, (str(chain[0][2]), int(chain[0][3]))


def _read_block(connection: sqlite3.Connection, digest: str) -> Any:
    row = connection.execute(
        "SELECT kind, size_bytes, payload_blob FROM conversation_audit_blocks WHERE digest = ?", (digest,),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"Audit block {digest} is missing.")
    try:
        content = decompress(row[2])
        if len(content) != row[1] or sha256(row[0].encode() + b"\0" + content).hexdigest() != digest:
            raise RuntimeError(f"Audit block {digest} failed integrity validation.")
        return loads(content) if row[0] == "json" else content.decode("utf-8")
    except (ValueError, OSError, EOFError, zlib_error) as error:
        raise RuntimeError(f"Audit block {digest} cannot be decoded.") from error
