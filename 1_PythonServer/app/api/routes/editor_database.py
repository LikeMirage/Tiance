from fastapi import APIRouter, Query, Request

from app.core.errors import AppError
from app.schemas.project import ProjectDatabaseQueryRequest
from app.services.editor_local_files import local_path
from app.services.file_preview.runtime import preview_file

router = APIRouter(prefix="/editor/local/databases", tags=["editor"])


async def _preview(request: Request, path: str, method: str, **arguments) -> dict:
    result = await preview_file(request, local_path(path), "database", method=method,
                                project_id="", target_path=path, arguments=arguments)
    if result.get("mode") == "blocked":
        raise AppError(result["message"], code="preview_result_limit", status_code=422)
    return result


@router.get("/overview")
async def overview(request: Request, path: str) -> dict:
    return await _preview(request, path, "overview")


@router.get("/table-data")
async def rows(request: Request, path: str, object_name: str = Query(min_length=1),
               limit: int = Query(100, ge=1), offset: int = Query(0, ge=0)) -> dict:
    return await _preview(request, path, "table_rows", object_name=object_name, limit=limit, offset=offset)


@router.get("/table-schema")
async def schema(request: Request, path: str, object_name: str = Query(min_length=1)) -> dict:
    return await _preview(request, path, "table_schema", object_name=object_name)


@router.post("/query")
async def query(request: Request, payload: ProjectDatabaseQueryRequest) -> dict:
    return await _preview(request, payload.path, "query", sql=payload.sql, limit=payload.limit)
