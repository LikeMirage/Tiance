"""Recover an interrupted JSONL append without scanning the full history."""

from collections.abc import Callable
import json
import logging
import os
from pathlib import Path
from uuid import uuid4

logger = logging.getLogger(__name__)


def repair_jsonl_tail(path: Path, validate: Callable[[object], object]) -> None:
    """Caller must serialize this operation with readers and writers of the file."""
    if not path.is_file():
        return
    with path.open("rb") as stream:
        position = stream.seek(0, os.SEEK_END)
        if position == 0:
            return
        stream.seek(-1, os.SEEK_END)
        if stream.read(1) == b"\n":
            return
        parts = []
        while position:
            start = max(0, position - 8192)
            stream.seek(start)
            chunk = stream.read(position - start)
            newline = chunk.rfind(b"\n")
            if newline >= 0:
                parts.append(chunk[newline + 1:])
                position = start + newline + 1
                break
            parts.append(chunk)
            position = start
        tail = b"".join(reversed(parts))
    if tail.strip():
        try:
            payload = json.loads(tail.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            backup = path.with_name(f"{path.name}.{uuid4().hex}.corrupt-tail")
            with backup.open("xb") as stream:
                stream.write(tail)
                stream.flush()
                os.fsync(stream.fileno())
            with path.open("r+b") as stream:
                stream.truncate(position)
                stream.flush()
                os.fsync(stream.fileno())
            logger.warning("Recovered incomplete JSONL tail; original bytes saved to %s", backup)
            return
        # A complete JSON value with an invalid schema is not a torn append.
        validate(payload)
    with path.open("ab") as stream:
        stream.write(b"\n")
        stream.flush()
        os.fsync(stream.fileno())
