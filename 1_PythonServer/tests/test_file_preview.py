import asyncio
import json
from pathlib import Path
import sqlite3
import subprocess
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from app.core.errors import AppError, BadRequestError
from app.services.file_preview import policy, runtime
from app.services.file_preview.inspection import Package, inspect_file
from app.services.file_preview.spreadsheet import spreadsheet_page
from app.services.project.project_database import ProjectDatabaseService, _read_rows


def workbook(tmp_path: Path, cells: str, *, merges: str = "", extras=None) -> Path:
    path = tmp_path / "book.xlsx"
    parts = {
        "xl/workbook.xml": '<workbook xmlns:r="urn:r"><sheets><sheet name="销售明细" r:id="r1"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": '<Relationships><Relationship Id="r1" Target="worksheets/sheet1.xml"/></Relationships>',
        "xl/worksheets/sheet1.xml": f'<worksheet><sheetData>{cells}</sheetData><mergeCells>{merges}</mergeCells></worksheet>',
        **(extras or {}),
    }
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        for name, content in parts.items():
            archive.writestr(name, content)
    return path


def test_inspection_uses_cell_complexity_and_sparse_extent_not_compressed_size(tmp_path):
    path = workbook(tmp_path, '<row><c r="A1"><v>3</v></c></row>',
                    merges="".join(f'<mergeCell ref="A{i}:B{i}"/>' for i in range(1, 150)))
    result = inspect_file(path)
    assert path.stat().st_size < 2048
    assert result["mode"] == "paged"
    assert result["merges"] == 149
    assert result["sheets"] == [{"name": "销售明细", "rows": 149, "columns": 2}]
    path = workbook(tmp_path, '<row><c r="XFD1048576"><v>3</v></c></row>')
    assert inspect_file(path)["mode"] == "paged"


def test_small_workbook_keeps_formatted_renderer(tmp_path):
    path = workbook(tmp_path, '<row><c r="B3"><v>42</v></c></row>')
    result = inspect_file(path)
    assert result["mode"] == "inline"
    assert result["sheets"][0]["rows"] == 3


