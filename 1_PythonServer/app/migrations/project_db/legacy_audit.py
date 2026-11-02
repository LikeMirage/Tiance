"""Frozen v1 audit codec for migrations only; normal readers remain v2-only."""

from copy import deepcopy
from gzip import decompress
from hashlib import sha256
from json import dumps, loads
from pathlib import Path
import re
import sqlite3
from zlib import error as zlib_error

from app.migrations.attempts import track_input

MANIFEST_KEY = "__tiance_audit_manifest__"


def restore_legacy_payload(connection: sqlite3.Connection, stored: dict) -> dict:
    if not isinstance(stored, dict):
        raise RuntimeError("Legacy audit must be a JSON object.")
    if MANIFEST_KEY not in stored:
        return stored
    if type(stored[MANIFEST_KEY]) is not int or stored[MANIFEST_KEY] != 1:
        raise RuntimeError(f"Unsupported legacy audit manifest version: {stored[MANIFEST_KEY]!r}.")
    if not isinstance(stored.get("payload"), dict) or not isinstance(stored.get("external_values"), list):
        raise RuntimeError("Legacy audit manifest has an invalid payload or references.")
    payload = deepcopy(stored["payload"])
    filename = next(row[2] for row in connection.execute("PRAGMA database_list") if row[1] == "main")
    for reference in stored["external_values"]:
        if not isinstance(reference, dict):
            raise RuntimeError("Legacy audit manifest has an invalid reference.")
        path, digest, size = reference.get("path"), reference.get("sha256"), reference.get("size_bytes")
        if (not isinstance(path, list) or not path or not isinstance(digest, str)
                or not re.fullmatch(r"[0-9a-f]{64}", digest) or type(size) is not int or size < 0
                or reference.get("encoding") != "utf-8"):
            raise RuntimeError("Legacy audit manifest has invalid external value metadata.")
        if not filename:
            raise RuntimeError("Legacy external audit blocks require a project database path.")
        workspace = Path(filename).resolve().parent
        blob = workspace / "conversations" / "audit_blobs" / digest[:2] / f"{digest}.blob"
        track_input(blob)
        if not blob.resolve().is_relative_to(workspace):
            raise RuntimeError(f"Legacy audit block {digest} resolves outside its workspace.")
        try:
            content = blob.read_bytes()
        except FileNotFoundError as error:
            raise RuntimeError(f"Legacy audit block is missing: {blob}") from error
        if len(content) != size or sha256(content).hexdigest() != digest:
            raise RuntimeError(f"Legacy audit block {digest} failed integrity validation.")
        try:
            value = content.decode("utf-8")
        except UnicodeDecodeError as error:
            raise RuntimeError(f"Legacy audit block {digest} is not UTF-8.") from error
        target = payload
        for index, segment in enumerate(path):
            valid = ((isinstance(target, dict) and isinstance(segment, str) and segment in target)
                     or (isinstance(target, list) and type(segment) is int and 0 <= segment < len(target)))
            if not valid:
                raise RuntimeError("Legacy audit reference path does not match its payload.")
            if index == len(path) - 1:
                if target[segment] is not None:
                    raise RuntimeError("Legacy audit reference must replace an empty placeholder.")
                target[segment] = value
            else:
                target = target[segment]
    return payload


def read_legacy_artifact(connection: sqlite3.Connection, row: tuple) -> dict:
    artifact_id, encoding, size, digest, compression, stored_size, blob = row
    if compression not in {"gzip", "gzip+audit-manifest-v1"} or len(blob) != stored_size:
        raise RuntimeError(f"HTTP audit {artifact_id} has an unsupported legacy payload.")
    try:
        content = decompress(blob)
        stored = loads(content.decode(encoding or "utf-8"))
    except (OSError, EOFError, UnicodeError, ValueError, zlib_error) as error:
        raise RuntimeError(f"HTTP audit {artifact_id} cannot be decoded.") from error
    if not isinstance(stored, dict):
        raise RuntimeError(f"HTTP audit {artifact_id} is not a JSON object.")
    if compression == "gzip+audit-manifest-v1":
        if stored.get(MANIFEST_KEY) != 1:
            raise RuntimeError(f"HTTP audit {artifact_id} has an invalid v1 manifest.")
        payload = restore_legacy_payload(connection, stored)
    else:
        payload = stored
    canonical = dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(encoding or "utf-8")
    if (len(canonical) != size or sha256(canonical).hexdigest() != digest
            or (compression == "gzip" and content != canonical)):
        raise RuntimeError(f"HTTP audit {artifact_id} failed original integrity checks.")
    return payload
