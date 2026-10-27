"""One owned buffer from HTTP reception through audit persistence."""
from collections.abc import Iterator
from tempfile import SpooledTemporaryFile
from threading import Lock

RESPONSE_MEMORY_LIMIT = 8 * 1024 * 1024


class ResponseCapture:
    def __init__(self, memory_limit: int = RESPONSE_MEMORY_LIMIT) -> None:
        self._file = SpooledTemporaryFile(max_size=memory_limit, mode="w+b")
        self._size = 0
        self._owners = 1
        self._sealed = False
        self._lock = Lock()

    @property
    def size_bytes(self) -> int:
        return self._size

    @property
    def closed(self) -> bool:
        return self._file.closed

    def write(self, chunk: bytes) -> None:
        if self._sealed:
            raise RuntimeError("Cannot write a sealed response body.")
        self._file.write(chunk)
        self._size += len(chunk)

    def seal(self) -> None:
        self._sealed = True

    def retain(self) -> None:
        with self._lock:
            if self._owners == 0:
                raise RuntimeError("Response body is already released.")
            self._owners += 1

    def release(self) -> None:
        with self._lock:
            if self._owners <= 0:
                raise RuntimeError("Response body released twice.")
            self._owners -= 1
            if self._owners == 0:
                self._file.close()

    def iter_bytes(self, chunk_size: int = 64 * 1024) -> Iterator[bytes]:
        if not self._sealed or chunk_size <= 0:
            raise ValueError("Reading requires a sealed body and positive chunk size.")
        # The persistence owner reads sequentially; this lock also makes repeated
        # readers safe without duplicating the underlying file.
        with self._lock:
            self._file.seek(0)
            while chunk := self._file.read(chunk_size):
                yield chunk