def test_project_and_tool_routes_keep_explicit_file_identity(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.routes.project import files as project_routes
    from app.api.routes.tools import tool_folder_files as tool_routes
    from app.core.errors import register_exception_handlers
    path = workbook(tmp_path, '<row><c r="A1"><v>42</v></c></row>')
    calls = []
    class Files:
        def get_file_path(self, *ids, target_path):
            calls.append((ids, target_path))
            return path
    async def preview(_request, resolved, operation="inspect", **kwargs):
        assert resolved == path
        return {"operation": operation, **kwargs}
    monkeypatch.setattr(project_routes, "get_project_file_service", Files)
    monkeypatch.setattr(tool_routes, "get_tool_folder_file_service", Files)
    monkeypatch.setattr(project_routes, "preview_file", preview)
    monkeypatch.setattr(tool_routes, "preview_file", preview)
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(project_routes.router)
    app.include_router(tool_routes.router)
    with TestClient(app) as client:
        response = client.get("/projects/p/files/preview", params={"path": "folder/book.xlsx"})
        assert response.status_code == 200
        response = client.get("/tools/categories/c/projects/t/files/preview/spreadsheet", params={
            "path": "folder/book.xlsx", "version": policy.version(path), "sheet": 0, "row": 50, "column": 20,
        })
        assert response.status_code == 200 and response.json()["row"] == 50
        assert calls == [(("p",), "folder/book.xlsx"), (("c", "t"), "folder/book.xlsx")]
        for prefix in ("/projects/p", "/tools/categories/c/projects/t"):
            response = client.get(prefix + "/files/asset", params={"path": "folder/book.xlsx", "preview_version": "obsolete"})
            assert response.status_code == 409
            assert client.get(prefix + "/files/asset", params={"path": "folder/book.xlsx", "preview_version": policy.version(path)}).status_code == 200


def test_page_preserves_coordinates_shared_strings_formulas_and_empty_cells(tmp_path):
    path = workbook(tmp_path, '''<row r="51">
      <c r="U51" t="s"><v>1</v></c><c r="V51"><f>6*7</f><v>42</v></c>
      <c r="X51" t="inlineStr"><is><r><t>中文</t></r><r><t>文本</t></r></is></c>
      <c r="Y51" t="b"><v>1</v></c></row>''', extras={
        "xl/sharedStrings.xml": "<sst><si><t>unused</t></si><si><t>保留此值</t></si></sst>",
    })
    result = spreadsheet_page(path, 0, 50, 20)
    assert result["row_start"] == 50 and result["column_start"] == 20
    assert result["sheet_name"] == "销售明细"
    assert len(result["values"]) == 50 and len(result["values"][0]) == 20
    assert result["values"][0][:5] == ["保留此值", "42", "", "中文文本", "TRUE"]
    assert all(value == "" for value in result["values"][1])


def test_page_only_collects_requested_rectangle_and_formats_dates(tmp_path):
    path = workbook(tmp_path, '<row><c r="A1" s="0"><v>45292</v></c><c r="B1"><v>45292</v></c></row>', extras={
        "xl/styles.xml": '<styleSheet><cellXfs><xf numFmtId="14"/></cellXfs></styleSheet>',
    })
    assert spreadsheet_page(path, 0, 0, 0)["values"][0][0] == "2024-01-01"
    assert spreadsheet_page(path, 0, 50, 0)["values"][0][0] == ""


def test_archive_and_actual_inflate_budgets(tmp_path, monkeypatch):
    path = workbook(tmp_path, '<row><c r="A1"><v>42</v></c></row>')
    monkeypatch.setattr(policy, "MAX_EXPANDED_BYTES", 10)
    with pytest.raises(policy.PreviewLimit, match="解压"):
        inspect_file(path)
    monkeypatch.setattr(policy, "MAX_EXPANDED_BYTES", 1_000_000)
    package = Package(path)
    try:
        monkeypatch.setattr(policy, "MAX_EXPANDED_BYTES", 10)
        with pytest.raises(policy.PreviewLimit, match="实际解压"):
            list(package.events("xl/worksheets/sheet1.xml"))
    finally:
        package.close()


@pytest.mark.parametrize("encoding", ["utf-8", "utf-16"])
def test_xml_entity_declarations_are_rejected_before_expansion(tmp_path, encoding):
    path = workbook(tmp_path, "", extras={
        "xl/workbook.xml": '<!DOCTYPE x [<!ENTITY a "long">]><workbook>&a;</workbook>'.encode(encoding),
    })
    with pytest.raises(ValueError, match="实体"):
        inspect_file(path)


def test_word_rejects_invalid_body_before_browser_receives_file(tmp_path):
    path = tmp_path / "large.docx"
    with ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", "<document>" + "<p/>" * 12 + "</document>")
    with pytest.raises(ValueError, match="正文结构"):
        inspect_file(path)


def test_long_xml_token_stops_before_allocating_full_text(tmp_path, monkeypatch):
    path = workbook(tmp_path, '<row><c r="A1" t="inlineStr"><is><t>' + "x" * 200_000 + "</t></is></c></row>")
    monkeypatch.setattr(policy, "MAX_XML_TOKEN_BYTES", 65536)
    with pytest.raises(policy.PreviewLimit, match="单个文本"):
        inspect_file(path)


def test_actual_text_read_is_bounded_even_when_file_grows_after_stat(tmp_path, monkeypatch):
    import os
    from app.infra.file_workspace import FileWorkspaceStorage, TextFileReadLimitExceededError
    path = tmp_path / "growing.txt"
    path.write_bytes(b"x" * 100)
    original = Path.stat
    def stat(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        if self == path:
            fields = list(result)
            fields[6] = 1  # stale size; open() still sees the real 100 bytes
            return os.stat_result(fields)
        return result
    monkeypatch.setattr(Path, "stat", stat)
    with pytest.raises(TextFileReadLimitExceededError):
        FileWorkspaceStorage().read_text_file_limited(str(tmp_path), path.name, max_size_bytes=10)


def test_text_read_never_pairs_old_content_with_new_file_version(tmp_path, monkeypatch):
    import os
    from app.core.errors import ConflictError
    from app.infra.file_workspace import FileWorkspaceStorage
    path = tmp_path / "changing.txt"
    path.write_bytes(b"old")
    original = os.fstat
    calls = 0
    def changed_after_read(fd):
        nonlocal calls
        calls += 1
        if calls == 2:
            path.write_bytes(b"new content")
        return original(fd)
    monkeypatch.setattr(os, "fstat", changed_after_read)
    with pytest.raises(ConflictError, match="读取期间"):
        FileWorkspaceStorage().read_text_file_limited(str(tmp_path), path.name, max_size_bytes=100)


class Request:
    def __init__(self):
        self.disconnected = False

    async def is_disconnected(self):
        return self.disconnected


def test_real_worker_and_version_guard(tmp_path):
    path = workbook(tmp_path, '<row><c r="A1"><v>42</v></c></row>')

    async def run():
        result = await runtime.preview_file(Request(), path)
        assert result["mode"] == "inline"
        page = await runtime.preview_file(Request(), path, "spreadsheet", version=result["version"], sheet=0, row=0, column=0)
        assert page["values"][0][0] == "42"
        path.write_bytes(b"changed")
        with pytest.raises(AppError, match="文件已变化"):
            await runtime.preview_file(Request(), path, "spreadsheet", version=result["version"], sheet=0, row=0, column=0)
    asyncio.run(run())


def test_database_worker_retains_read_only_contract_and_result_schema(tmp_path):
    path = tmp_path / "records.sqlite"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE items (name TEXT)")
        connection.execute("INSERT INTO items VALUES ('完整内容')")

    async def run():
        result = await runtime.preview_file(Request(), path, "database", method="overview",
                                            project_id="p", target_path="records.sqlite", arguments={})
        assert result["project_id"] == "p" and result["tables_count"] == 1
        result = await runtime.preview_file(Request(), path, "database", method="table_rows",
                                            project_id="p", target_path="records.sqlite",
                                            arguments={"object_name": "items", "limit": 100, "offset": 0})
        assert result["rows"][0][0]["value"] == "完整内容"
        with pytest.raises(AppError) as failed:
            await runtime.preview_file(Request(), path, "database", method="query",
                                       project_id="p", target_path="records.sqlite",
                                       arguments={"sql": "DELETE FROM items", "limit": 100})
        assert failed.value.status_code == 400
    asyncio.run(run())
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT count(*) FROM items").fetchone()[0] == 1


def test_images_are_checked_before_decode_and_animations_include_all_frames(tmp_path, monkeypatch):
    from PIL import Image
    path = tmp_path / "image.png"
    Image.new("RGB", (3, 3)).save(path)
    monkeypatch.setattr(policy, "MAX_IMAGE_PIXELS", 4)
    with pytest.raises(policy.PreviewLimit, match="像素"):
        inspect_file(path)
    path = tmp_path / "animation.gif"
    frames = [Image.new("RGB", (2, 2), color) for color in ("red", "green", "blue")]
    frames[0].save(path, save_all=True, append_images=frames[1:])
    with pytest.raises(policy.PreviewLimit, match="累计"):
        inspect_file(path)


@pytest.mark.parametrize("stop", ["disconnect", "cancel", "timeout"])
def test_stop_reaps_process_and_removes_temporary_data(tmp_path, monkeypatch, stop):
    # A deliberately stalled parser verifies actual process cancellation.
    (tmp_path / "worker.py").write_text("import time; time.sleep(60)", encoding="utf-8")
    monkeypatch.setattr(runtime, "__file__", str(tmp_path / "runtime.py"))
    monkeypatch.setattr(runtime, "_slots", asyncio.Semaphore(1))
    monkeypatch.setattr(policy, "PROCESS_SECONDS", 0.15 if stop == "timeout" else 30)
    processes = []
    paths = []
    popen = subprocess.Popen

    def launch(args, **kwargs):
        process = popen(args, **kwargs)
        processes.append(process)
        paths.append(Path(args[-1]).parent)
        return process
    monkeypatch.setattr(runtime.subprocess, "Popen", launch)

    async def run():
        request = Request()
        task = asyncio.create_task(runtime.preview_file(request, tmp_path / "source"))
        while not processes:
            await asyncio.sleep(0.01)
        if stop == "disconnect":
            request.disconnected = True
        elif stop == "cancel":
            task.cancel()
        with pytest.raises((AppError, asyncio.CancelledError)):
            await task
        assert processes[0].poll() is not None
        assert not paths[0].exists()
        assert runtime._slots._value == 1
    asyncio.run(run())


def test_queued_cancellation_never_starts_another_process(tmp_path, monkeypatch):
    async def run():
        monkeypatch.setattr(runtime, "_slots", asyncio.Semaphore(0))
        def forbidden(*args, **kwargs):
            pytest.fail("cancelled queued work launched a process")
        monkeypatch.setattr(runtime.subprocess, "Popen", forbidden)
        request = Request()
        task = asyncio.create_task(runtime.preview_file(request, tmp_path / "source"))
        await asyncio.sleep(0.02)
        request.disconnected = True
        with pytest.raises(AppError, match="取消"):
            await task
    asyncio.run(run())


def test_sqlite_header_is_bounded_and_query_has_budget(tmp_path, monkeypatch):
    path = tmp_path / "db.sqlite"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE example(value)")
    class Files:
        def get_file_path(self, *_args):
            return str(path)
    service = ProjectDatabaseService(Files())
    def forbidden(*_args):
        pytest.fail("must not read entire database for its header")
    monkeypatch.setattr(Path, "read_bytes", forbidden)
    assert service._resolve_sqlite_file("project", "db.sqlite").path == path
    import app.services.project.project_database as database
    monkeypatch.setattr(database, "_PREVIEW_QUERY_SECONDS", 0.001)
    with pytest.raises(BadRequestError, match="已中止"):
        service.query("project", target_path="db.sqlite", limit=10,
                      sql="WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM n) SELECT sum(x) FROM n")
    with sqlite3.connect(path) as connection:
        with pytest.raises(BadRequestError, match="超过"):
            _read_rows(connection.execute("SELECT printf('%.*c', 4194305, 'x')"), limit=10)
