from __future__ import annotations

from contextlib import suppress
import hashlib
import json
from pathlib import Path
from uuid import uuid4

from app.core.atomic_replace import atomic_replace_path


class OnlineMarketCacheRepository:
    """在线市场共用的按源隔离索引、预览和操作缓存。"""

    def __init__(self, cache_root: Path, *, sources_directory: str | None = None) -> None:
        self._cache_root = cache_root.resolve()
        self._sources_root = (
            self._cache_root / sources_directory
            if sources_directory
            else self._cache_root
        )

    @property
    def cache_root(self) -> Path:
        return self._cache_root

    @property
    def downloads_root(self) -> Path:
        return self._cache_root / "downloads"

    @property
    def operations_root(self) -> Path:
        return self._cache_root / "operations"

    def read_index(self, source: str) -> dict[str, object] | None:
        try:
            payload = json.loads(
                (self._source_root(source) / "index.json").read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def save_index(self, source: str, payload: dict[str, object]) -> None:
        root = self._source_root(source)
        root.mkdir(parents=True, exist_ok=True)
        path = root / "index.json"
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            atomic_replace_path(temporary, path)
        finally:
            with suppress(OSError):
                temporary.unlink(missing_ok=True)

    def preview_path(self, source: str, cache_name: str) -> Path:
        return self._source_root(source) / "previews" / cache_name

    def _source_root(self, source: str) -> Path:
        key = hashlib.sha256(source.encode("utf-8")).hexdigest()[:20]
        return self._sources_root / key
