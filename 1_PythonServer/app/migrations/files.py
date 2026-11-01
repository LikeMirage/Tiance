"""Durable, content-addressed backups for one-time file conversions."""

from hashlib import sha256
import json
import os
from pathlib import Path
from uuid import uuid4

from app.core.atomic_replace import atomic_replace_path


def backup_file(path: Path) -> Path | None:
    if not path.is_file():
        return None
    content = path.read_bytes()
    backup = path.with_name(f"{path.name}.before-migration.{sha256(content).hexdigest()}.bak")
    if backup.exists():
        if backup.read_bytes() != content:
            raise RuntimeError(f"Migration backup is inconsistent: {backup}")
        return backup
    temporary = backup.with_name(f".{backup.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        atomic_replace_path(temporary, backup)
    finally:
        temporary.unlink(missing_ok=True)
    return backup


def write_json(path: Path, payload: dict) -> None:
    backup_file(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as output:
            output.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
            output.flush()
            os.fsync(output.fileno())
        atomic_replace_path(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
