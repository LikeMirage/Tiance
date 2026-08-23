from __future__ import annotations

from contextlib import suppress
from datetime import datetime, timezone
import json
from pathlib import Path
from threading import RLock
from uuid import uuid4

from app.core.atomic_replace import atomic_replace_path
from app.core.errors import BadRequestError


class AnnouncementStateRepository:
    """公告已读事实与最后成功联网检查时间的本地持久化。"""

    def __init__(self, state_path: Path) -> None:
        self._state_path = state_path
        self._lock = RLock()

    def get_state(self) -> dict[str, object]:
        with self._lock:
            return self._read_unlocked()

    def set_last_successful_check(self) -> str:
        with self._lock:
            state = self._read_unlocked()
            checked_at = _utc_now()
            state["lastSuccessfulCheckAt"] = checked_at
            self._write_unlocked(state)
            return checked_at

    def mark_read(self, announcement_id: str, revision: int) -> str:
        with self._lock:
            state = self._read_unlocked()
            read_at = _utc_now()
            raw_entries = state.get("readAnnouncements")
            entries = dict(raw_entries) if isinstance(raw_entries, dict) else {}
            entries[announcement_id] = {"revision": revision, "readAt": read_at}
            state["readAnnouncements"] = entries
            self._write_unlocked(state)
            return read_at

    def _read_unlocked(self) -> dict[str, object]:
        try:
            raw = self._state_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {
                "schemaVersion": 1,
                "lastSuccessfulCheckAt": None,
                "readAnnouncements": {},
            }
        except OSError as exc:
            raise BadRequestError("无法读取本机公告状态。") from exc
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise BadRequestError("本机公告状态文件不是有效 JSON。") from exc
        if not isinstance(payload, dict) or payload.get("schemaVersion") != 1:
            raise BadRequestError("本机公告状态文件版本无效。")
        if not isinstance(payload.get("readAnnouncements"), dict):
            raise BadRequestError("本机公告已读状态格式无效。")
        last_checked = payload.get("lastSuccessfulCheckAt")
        if last_checked is not None and not isinstance(last_checked, str):
            raise BadRequestError("本机公告检查时间格式无效。")
        for announcement_id, entry in payload["readAnnouncements"].items():
            if (
                not isinstance(announcement_id, str)
                or not isinstance(entry, dict)
                or not isinstance(entry.get("revision"), int)
                or entry["revision"] < 1
                or not isinstance(entry.get("readAt"), str)
            ):
                raise BadRequestError("本机公告已读记录格式无效。")
        return payload

    def _write_unlocked(self, payload: dict[str, object]) -> None:
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._state_path.with_name(
            f".{self._state_path.name}.{uuid4().hex}.tmp"
        )
        try:
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            atomic_replace_path(temporary, self._state_path)
        finally:
            with suppress(OSError):
                temporary.unlink(missing_ok=True)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
