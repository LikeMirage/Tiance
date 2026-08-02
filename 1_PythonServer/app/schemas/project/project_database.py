from typing import Any, Literal

from pydantic import BaseModel, Field


ProjectDatabaseObjectType = Literal["table", "view", "index", "trigger"]


class ProjectDatabaseObjectResponse(BaseModel):
    name: str
    type: ProjectDatabaseObjectType
    table_name: str | None = None
    sql: str | None = None


class ProjectDatabaseOverviewResponse(BaseModel):
    project_id: str
    path: str
    file_name: str
    size_bytes: int
    tables_count: int
    views_count: int
    indexes_count: int
    triggers_count: int
    objects: list[ProjectDatabaseObjectResponse] = Field(default_factory=list)


class ProjectDatabaseCellResponse(BaseModel):
    value_type: Literal["null", "integer", "real", "text", "blob"]
    value: Any = None
    size_bytes: int | None = None


class ProjectDatabaseRowsResponse(BaseModel):
    project_id: str
    path: str
    object_name: str
    columns: list[str] = Field(default_factory=list)
    rows: list[list[ProjectDatabaseCellResponse]] = Field(default_factory=list)
    limit: int
    offset: int
    has_more: bool = False


class ProjectDatabaseColumnResponse(BaseModel):
    cid: int
    name: str
    data_type: str
    not_null: bool
    default_value: str | None = None
    primary_key: int
    hidden: int = 0


class ProjectDatabaseIndexResponse(BaseModel):
    name: str
    unique: bool
    origin: str
    partial: bool


class ProjectDatabaseForeignKeyResponse(BaseModel):
    id: int
    seq: int
    table: str
    from_column: str
    to_column: str | None = None
    on_update: str | None = None
    on_delete: str | None = None
    match: str | None = None


class ProjectDatabaseTableSchemaResponse(BaseModel):
    project_id: str
    path: str
    object_name: str
    object_type: Literal["table", "view"]
    create_sql: str | None = None
    columns: list[ProjectDatabaseColumnResponse] = Field(default_factory=list)
    indexes: list[ProjectDatabaseIndexResponse] = Field(default_factory=list)
    foreign_keys: list[ProjectDatabaseForeignKeyResponse] = Field(default_factory=list)


class ProjectDatabaseQueryRequest(BaseModel):
    path: str
    sql: str = Field(min_length=1)
    limit: int = Field(default=200, ge=1)


class ProjectDatabaseQueryResponse(BaseModel):
    project_id: str
    path: str
    sql: str
    columns: list[str] = Field(default_factory=list)
    rows: list[list[ProjectDatabaseCellResponse]] = Field(default_factory=list)
    limit: int
    truncated: bool = False
