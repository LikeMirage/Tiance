from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from app.api.routes.project import document_marks as api


def test_project_mark_operations(tmp_path, monkeypatch):
    db = tmp_path / ".Tiance" / "document-marks.sqlite3"
    monkeypatch.setattr(api, "_location", lambda project_id, path: (db, path))
    assert api.list_marks("project", "a.md") == []
    assert not db.exists()
    def add(i):
        mark = api.DocumentMark(id=uuid4(), surface="preview", start=2, length=3,
                                startLine=1, endLine=1, head="选这里", tail="选这里",
                                before="", after="", digest="123456789abcdef0")
        changes = api.MarkChanges(add=[mark])
        api.change_marks("project", "a.md", changes)
        api.change_marks("project", "a.md", changes)
        return mark.id
    with ThreadPoolExecutor(max_workers=4) as pool:
        ids = list(pool.map(add, range(8)))
    assert len(api.list_marks("project", "a.md")) == 8
    api.change_marks("project", "b.md", api.MarkChanges(remove=ids))
    api.change_marks("project", "a.md", api.MarkChanges(remove=ids[:2]))
    assert {row["id"] for row in api.list_marks("project", "a.md")} == set(map(str, ids[2:]))
