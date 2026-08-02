import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterator

from app.core.errors import BadRequestError
from app.schemas.project.project_database import (
    ProjectDatabaseCellResponse,
    ProjectDatabaseColumnResponse,
    ProjectDatabaseForeignKeyResponse,
    ProjectDatabaseIndexResponse,
    ProjectDatabaseObjectResponse,
    ProjectDatabaseOverviewResponse,
    ProjectDatabaseQueryResponse,
    ProjectDatabaseRowsResponse,
    ProjectDatabaseTableSchemaResponse,
)
from app.services.project.project_files import ProjectFileService, get_project_file_service

_SQLITE_HEADER = b"SQLite format 3\x00"
_SQLITE_EXTENSIONS = {".db", ".sqlite", ".sqlite3"}
_OBJECT_TYPES = ("table", "view", "index", "trigger")
_READONLY_PRAGMAS = {
    "database_list",
    "foreign_key_list",
    "index_info",
    "index_list",
    "index_xinfo",
    "table_info",
    "table_list",
    "table_xinfo",
}


@dataclass(frozen=True)
class ResolvedSqliteFile:
    path: Path
    is_empty: bool


class ProjectDatabaseService:
    def __init__(self, file_service: ProjectFileService) -> None:
        self._file_service = file_service

    def overview(self, project_id: str, *, target_path: str) -> ProjectDatabaseOverviewResponse:
        db_file = self._resolve_sqlite_file(project_id, target_path)
        objects: list[ProjectDatabaseObjectResponse] = []
        if not db_file.is_empty:
            with self._connect_readonly(db_file.path) as connection:
                objects = self._list_objects(connection)
        return ProjectDatabaseOverviewResponse(
            project_id=project_id,
            path=target_path,
            file_name=db_file.path.name,
            size_bytes=db_file.path.stat().st_size,
            tables_count=sum(1 for item in objects if item.type == "table"),
            views_count=sum(1 for item in objects if item.type == "view"),
            indexes_count=sum(1 for item in objects if item.type == "index"),
            triggers_count=sum(1 for item in objects if item.type == "trigger"),
            objects=objects,
        )

    def table_rows(
        self,
        project_id: str,
        *,
        target_path: str,
        object_name: str,
        limit: int,
        offset: int,
    ) -> ProjectDatabaseRowsResponse:
        db_file = self._resolve_sqlite_file(project_id, target_path)
        if db_file.is_empty:
            raise BadRequestError("空数据库没有可查询的表或视图。")
        with self._connect_readonly(db_file.path) as connection:
            self._require_table_or_view(connection, object_name)
            cursor = connection.execute(
                f"SELECT * FROM {_quote_identifier(object_name)} LIMIT ? OFFSET ?",
                (limit + 1, offset),
            )
            columns, rows = _read_rows(cursor, limit=limit)
            has_more = len(rows) > limit
        return ProjectDatabaseRowsResponse(
            project_id=project_id,
            path=target_path,
            object_name=object_name,
            columns=columns,
            rows=rows[:limit],
            limit=limit,
            offset=offset,
            has_more=has_more,
        )

    def table_schema(
        self,
        project_id: str,
        *,
        target_path: str,
        object_name: str,
    ) -> ProjectDatabaseTableSchemaResponse:
        db_file = self._resolve_sqlite_file(project_id, target_path)
        if db_file.is_empty:
            raise BadRequestError("空数据库没有表结构。")
        with self._connect_readonly(db_file.path) as connection:
            object_type, create_sql = self._require_table_or_view(connection, object_name)
            columns = [
                ProjectDatabaseColumnResponse(
                    cid=int(row[0]),
                    name=str(row[1] or ""),
                    data_type=str(row[2] or ""),
                    not_null=bool(row[3]),
                    default_value=None if row[4] is None else str(row[4]),
                    primary_key=int(row[5] or 0),
                    hidden=int(row[6] or 0) if len(row) > 6 else 0,
                )
                for row in connection.execute(f"PRAGMA table_xinfo({_quote_string(object_name)})")
            ]
            indexes = [
                ProjectDatabaseIndexResponse(
                    name=str(row[1] or ""),
                    unique=bool(row[2]),
                    origin=str(row[3] or ""),
                    partial=bool(row[4]),
                )
                for row in connection.execute(f"PRAGMA index_list({_quote_string(object_name)})")
            ]
            foreign_keys = [
                ProjectDatabaseForeignKeyResponse(
                    id=int(row[0]),
                    seq=int(row[1]),
                    table=str(row[2] or ""),
                    from_column=str(row[3] or ""),
                    to_column=None if row[4] is None else str(row[4]),
                    on_update=None if row[5] is None else str(row[5]),
                    on_delete=None if row[6] is None else str(row[6]),
                    match=None if row[7] is None else str(row[7]),
                )
                for row in connection.execute(f"PRAGMA foreign_key_list({_quote_string(object_name)})")
            ]
        return ProjectDatabaseTableSchemaResponse(
            project_id=project_id,
            path=target_path,
            object_name=object_name,
            object_type=object_type,
            create_sql=create_sql,
            columns=columns,
            indexes=indexes,
            foreign_keys=foreign_keys,
        )

    def query(
        self,
        project_id: str,
        *,
        target_path: str,
        sql: str,
        limit: int,
    ) -> ProjectDatabaseQueryResponse:
        normalized_sql = _normalize_readonly_sql(sql)
        db_file = self._resolve_sqlite_file(project_id, target_path)
        if db_file.is_empty:
            raise BadRequestError("空数据库没有可查询内容。")
        with self._connect_readonly(db_file.path) as connection:
            cursor = connection.execute(normalized_sql)
            columns, rows = _read_rows(cursor, limit=limit)
            truncated = len(rows) > limit
        return ProjectDatabaseQueryResponse(
            project_id=project_id,
            path=target_path,
            sql=normalized_sql,
            columns=columns,
            rows=rows[:limit],
            limit=limit,
            truncated=truncated,
        )

    def _resolve_sqlite_file(self, project_id: str, target_path: str) -> ResolvedSqliteFile:
        file_path = Path(self._file_service.get_file_path(project_id, target_path))
        if not file_path.is_file():
            raise BadRequestError("只能打开 SQLite 数据库文件。")
        try:
            stat = file_path.stat()
        except OSError as exc:
            raise BadRequestError(f"数据库文件读取失败：{exc}") from exc
        if stat.st_size == 0 and file_path.suffix.lower() in _SQLITE_EXTENSIONS:
            return ResolvedSqliteFile(path=file_path, is_empty=True)
        try:
            header = file_path.read_bytes()[: len(_SQLITE_HEADER)]
        except OSError as exc:
            raise BadRequestError(f"数据库文件读取失败：{exc}") from exc
        if header != _SQLITE_HEADER:
            raise BadRequestError("当前文件不是有效的 SQLite 数据库。")
        return ResolvedSqliteFile(path=file_path, is_empty=False)

    @contextmanager
    def _connect_readonly(self, db_path: Path) -> Iterator[sqlite3.Connection]:
        uri = f"{db_path.resolve().as_uri()}?mode=ro"
        try:
            connection = sqlite3.connect(uri, uri=True)
            connection.execute("PRAGMA query_only = ON")
            try:
                yield connection
            finally:
                connection.close()
        except sqlite3.DatabaseError as exc:
            raise BadRequestError(f"SQLite 读取失败：{exc}") from exc

    def _list_objects(self, connection: sqlite3.Connection) -> list[ProjectDatabaseObjectResponse]:
        rows = connection.execute(
            """
            SELECT name, type, tbl_name, sql
            FROM sqlite_schema
            WHERE type IN ('table', 'view', 'index', 'trigger')
              AND name NOT LIKE 'sqlite_%'
            ORDER BY CASE type
              WHEN 'table' THEN 1
              WHEN 'view' THEN 2
              WHEN 'index' THEN 3
              ELSE 4
            END, name
            """
        )
        objects: list[ProjectDatabaseObjectResponse] = []
        for name, object_type, table_name, sql in rows:
            if object_type not in _OBJECT_TYPES:
                continue
            objects.append(
                ProjectDatabaseObjectResponse(
                    name=str(name),
                    type=object_type,
                    table_name=None if table_name is None else str(table_name),
                    sql=None if sql is None else str(sql),
                )
            )
        return objects

    def _require_table_or_view(
        self,
        connection: sqlite3.Connection,
        object_name: str,
    ) -> tuple[str, str | None]:
        row = connection.execute(
            """
            SELECT type, sql
            FROM sqlite_schema
            WHERE name = ? AND type IN ('table', 'view')
            """,
            (object_name,),
        ).fetchone()
        if row is None:
            raise BadRequestError("表或视图不存在。")
        return str(row[0]), None if row[1] is None else str(row[1])


