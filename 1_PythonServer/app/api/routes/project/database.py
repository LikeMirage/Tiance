from fastapi import APIRouter, Query, Request

from app.schemas.project import (
    ProjectDatabaseOverviewResponse,
    ProjectDatabaseQueryRequest,
    ProjectDatabaseQueryResponse,
    ProjectDatabaseRowsResponse,
    ProjectDatabaseTableSchemaResponse,
)
from app.core.errors import AppError
from app.services.project.project_files import get_project_file_service
from app.services.file_preview.runtime import preview_file

router = APIRouter(prefix="/projects", tags=["projects"])


async def _database_preview(request: Request, project_id: str, path: str, method: str, **arguments) -> dict:
    file_path = get_project_file_service().get_file_path(project_id, path)
    result = await preview_file(request, file_path, "database", method=method,
                                project_id=project_id, target_path=path, arguments=arguments)
    if result.get("mode") == "blocked":
        raise AppError(result["message"], code="preview_result_limit", status_code=422)
    return result


@router.get(
    "/{project_id}/databases/overview",
    response_model=ProjectDatabaseOverviewResponse,
    summary="Read SQLite database overview",
)
async def read_project_database_overview(
    request: Request,
    project_id: str,
    path: str = Query(..., description="SQLite 数据库文件路径"),
) -> ProjectDatabaseOverviewResponse:
    return ProjectDatabaseOverviewResponse.model_validate(await _database_preview(request, project_id, path, "overview"))


@router.get(
    "/{project_id}/databases/table-data",
    response_model=ProjectDatabaseRowsResponse,
    summary="Read SQLite table rows",
)
async def read_project_database_table_data(
    request: Request,
    project_id: str,
    path: str = Query(..., description="SQLite 数据库文件路径"),
    object_name: str = Query(..., min_length=1, description="表或视图名称"),
    limit: int = Query(default=100, ge=1),
    offset: int = Query(default=0, ge=0),
) -> ProjectDatabaseRowsResponse:
    return ProjectDatabaseRowsResponse.model_validate(await _database_preview(
        request, project_id, path, "table_rows",
        object_name=object_name,
        limit=limit,
        offset=offset,
    ))


@router.get(
    "/{project_id}/databases/table-schema",
    response_model=ProjectDatabaseTableSchemaResponse,
    summary="Read SQLite table schema",
)
async def read_project_database_table_schema(
    request: Request,
    project_id: str,
    path: str = Query(..., description="SQLite 数据库文件路径"),
    object_name: str = Query(..., min_length=1, description="表或视图名称"),
) -> ProjectDatabaseTableSchemaResponse:
    return ProjectDatabaseTableSchemaResponse.model_validate(await _database_preview(
        request, project_id, path, "table_schema",
        object_name=object_name,
    ))


@router.post(
    "/{project_id}/databases/query",
    response_model=ProjectDatabaseQueryResponse,
    summary="Run read-only SQLite query",
)
async def run_project_database_query(
    request: Request,
    project_id: str,
    payload: ProjectDatabaseQueryRequest,
) -> ProjectDatabaseQueryResponse:
    return ProjectDatabaseQueryResponse.model_validate(await _database_preview(
        request, project_id, payload.path, "query",
        sql=payload.sql,
        limit=payload.limit,
    ))
