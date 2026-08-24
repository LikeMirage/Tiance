from __future__ import annotations

from hashlib import sha256
from os import replace as replace_file
from pathlib import Path
from typing import Any
from uuid import uuid4


AUDIT_EXTERNAL_VALUE_MIN_BYTES = 64 * 1024
_MANIFEST_KEY = "__tiance_audit_manifest__"
_MANIFEST_VERSION = 1


def externalize_audit_payload(
    workspace_dir: Path,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Replace large strings with content-addressed references without losing data."""

    external_values: list[dict[str, Any]] = []

    def visit(value: Any, path: list[str | int]) -> Any:
        if isinstance(value, str):
            content = value.encode("utf-8")
            if len(content) < AUDIT_EXTERNAL_VALUE_MIN_BYTES:
                return value
            digest = sha256(content).hexdigest()
            _write_blob(workspace_dir, digest, content)
            external_values.append(
                {
                    "path": list(path),
                    "sha256": digest,
                    "size_bytes": len(content),
                    "encoding": "utf-8",
                }
            )
            return None
        if isinstance(value, dict):
            return {
                key: visit(item, [*path, key])
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [
                visit(item, [*path, index])
                for index, item in enumerate(value)
            ]
        if isinstance(value, tuple):
            return [
                visit(item, [*path, index])
                for index, item in enumerate(value)
            ]
        return value

    return {
        _MANIFEST_KEY: _MANIFEST_VERSION,
        "payload": visit(payload, []),
        "external_values": external_values,
    }


def restore_audit_payload(
    workspace_dir: Path,
    stored_payload: dict[str, Any],
) -> dict[str, Any]:
    if stored_payload.get(_MANIFEST_KEY) != _MANIFEST_VERSION:
        return stored_payload
    payload = stored_payload.get("payload")
    if not isinstance(payload, dict):
        raise RuntimeError("Audit manifest does not contain an object payload.")
    external_values = stored_payload.get("external_values")
    if not isinstance(external_values, list):
        raise RuntimeError("Audit manifest does not contain external value references.")

    for reference in external_values:
        if not isinstance(reference, dict):
            raise RuntimeError("Audit manifest contains an invalid external value reference.")
        path = reference.get("path")
        digest = str(reference.get("sha256") or "")
        size_bytes = reference.get("size_bytes")
        encoding = str(reference.get("encoding") or "")
        if (
            not isinstance(path, list)
            or len(digest) != 64
            or not isinstance(size_bytes, int)
            or size_bytes < 0
            or encoding != "utf-8"
        ):
            raise RuntimeError("Audit manifest contains incomplete external value metadata.")
        content = _read_blob(workspace_dir, digest, size_bytes)
        try:
            value = content.decode(encoding)
        except UnicodeDecodeError as error:
            raise RuntimeError(f"Audit blob {digest} is not valid UTF-8.") from error
        _assign_path(payload, path, value)
    return payload


def is_audit_manifest(value: object) -> bool:
    return isinstance(value, dict) and value.get(_MANIFEST_KEY) == _MANIFEST_VERSION


def audit_blob_path(workspace_dir: Path, digest: str) -> Path:
    return workspace_dir / "conversations" / "audit_blobs" / digest[:2] / f"{digest}.blob"


def _write_blob(workspace_dir: Path, digest: str, content: bytes) -> None:
    target = audit_blob_path(workspace_dir, digest)
    if target.is_file():
        if target.stat().st_size != len(content):
            raise RuntimeError(f"Audit blob {digest} has an unexpected size.")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.tmp-{uuid4().hex}")
    try:
        temporary.write_bytes(content)
        if sha256(content).hexdigest() != digest:
            raise RuntimeError("Audit blob digest changed before it was written.")
        try:
            replace_file(temporary, target)
        except OSError:
            if not target.is_file() or target.stat().st_size != len(content):
                raise
    finally:
        temporary.unlink(missing_ok=True)
    if target.stat().st_size != len(content):
        raise RuntimeError(f"Audit blob {digest} has an unexpected size.")


def _read_blob(workspace_dir: Path, digest: str, size_bytes: int) -> bytes:
    path = audit_blob_path(workspace_dir, digest)
    try:
        content = path.read_bytes()
    except OSError as error:
        raise RuntimeError(f"Audit blob {digest} is missing.") from error
    if len(content) != size_bytes or sha256(content).hexdigest() != digest:
        raise RuntimeError(f"Audit blob {digest} failed integrity validation.")
    return content


def _assign_path(root: dict[str, Any], path: list[object], value: str) -> None:
    if not path:
        raise RuntimeError("Audit manifest cannot replace its root object with a string.")
    current: Any = root
    for segment in path[:-1]:
        if isinstance(segment, str) and isinstance(current, dict):
            if segment not in current:
                raise RuntimeError("Audit manifest path does not exist.")
            current = current[segment]
        elif isinstance(segment, int) and isinstance(current, list):
            if segment < 0 or segment >= len(current):
                raise RuntimeError("Audit manifest list path is out of range.")
            current = current[segment]
        else:
            raise RuntimeError("Audit manifest path does not match its payload.")
    final = path[-1]
    if isinstance(final, str) and isinstance(current, dict) and final in current:
        current[final] = value
        return
    if isinstance(final, int) and isinstance(current, list) and 0 <= final < len(current):
        current[final] = value
        return
    raise RuntimeError("Audit manifest target path does not exist.")
