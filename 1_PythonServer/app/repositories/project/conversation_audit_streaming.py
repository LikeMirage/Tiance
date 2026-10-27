"""Bounded JSON encoding and block preparation, preserving audit-manifest-v2."""
from __future__ import annotations

from base64 import b64encode
from codecs import getincrementaldecoder
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from hashlib import sha256
from json import dumps
from tempfile import SpooledTemporaryFile
from typing import Any, BinaryIO
from zlib import compressobj

from app.domain.llm.response_body import ResponseBody, body_chunks

BLOCK_MIN_BYTES = 1024
TEXT_CHUNK_CHARS = 16 * 1024


@dataclass(frozen=True)
class AuditText:
    chunks: Callable[[], Iterator[str]]


def response_text(body: bytes | ResponseBody) -> tuple[str, AuditText]:
    def utf8() -> Iterator[str]:
        decoder = getincrementaldecoder("utf-8")()
        for chunk in body_chunks(body):
            yield decoder.decode(chunk)
        yield decoder.decode(b"", final=True)

    try:
        for _ in utf8():
            pass
    except UnicodeDecodeError:
        def base64_chunks() -> Iterator[str]:
            tail = b""
            for chunk in body_chunks(body):
                data = tail + chunk
                end = len(data) - len(data) % 3
                yield b64encode(data[:end]).decode("ascii")
                tail = data[end:]
            if tail:
                yield b64encode(tail).decode("ascii")
        return "base64", AuditText(base64_chunks)
    return "utf-8", AuditText(utf8)


def text_chunks(value: str | AuditText) -> Iterator[str]:
    source = value.chunks() if isinstance(value, AuditText) else (value,)
    for text in source:
        for start in range(0, len(text), TEXT_CHUNK_CHARS):
            yield text[start:start + TEXT_CHUNK_CHARS]


def iter_json_bytes(value: Any) -> Iterator[bytes]:
    """Match dumps(ensure_ascii=False, separators=(',', ':')) without big strings."""
    if isinstance(value, (str, AuditText)):
        yield b'"'
        for chunk in text_chunks(value):
            yield dumps(chunk, ensure_ascii=False)[1:-1].encode("utf-8")
        yield b'"'
    elif isinstance(value, dict):
        yield b"{"
        for index, (key, item) in enumerate(value.items()):
            if index:
                yield b","
            if not isinstance(key, str):
                if key is None or isinstance(key, (bool, int, float)):
                    key = dumps(key)
                else:
                    raise TypeError("Unsupported JSON object key")
            yield from iter_json_bytes(key)
            yield b":"
            yield from iter_json_bytes(item)
        yield b"}"
    elif isinstance(value, (list, tuple)):
        yield b"["
        for index, item in enumerate(value):
            if index:
                yield b","
            yield from iter_json_bytes(item)
        yield b"]"
    else:
        yield dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


@dataclass
class PreparedBlock:
    kind: str
    size_bytes: int
    compressed_size: int
    file: BinaryIO


@dataclass
class PreparedAuditSnapshot:
    tree: dict[str, Any] = field(default_factory=dict)
    size_bytes: int = 0
    digest: str = ""
    blocks: dict[str, PreparedBlock] = field(default_factory=dict)

    def __enter__(self) -> PreparedAuditSnapshot:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def close(self) -> None:
        for block in self.blocks.values():
            block.file.close()


def prepare_audit_snapshot(payload: dict[str, Any]) -> PreparedAuditSnapshot:
    prepared = PreparedAuditSnapshot()
    references: dict[str, str] = {}

    def pack(value: Any, path: list[str | int]) -> Any:
        if isinstance(value, str) and len(value) < BLOCK_MIN_BYTES and len(value.encode("utf-8")) < BLOCK_MIN_BYTES:
            return value
        kind = None
        if isinstance(value, (str, AuditText)):
            kind = "text"
            chunks = (chunk.encode("utf-8") for chunk in text_chunks(value))
        elif path and path[-1] == "tools" and isinstance(value, (list, dict)):
            kind = "json"
            chunks = iter_json_bytes(value)
        if kind is not None:
            # Only compressed bytes are buffered; large/incompressible blocks
            # spill too. Raw text and complete JSON are never accumulated here.
            output = SpooledTemporaryFile(max_size=1024 * 1024, mode="w+b")
            try:
                compressor = compressobj(wbits=31)
                digest = sha256(kind.encode() + b"\0")
                size = 0
                small = bytearray()
                for chunk in chunks:
                    size += len(chunk)
                    digest.update(chunk)
                    output.write(compressor.compress(chunk))
                    if size < BLOCK_MIN_BYTES:
                        small.extend(chunk)
                output.write(compressor.flush())
                if size >= BLOCK_MIN_BYTES:
                    key = digest.hexdigest()
                    if key not in prepared.blocks:
                        prepared.blocks[key] = PreparedBlock(kind, size, output.tell(), output)
                        output = None
                    references[dumps(path, ensure_ascii=False, separators=(",", ":"))] = key
                    return None
                if isinstance(value, AuditText):
                    return small.decode("utf-8")
            finally:
                if output is not None:
                    output.close()
        if isinstance(value, dict):
            return {key: pack(item, [*path, key]) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [pack(item, [*path, index]) for index, item in enumerate(value)]
        return value

    try:
        digest = sha256()
        for chunk in iter_json_bytes(payload):
            prepared.size_bytes += len(chunk)
            digest.update(chunk)
        prepared.digest = digest.hexdigest()
        prepared.tree = {"payload": pack(payload, []), "external_values": references}
        return prepared
    except BaseException:
        prepared.close()
        raise


def write_prepared_blocks(connection: Any, prepared: PreparedAuditSnapshot) -> None:
    for digest, block in prepared.blocks.items():
        existing = connection.execute(
            "SELECT kind, size_bytes FROM conversation_audit_blocks WHERE digest = ?", (digest,),
        ).fetchone()
        if existing is not None:
            if tuple(existing) != (block.kind, block.size_bytes):
                raise RuntimeError(f"Audit block {digest} has inconsistent metadata.")
            continue
        cursor = connection.execute(
            """INSERT INTO conversation_audit_blocks(digest, kind, size_bytes, payload_blob)
               VALUES (?, ?, ?, zeroblob(?))""",
            (digest, block.kind, block.size_bytes, block.compressed_size),
        )
        block.file.seek(0)
        with connection.blobopen("conversation_audit_blocks", "payload_blob", cursor.lastrowid) as blob:
            while chunk := block.file.read(64 * 1024):
                blob.write(chunk)
