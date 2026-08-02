from fastapi import APIRouter, Query

from app.schemas.project import (
    ProjectDatabaseOverviewResponse,
    ProjectDatabaseQueryRequest,
    ProjectDatabaseQueryResponse,
    ProjectDatabaseRowsResponse,
    ProjectDatabaseTableSchemaResponse,
)
from app.services.project.project_database import get_project_database_service

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get(
    "/{project_id}/databases/overview",
    response_model=ProjectDatabaseOverviewResponse,
    summary="Read SQLite database overview",
)
def read_project_database_overview(
    project_id: str,
    path: str = Query(..., description="SQLite 数据库文件路径"),
) -> ProjectDatabaseOverviewResponse:
    service = get_project_database_service()
    return service.overview(project_id, target_path=path)


@router.get(
    "/{project_id}/databases/table-data",
    response_model=ProjectDatabaseRowsResponse,
    summary="Read SQLite table rows",
)
def read_project_database_table_data(
    project_id: str,
    path: str = Query(..., description="SQLite 数据库文件路径"),
    object_name: str = Query(..., min_length=1, description="表或视图名称"),
    limit: int = Query(default=100, ge=1),
    offset: int = Query(default=0, ge=0),
) -> ProjectDatabaseRowsResponse:
    service = get_project_database_service()
    return service.table_rows(
        project_id,
        target_path=path,
        object_name=object_name,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{project_id}/databases/table-schema",
    response_model=ProjectDatabaseTableSchemaResponse,
    summary="Read SQLite table schema",
)
def read_project_database_table_schema(
    project_id: str,
    path: str = Query(..., description="SQLite 数据库文件路径"),
    object_name: str = Query(..., min_length=1, description="表或视图名称"),
) -> ProjectDatabaseTableSchemaResponse:
    service = get_project_database_service()
    return service.table_schema(
        project_id,
        target_path=path,
        object_name=object_name,
    )


@router.post(
    "/{project_id}/databases/query",
    response_model=ProjectDatabaseQueryResponse,
    summary="Run read-only SQLite query",
)
def run_project_database_query(
    project_id: str,
    payload: ProjectDatabaseQueryRequest,
) -> ProjectDatabaseQueryResponse:
    service = get_project_database_service()
    return service.query(
        project_id,
        target_path=payload.path,
        sql=payload.sql,
        limit=payload.limit,
    )
