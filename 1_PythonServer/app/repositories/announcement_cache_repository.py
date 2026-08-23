from __future__ import annotations

from contextlib import suppress
import hashlib
import json
from pathlib import Path, PurePosixPath
from uuid import uuid4

from app.core.atomic_replace import atomic_replace_path
from app.core.errors import BadRequestError


class AnnouncementCacheRepository:
    """按远端源隔离的可重建公告缓存；缓存从不承担已读事实。"""

    def __init__(self, cache_root: Path) -> None:
        self._cache_root = cache_root.resolve()

    def read_json(self, source: str, relative_path: str) -> dict[str, object] | None:
        try:
            payload = json.loads(self._path(source, relative_path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def read_index(self, source: str) -> dict[str, object] | None:
        return self.read_json(source, "index.json")

    def read_bytes(self, source: str, relative_path: str) -> bytes | None:
        try:
            return self._path(source, relative_path).read_bytes()
        except OSError:
            return None

    def save_json(self, source: str, relative_path: str, payload: dict[str, object]) -> None:
        self.save_bytes(
            source,
            relative_path,
            (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
        )

    def save_index(self, source: str, payload: dict[str, object]) -> None:
        self.save_json(source, "index.json", payload)

    def save_bytes(self, source: str, relative_path: str, payload: bytes) -> Path:
        target = self._path(source, relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
        try:
            temporary.write_bytes(payload)
            atomic_replace_path(temporary, target)
        finally:
            with suppress(OSError):
                temporary.unlink(missing_ok=True)
        return target

    def path_for(self, source: str, relative_path: str) -> Path:
        return self._path(source, relative_path)

    def _path(self, source: str, relative_path: str) -> Path:
        normalized = PurePosixPath(relative_path.replace("\\", "/"))
        if (
            normalized.is_absolute()
            or not normalized.parts
            or any(part in {"", ".", ".."} for part in normalized.parts)
        ):
            raise BadRequestError("公告资源路径无效。")
        source_key = hashlib.sha256(source.encode("utf-8")).hexdigest()[:20]
        root = (self._cache_root / source_key).resolve()
        target = root.joinpath(*normalized.parts).resolve()
        if target != root and root not in target.parents:
            raise BadRequestError("公告资源路径越界。")
        return target
