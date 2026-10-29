from dataclasses import dataclass


@dataclass(frozen=True)
class TextFileUpdate:
    path: str
    content: str
    expected_mtime_ms: int | None = None
