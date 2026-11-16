"""Bounded, immediate local JSONL writes; logging must never break the app."""
from datetime import UTC, datetime
import json
from pathlib import Path
from threading import Lock
from uuid import uuid4


class DiagnosticLog:
    def __init__(self, directory: Path, *, max_bytes=4 * 1024 * 1024, backups=4):
        self.path = directory / "runtime-diagnostics.jsonl"
        self.max_bytes = max_bytes
        self.backups = backups
        self.session = uuid4().hex
        self.lock = Lock()
        self.closed = False

    def write(self, event: str, **fields) -> bool:
        try:
            record = dict(time=datetime.now(UTC).isoformat(), session=self.session,
                          event=event, **fields)
            line = (json.dumps(record, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n").encode("utf-8")
            if len(line) > min(self.max_bytes, 64 * 1024):
                return False
            with self.lock:
                if self.closed:
                    return False
                self.path.parent.mkdir(parents=True, exist_ok=True)
                if self.path.exists() and self.path.stat().st_size + len(line) > self.max_bytes:
                    for index in range(self.backups, 0, -1):
                        source = self.path if index == 1 else self.path.with_name(f"{self.path.name}.{index - 1}")
                        if source.exists():
                            source.replace(self.path.with_name(f"{self.path.name}.{index}"))
                with self.path.open("ab") as stream:
                    stream.write(line)
            return True
        except (OSError, ValueError, TypeError):
            return False

    def close(self):
        with self.lock:
            self.closed = True
