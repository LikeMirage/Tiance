"""Replayable HTTP body contract; a retained owner must release its reference."""
from collections.abc import Iterator
from typing import Protocol


class ResponseBody(Protocol):
    @property
    def size_bytes(self) -> int: ...
    def iter_bytes(self, chunk_size: int = 64 * 1024) -> Iterator[bytes]: ...
    def retain(self) -> None: ...
    def release(self) -> None: ...


def body_size(body: bytes | ResponseBody) -> int:
    return len(body) if isinstance(body, bytes) else body.size_bytes


def body_chunks(body: bytes | ResponseBody, chunk_size: int = 64 * 1024) -> Iterator[bytes]:
    if isinstance(body, bytes):
        for start in range(0, len(body), chunk_size):
            yield body[start:start + chunk_size]
    else:
        yield from body.iter_bytes(chunk_size)