def _read_rows(cursor: sqlite3.Cursor, *, limit: int) -> tuple[list[str], list[list[ProjectDatabaseCellResponse]]]:
    columns = [description[0] for description in cursor.description or []]
    rows: list[list[ProjectDatabaseCellResponse]] = []
    for index, row in enumerate(cursor):
        if index > limit:
            break
        rows.append([_cell_response(value) for value in row])
    return columns, rows


def _cell_response(value: Any) -> ProjectDatabaseCellResponse:
    if value is None:
        return ProjectDatabaseCellResponse(value_type="null")
    if isinstance(value, bytes):
        return ProjectDatabaseCellResponse(value_type="blob", size_bytes=len(value))
    if isinstance(value, int):
        return ProjectDatabaseCellResponse(value_type="integer", value=value)
    if isinstance(value, float):
        return ProjectDatabaseCellResponse(value_type="real", value=value)
    return ProjectDatabaseCellResponse(value_type="text", value=str(value))


def _normalize_readonly_sql(sql: str) -> str:
    normalized = sql.strip()
    if not normalized:
        raise BadRequestError("SQL 不能为空。")
    normalized = normalized[:-1].strip() if normalized.endswith(";") else normalized
    if ";" in normalized:
        raise BadRequestError("只允许执行单条只读 SQL。")

    keyword = _first_sql_keyword(normalized)
    if keyword in {"select", "with"}:
        return normalized
    if keyword == "pragma" and _is_readonly_pragma(normalized):
        return normalized
    raise BadRequestError("只允许执行 SELECT、WITH 或安全 PRAGMA 查询。")


