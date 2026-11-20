import shutil
import sqlite3
from contextlib import closing
from unittest.mock import patch

from app.editor_browser import workspace_download_path
from app.editor_browser_history import PAGE_SIZE, read_editor_downloads, read_editor_history, read_editor_records_page


def test_workspace_download_keeps_existing_and_in_progress_files(tmp_path):
    suggested = str(tmp_path / "report.pdf")
    first = workspace_download_path(str(tmp_path), suggested, set())
    assert first == tmp_path / "下载" / "report.pdf"
    first.write_bytes(b"previous download")
    second = workspace_download_path(str(tmp_path), suggested, set())
    third = workspace_download_path(str(tmp_path), suggested, {second})
    assert second.name == "report (1).pdf"
    assert third.name == "report (2).pdf"
    assert first.read_bytes() == b"previous download"


def test_history_reads_committed_visits_while_webview_holds_exclusive_lock(tmp_path):
    assert read_editor_history(str(tmp_path)) == []
    db_path = tmp_path / "EBWebView" / "Default" / "History"
    db_path.parent.mkdir(parents=True)
    with closing(sqlite3.connect(db_path)) as db:
        db.executescript("""
            PRAGMA locking_mode=EXCLUSIVE;
            CREATE TABLE urls (id INTEGER PRIMARY KEY, url TEXT, title TEXT, hidden INTEGER);
            CREATE TABLE visits (id INTEGER PRIMARY KEY, url INTEGER, visit_time INTEGER);
            INSERT INTO urls VALUES (1, 'https://example.test/', 'Example', 0),
                                    (2, 'file:///private', '', 0), (3, 'https://hidden.test/', '', 1);
            INSERT INTO visits VALUES (1, 1, 11644473600001000), (2, 1, 11644473600002000),
                                      (3, 2, 11644473600003000), (4, 3, 11644473600004000);
        """)
        db.execute("BEGIN EXCLUSIVE")
        db.execute("UPDATE urls SET title='uncommitted' WHERE id=1")
        assert read_editor_history(str(tmp_path)) == [
            {"url": "https://example.test/", "title": "Example", "visitedAt": stamp} for stamp in (2, 1)
        ]


def test_download_list_uses_final_paths_and_only_completed_operations(tmp_path):
    path = tmp_path / "EBWebView" / "Default" / "History"
    path.parent.mkdir(parents=True)
    with closing(sqlite3.connect(path)) as db:
        db.executescript("""
            CREATE TABLE downloads (id INTEGER PRIMARY KEY, target_path TEXT, state INTEGER, start_time INTEGER, end_time INTEGER);
            INSERT INTO downloads VALUES (1, 'a.pdf', 1, 11644473600001000, 0),
              (2, 'b.unknown', 1, 11644473600002000, 11644473600003000),
              (3, 'active.tmp', 0, 11644473600002000, 0), (4, 'cancelled.zip', 2, 11644473600002000, 0);
        """)
    assert [(r["path"], r["completedAt"]) for r in read_editor_downloads(str(tmp_path))] == [
        ("b.unknown", 3), ("a.pdf", 1)]


def test_pages_reach_old_records_and_search_full_history(tmp_path):
    profile = str(tmp_path)
    path = tmp_path / "EBWebView" / "Default" / "History"
    path.parent.mkdir(parents=True)
    count = 10_000
    stamp = 13407898123456789
    with closing(sqlite3.connect(path)) as db:
        db.executescript("""
            PRAGMA locking_mode=EXCLUSIVE;
            CREATE TABLE urls (id INTEGER PRIMARY KEY, url TEXT, title TEXT, hidden INTEGER);
            CREATE TABLE visits (id INTEGER PRIMARY KEY, url INTEGER, visit_time INTEGER);
            CREATE INDEX visits_time ON visits(visit_time);
            CREATE TABLE downloads (id INTEGER PRIMARY KEY, target_path TEXT, state INTEGER, start_time INTEGER, end_time INTEGER);
        """)
        db.executemany("INSERT INTO urls VALUES (?,?,?,0)",
                       ((i, f"https://site.test/{i}", "旧资料%_A" if i <= 50 else "其他") for i in range(1, count + 1)))
        db.executemany("INSERT INTO visits VALUES (?,?,?)",
                       ((i, i, stamp) for i in range(1, count + 1)))
        db.executemany("INSERT INTO downloads VALUES (?,?,1,?,0)",
                       ((i, f"{i}.pdf", stamp) for i in range(1, count + 1)))
        db.commit()
        # The same locked database serves search and both lists without being recopied per page.
        with patch("app.editor_browser_history.shutil.copyfile", wraps=shutil.copyfile) as copies:
            for kind in ("history", "downloads"):
                cursor, targets = None, []
                for _ in range(5):
                    page = read_editor_records_page(profile, kind, cursor=cursor)
                    assert len(page["items"]) == PAGE_SIZE
                    targets.extend(item["target"] for item in page["items"])
                    cursor = page["nextCursor"]
                expected = range(count, count - 5 * PAGE_SIZE, -1)
                assert targets == [f"https://site.test/{i}" if kind == "history" else f"{i}.pdf" for i in expected]
            first = read_editor_records_page(profile, "history", "%_a")
            second = read_editor_records_page(profile, "history", "%_a", first["nextCursor"])
            assert [row["target"] for row in first["items"] + second["items"]] == [
                f"https://site.test/{i}" for i in range(50, 0, -1)]
            assert second["nextCursor"] is None
            assert read_editor_records_page(profile, "history", "SITE.test/10000")["items"][0]["target"].endswith("/10000")
            assert read_editor_records_page(profile, "history", "不存在") == {"items": [], "nextCursor": None}
            downloads = read_editor_records_page(profile, "downloads", ".PDF")
            assert len(downloads["items"]) == PAGE_SIZE and downloads["nextCursor"]
            assert read_editor_records_page(profile, "downloads", "100.PDF")["items"][-1]["target"] == "100.pdf"
            assert not read_editor_records_page(profile, "downloads", "%_")["items"]
            sources = [call.args[0] for call in copies.call_args_list]
            assert path in sources and len(sources) == len(set(sources))

        db.execute("INSERT INTO visits VALUES (?,?,?)", (count + 1, 1, stamp + 1))
        db.commit()
        assert read_editor_records_page(profile, "history")["items"][0]["target"].endswith("/1")
        assert read_editor_records_page(profile, "history", "%_a", first["nextCursor"]) == second
