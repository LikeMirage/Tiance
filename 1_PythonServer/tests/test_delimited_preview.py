import csv

import pytest

from app.services.file_preview import policy
from app.services.file_preview.delimited import inspect_delimited, delimited_page


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig", "gb18030", "utf-16"])
@pytest.mark.parametrize("extension,separator", [(".csv", ","), (".tsv", "\t"), (".csv", ";")])
def test_encoding_and_record_boundaries(tmp_path, encoding, extension, separator):
    path = tmp_path / ("销售" + extension)
    data = [["编号", "备注", "金额"], ["00012", '含逗号,和"引号"\n第二行', "001.20"],
            ["=SUM(A1:A2)", "尾部空格  ", ""]]
    with path.open("w", encoding=encoding, newline="") as stream:
        csv.writer(stream, delimiter=separator).writerows(data)
    result = inspect_delimited(path)
    assert result["mode"] == "paged"
    assert result["sheets"] == [{"name": path.name, "rows": 3, "columns": 3}]
    page = delimited_page(path, 0, 0, 0, **result["delimited"])
    assert [row[:3] for row in page["values"]] == data


def test_rectangle_ragged_rows_and_empty_file(tmp_path):
    path = tmp_path / "file.csv"
    path.write_text("".join(",".join(f"{r}:{c}" for c in range(27)) + "\n" for r in range(120))
                    + "last\n\n", encoding="utf-8")
    result = inspect_delimited(path)
    assert result["sheets"][0] == {"name": "file.csv", "rows": 122, "columns": 27}
    page = delimited_page(path, 0, 50, 20)
    assert len(page["values"]) == 50
    assert page["values"][0][:7] == [f"50:{c}" for c in range(20, 27)]
    assert page["values"][-1][0] == "99:20"
    assert delimited_page(path, 0, 120, 0)["values"][1] == [""] * 20
    path.write_bytes(b"")
    assert inspect_delimited(path)["sheets"][0]["rows"] == 0
    assert delimited_page(path, 0, 0, 0)["values"] == []


def test_explicit_format_and_errors_are_visible(tmp_path):
    path = tmp_path / "file.csv"
    path.write_text("a|b\nc|d\n", encoding="utf-8")
    assert inspect_delimited(path)["delimited"]["delimiter"] == "pipe"
    assert inspect_delimited(path, delimiter="comma")["sheets"][0]["columns"] == 1
    with pytest.raises(ValueError, match="不支持"):
        inspect_delimited(path, encoding="arbitrary-codec")
    with pytest.raises(ValueError, match="坐标"):
        delimited_page(path, 1, 0, 0)
    path.write_text('a,"unterminated\n', encoding="utf-8")
    with pytest.raises(ValueError, match="解析失败"):
        inspect_delimited(path, delimiter="comma")
    path.write_bytes("编号,金额\n".encode("gb18030"))
    with pytest.raises(ValueError, match="编码"):
        inspect_delimited(path, encoding="utf-8-sig")


def test_resource_limits_cover_multiline_records_and_columns(tmp_path, monkeypatch):
    path = tmp_path / "file.csv"
    monkeypatch.setattr(policy, "MAX_DELIMITED_RECORD_CHARS", 32)
    path.write_text('a,"' + "long\n" * 10 + '"\n', encoding="utf-8")
    with pytest.raises(policy.PreviewLimit, match="记录"):
        inspect_delimited(path)
    path.write_text("a,b,c,d\n", encoding="utf-8")
    monkeypatch.setattr(policy, "MAX_DELIMITED_COLUMNS", 3)
    with pytest.raises(policy.PreviewLimit, match="列"):
        inspect_delimited(path)
    monkeypatch.setattr(policy, "MAX_DELIMITED_BYTES", 2)
    with pytest.raises(policy.PreviewLimit, match="MiB"):
        inspect_delimited(path)


def test_csv_real_worker_and_both_routes(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.routes.project import files
    from app.api.routes.tools import tool_folder_files
    from app.core.errors import register_exception_handlers
    path = tmp_path / "file.csv"
    path.write_text('编号;备注\n001;"两行\n备注"\n', encoding="utf-8-sig", newline="")
    class Files:
        def get_file_path(self, *_ids, target_path):
            assert target_path == path.name
            return path
    monkeypatch.setattr(files, "get_project_file_service", Files)
    monkeypatch.setattr(tool_folder_files, "get_tool_folder_file_service", Files)
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(files.router)
    app.include_router(tool_folder_files.router)
    with TestClient(app) as client:
        for prefix in ["/projects/p", "/tools/categories/c/projects/t"]:
            params = {"path": path.name, "encoding": "utf-8-sig", "delimiter": "semicolon"}
            info = client.get(prefix + "/files/preview", params=params)
            assert info.status_code == 200, info.text
            assert info.json()["sheets"][0]["columns"] == 2
            params["version"] = info.json()["version"]
            response = client.get(prefix + "/files/preview/spreadsheet", params=params)
            assert response.status_code == 200, response.text
            assert response.json()["values"][1][:2] == ["001", "两行\n备注"]
            assert client.get(prefix + "/files/preview/spreadsheet", params={**params, "version": "old"}).status_code == 409