def _first_sql_keyword(sql: str) -> str:
    stripped = _strip_leading_sql_comments(sql)
    return stripped.split(None, 1)[0].lower() if stripped else ""


def _strip_leading_sql_comments(sql: str) -> str:
    remaining = sql.lstrip()
    while remaining.startswith("--") or remaining.startswith("/*"):
        if remaining.startswith("--"):
            line_break = remaining.find("\n")
            if line_break < 0:
                return ""
            remaining = remaining[line_break + 1 :].lstrip()
            continue
        block_end = remaining.find("*/")
        if block_end < 0:
            return ""
        remaining = remaining[block_end + 2 :].lstrip()
    return remaining


def _is_readonly_pragma(sql: str) -> bool:
    normalized = _strip_leading_sql_comments(sql).strip()
    rest = normalized[len("pragma") :].strip()
    if "=" in rest:
        return False
    name = rest.split("(", 1)[0].split(None, 1)[0].strip().lower()
    if "." in name:
        name = name.rsplit(".", 1)[-1]
    return name in _READONLY_PRAGMAS


def _quote_identifier(identifier: str) -> str:
    return f'"{identifier.replace(chr(34), chr(34) * 2)}"'


def _quote_string(value: str) -> str:
    return f"'{value.replace(chr(39), chr(39) * 2)}'"


@lru_cache
def get_project_database_service() -> ProjectDatabaseService:
    return ProjectDatabaseService(get_project_file_service())
