"""Read the editor's WebView2 history without modifying the live Chromium database."""

import shutil
import sqlite3
from contextlib import closing
from functools import lru_cache
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock

from app.editor_browser import web_address


PAGE_SIZE = 25


class _HistoryDatabase:
    def __init__(self, profile: str):
        self.path = Path(profile) / "EBWebView" / "Default" / "History"
        self.lock = Lock()
        self.snapshot = None
        self.signature = None

    def read(self, query):
        # Bridge calls run on worker threads. Only one may replace/read the private copy at a time.
        with self.lock:
            if self.snapshot:
                if self.path.is_file() and self.signature == _snapshot_files(self.path):
                    with closing(sqlite3.connect(Path(self.snapshot.name) / "History")) as db:
                        return query(db)
                self.snapshot.cleanup()
                self.snapshot = self.signature = None
            if not self.path.is_file():
                return {"items": [], "nextCursor": None}
            try:
                with closing(sqlite3.connect(f"{self.path.as_uri()}?mode=ro", uri=True, timeout=0.1)) as db:
                    return query(db)
            except sqlite3.OperationalError as exc:
                if exc.sqlite_errorcode & 0xFF not in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
                    raise

            # WebView2 can hold an exclusive lock. Copy its journals too and let SQLite
            # recover the last committed state. Reuse this snapshot until the source changes.
            for _ in range(2):
                tmp = TemporaryDirectory(prefix="tiance-web-history-")
                try:
                    files = _snapshot_files(self.path)
                    for path in files:
                        shutil.copyfile(path, Path(tmp.name) / path.name)
                    if files != _snapshot_files(self.path):
                        continue
                    with closing(sqlite3.connect(Path(tmp.name) / "History")) as db:
                        result = query(db)
                    self.snapshot, self.signature = tmp, files
                    return result
                except FileNotFoundError:
                    continue
                finally:
                    if tmp is not self.snapshot:
                        tmp.cleanup()
            raise RuntimeError("网页记录正在更新，请稍后重试。")


# The shell has one editor profile, shared across tabs.
@lru_cache(maxsize=1)
def _database(profile: str) -> _HistoryDatabase:
    return _HistoryDatabase(profile)


def _snapshot_files(history: Path) -> dict:
    files = {}
    for suffix in ("", "-wal", "-journal"):
        path = history.with_name(history.name + suffix)
        try:
            stat = path.stat()
        except FileNotFoundError:
            if not suffix:
                raise
            continue
        files[path] = (stat.st_ino, stat.st_size, stat.st_mtime_ns)
    return files


def read_editor_records_page(profile: str, kind: str, query: str = "", cursor: str | None = None, *, limit: int = PAGE_SIZE) -> dict:
    params = []
    if kind == "history":
        source = """
            SELECT visits.id AS record_id, visits.visit_time AS stamp, urls.title AS title, urls.url AS target
            FROM visits JOIN urls ON urls.id = visits.url
            WHERE urls.hidden = 0 AND (urls.url LIKE 'https://%' OR urls.url LIKE 'http://%')
        """
        filters = []
        if term := query.strip():
            filters.append("(instr(lower(title), lower(?)) > 0 OR instr(lower(target), lower(?)) > 0)")
            params.extend([term, term])
        filters.append("valid_web_address(target)")
    elif kind == "downloads":
        source = """
            SELECT id AS record_id, COALESCE(NULLIF(end_time, 0), start_time) AS stamp, target_path AS target
            FROM downloads WHERE state = 1 AND target_path != ''
        """
        filters = []
        if term := query.strip():
            filters.append("instr(lower(target), lower(?)) > 0")
            params.append(term)
    else:
        raise ValueError("未知的网页记录类型。")

    if cursor is not None:
        # Chromium's microsecond timestamps exceed JavaScript's exact integer range.
        # Keep both sort keys as decimal text across the bridge.
        stamp, record_id = cursor.split(":")
        filters.append("(stamp, record_id) < (?, ?)")
        params.extend([int(stamp), int(record_id)])
    where = " WHERE " + " AND ".join(filters) if filters else ""
    sql = f"SELECT * FROM ({source}){where} ORDER BY stamp DESC, record_id DESC LIMIT ?"

    def read(db):
        if kind == "history":
            db.create_function("valid_web_address", 1, web_address, deterministic=True)
        db.row_factory = sqlite3.Row
        rows = db.execute(sql, (*params, limit + 1)).fetchall()
        items = []
        for row in rows[:limit]:
            target = row["target"]
            title = (row["title"] or "") if kind == "history" else Path(target).name
            items.append({"target": target, "title": title, "time": row["stamp"] // 1000 - 11644473600000})
        next_cursor = None
        if len(rows) > limit:
            last = rows[limit - 1]
            next_cursor = f"{last['stamp']}:{last['record_id']}"
        return {"items": items, "nextCursor": next_cursor}

    return _database(profile).read(read)


# Older frontends still request a flat list of the latest 100 records.
def read_editor_history(profile: str) -> list[dict]:
    rows = read_editor_records_page(profile, "history", limit=100)["items"]
    return [{"url": row["target"], "title": row["title"], "visitedAt": row["time"]} for row in rows]


def read_editor_downloads(profile: str) -> list[dict]:
    rows = read_editor_records_page(profile, "downloads", limit=100)["items"]
    return [{"path": row["target"], "name": row["title"], "completedAt": row["time"]} for row in rows]
