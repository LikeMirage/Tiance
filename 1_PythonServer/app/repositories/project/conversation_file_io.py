from __future__ import annotations

from json import dumps, loads
import os
from pathlib import Path
from re import fullmatch
from typing import Any
from uuid import uuid4

from app.core.atomic_replace import atomic_replace_path
from app.core.errors import ConflictError


def require_safe_storage_name(value: str, *, label: str) -> str:
    normalized = value.strip()
    if not fullmatch(r"[A-Za-z0-9_-]+", normalized):
        raise ValueError(f"{label} contains unsupported characters: {value!r}")
    return normalized


def read_json_object(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        value = loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ConflictError(f"数据文件损坏，已停止读取以避免覆盖：{path}") from exc
    if not isinstance(value, dict):
        raise ConflictError(f"数据文件格式无效，已停止读取以避免覆盖：{path}")
    return value


def write_json_object(path: Path, payload: dict[str, Any]) -> None:
    write_text_if_changed(
        path,
        dumps(payload, ensure_ascii=False, indent=2) + "\n",
    )


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    pending = _read_pending_intent(path)
    readable_size = pending["source_size"] if pending is not None else None
    current_size = path.stat().st_size if path.is_file() else 0
    if readable_size is not None and current_size < readable_size:
        raise ConflictError(f"记录文件长度小于待写位置，已停止读取：{path}")
    records: list[dict[str, Any]] = []
    try:
        if path.is_file():
            with path.open("rb") as source:
                raw = source.read() if readable_size is None else source.read(readable_size)
            for line_number, line in enumerate(raw.decode("utf-8").splitlines(), start=1):
                if not line.strip():
                    continue
                value = loads(line)
                if not isinstance(value, dict):
                    raise ValueError("JSONL record is not an object")
                records.append(value)
    except (OSError, ValueError) as exc:
        raise ConflictError(
            f"记录文件损坏（第 {line_number if 'line_number' in locals() else '?'} 行），"
            f"已停止读取以避免静默丢失：{path}"
        ) from exc
    if pending is not None:
        # The durable intent is the authoritative last record until the next
        # locked append repairs any missing or partial file tail. Readers never
        # mutate a file that may still be owned by an active writer.
        records.append(pending["payload"])
    return records


def replace_jsonl(path: Path, payloads: list[dict[str, Any]]) -> None:
    _recover_pending_append(path)
    content = "".join(
        f"{dumps(payload, ensure_ascii=False, separators=(',', ':'))}\n"
        for payload in payloads
    )
    write_text_if_changed(path, content)
    _pending_path(path).unlink(missing_ok=True)


def append_jsonl_recoverable(path: Path, payload: dict[str, Any]) -> None:
    """Append one record with a recoverable intent file.

    The caller owns the containing scope lock. If the process exits after the
    intent is persisted but before it is cleared, the next read/append compares
    the intent with the final record and either clears it or completes it.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    _recover_pending_append(path)
    pending = _pending_path(path)
    source_size = path.stat().st_size if path.is_file() else 0
    write_json_object(
        pending,
        {
            "version": 1,
            "source_size": source_size,
            "payload": payload,
        },
    )
    encoded = _encode_jsonl_record(payload)
    with path.open("ab") as output:
        output.write(encoded)
        output.flush()
        os.fsync(output.fileno())
    pending.unlink(missing_ok=True)


def write_text_if_changed(path: Path, content: str) -> None:
    try:
        if path.is_file() and path.read_text(encoding="utf-8") == content:
            return
    except OSError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        atomic_replace_path(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _recover_pending_append(path: Path) -> None:
    intent = _read_pending_intent(path)
    if intent is None:
        return
    pending = _pending_path(path)
    source_size = intent["source_size"]
    encoded = _encode_jsonl_record(intent["payload"])
    current_size = path.stat().st_size if path.is_file() else 0
    if current_size < source_size:
        raise ConflictError(f"记录文件长度小于待恢复位置，已停止覆盖：{path}")

    suffix = b""
    if path.is_file() and current_size > source_size:
        with path.open("rb") as source:
            source.seek(source_size)
            suffix = source.read()
    if suffix.startswith(encoded):
        pending.unlink(missing_ok=True)
        return
    if not encoded.startswith(suffix):
        raise ConflictError(f"记录文件待恢复尾部不一致，已停止覆盖：{path}")

    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "r+b" if path.is_file() else "w+b"
    with path.open(mode) as output:
        output.truncate(source_size)
        output.seek(source_size)
        output.write(encoded)
        output.flush()
        os.fsync(output.fileno())
    pending.unlink(missing_ok=True)


def _read_pending_intent(path: Path) -> dict[str, Any] | None:
    pending = read_json_object(_pending_path(path))
    if pending is None:
        return None
    source_size = pending.get("source_size")
    payload = pending.get("payload")
    if (
        pending.get("version") != 1
        or not isinstance(source_size, int)
        or isinstance(source_size, bool)
        or source_size < 0
        or not isinstance(payload, dict)
    ):
        raise ConflictError(f"记录文件待写意图格式无效，已停止覆盖：{path}")
    return {"source_size": source_size, "payload": payload}


def _encode_jsonl_record(payload: dict[str, Any]) -> bytes:
    return (
        dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _pending_path(path: Path) -> Path:
    return path.with_name(f".{path.name}.pending.json")
