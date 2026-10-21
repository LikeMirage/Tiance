"""Standalone disposable worker. No application bootstrap, database or network."""
import json
from pathlib import Path
import sys


def main():
    request_path, result_path = map(Path, sys.argv[1:3])
    request = json.loads(request_path.read_text(encoding="utf-8"))
    # The bundled Python uses an isolated _pth. Reuse the server's explicit
    # dependency roots rather than relying on ambient PYTHONPATH or a venv.
    sys.path[:0] = request.pop("module_paths")
    from app.services.file_preview import policy
    from app.services.file_preview.inspection import inspect_file
    from app.services.file_preview.spreadsheet import spreadsheet_page
    from app.services.file_preview.delimited import inspect_delimited, delimited_page
    from app.core.errors import AppError

    try:
        path = Path(request["path"])
        current = policy.require_version(path, request.get("version"))
        is_delimited = path.suffix.lower() in (".csv", ".tsv")
        options = {"encoding": request.get("encoding", "auto"), "delimiter": request.get("delimiter", "auto")}
        if request["operation"] == "inspect":
            result = inspect_delimited(path, **options) if is_delimited else inspect_file(path)
        elif request["operation"] == "spreadsheet":
            if is_delimited:
                result = delimited_page(path, request["sheet"], request["row"], request["column"], **options)
            elif path.suffix.lower() != ".xlsx" or path.stat().st_size > policy.MAX_PACKAGE_BYTES:
                raise policy.PreviewLimit("分页读取仅支持 64 MiB 以内的 XLSX 文件。")
            else:
                result = spreadsheet_page(path, request["sheet"], request["row"], request["column"])
        elif request["operation"] == "word":
            from app.services.file_preview.word import word_chunk
            result = word_chunk(path, request["chunk"])
        elif request["operation"] == "database":
            from app.services.project.project_database import ProjectDatabaseService
            class ResolvedFile:
                def get_file_path(self, *_args):
                    return str(path)
            service = ProjectDatabaseService(ResolvedFile())
            methods = {"overview": service.overview, "table_rows": service.table_rows,
                       "table_schema": service.table_schema, "query": service.query}
            result = methods[request["method"]](
                request["project_id"], target_path=request["target_path"], **request.get("arguments", {}),
            ).model_dump(mode="json")
        else:
            raise ValueError("未知预览操作。")
        policy.require_version(path, current)
        result["version"] = current
    except policy.PreviewLimit as error:
        result = {"mode": "blocked", "message": str(error)}
    except AppError as error:
        result = {"error": error.message, "code": error.code, "status_code": error.status_code}
    except Exception as error:
        result = {"error": str(error) or type(error).__name__}
    encoded = json.dumps(result, ensure_ascii=False).encode("utf-8")
    if len(encoded) > policy.MAX_RESULT_BYTES:
        encoded = json.dumps({"mode": "blocked", "message": "本页输出超过 4 MiB，请用默认应用查看。"}, ensure_ascii=False).encode("utf-8")
    result_path.write_bytes(encoded)


if __name__ == "__main__":
    main()
