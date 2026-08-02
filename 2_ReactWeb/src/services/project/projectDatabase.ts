import { fetchJson } from "../http/httpClient";

export type ProjectDatabaseObjectType = "table" | "view" | "index" | "trigger";

export type ProjectDatabaseObject = {
  name: string;
  type: ProjectDatabaseObjectType;
  table_name: string | null;
  sql: string | null;
};

export type ProjectDatabaseOverview = {
  project_id: string;
  path: string;
  file_name: string;
  size_bytes: number;
  tables_count: number;
  views_count: number;
  indexes_count: number;
  triggers_count: number;
  objects: ProjectDatabaseObject[];
};

export type ProjectDatabaseCell = {
  value_type: "null" | "integer" | "real" | "text" | "blob";
  value: unknown;
  size_bytes: number | null;
};

export type ProjectDatabaseRows = {
  project_id: string;
  path: string;
  object_name: string;
  columns: string[];
  rows: ProjectDatabaseCell[][];
  limit: number;
  offset: number;
  has_more: boolean;
};

export type ProjectDatabaseColumn = {
  cid: number;
  name: string;
  data_type: string;
  not_null: boolean;
  default_value: string | null;
  primary_key: number;
  hidden: number;
};

export type ProjectDatabaseIndex = {
  name: string;
  unique: boolean;
  origin: string;
  partial: boolean;
};

export type ProjectDatabaseForeignKey = {
  id: number;
  seq: number;
  table: string;
  from_column: string;
  to_column: string | null;
  on_update: string | null;
  on_delete: string | null;
  match: string | null;
};

export type ProjectDatabaseTableSchema = {
  project_id: string;
  path: string;
  object_name: string;
  object_type: "table" | "view";
  create_sql: string | null;
  columns: ProjectDatabaseColumn[];
  indexes: ProjectDatabaseIndex[];
  foreign_keys: ProjectDatabaseForeignKey[];
};

export type ProjectDatabaseQueryResult = {
  project_id: string;
  path: string;
  sql: string;
  columns: string[];
  rows: ProjectDatabaseCell[][];
  limit: number;
  truncated: boolean;
};

export function getProjectDatabaseOverview(
  projectId: string,
  path: string,
  init?: RequestInit,
) {
  const query = new URLSearchParams({ path });
  return fetchJson<ProjectDatabaseOverview>(
    `/api/projects/${encodeURIComponent(projectId)}/databases/overview?${query.toString()}`,
    init,
  );
}

export function getProjectDatabaseTableData(
  projectId: string,
  input: {
    limit: number;
    objectName: string;
    offset: number;
    path: string;
  },
  init?: RequestInit,
) {
  const query = new URLSearchParams({
    path: input.path,
    object_name: input.objectName,
    limit: String(input.limit),
    offset: String(input.offset),
  });
  return fetchJson<ProjectDatabaseRows>(
    `/api/projects/${encodeURIComponent(projectId)}/databases/table-data?${query.toString()}`,
    init,
  );
}

export function getProjectDatabaseTableSchema(
  projectId: string,
  input: {
    objectName: string;
    path: string;
  },
  init?: RequestInit,
) {
  const query = new URLSearchParams({
    path: input.path,
    object_name: input.objectName,
  });
  return fetchJson<ProjectDatabaseTableSchema>(
    `/api/projects/${encodeURIComponent(projectId)}/databases/table-schema?${query.toString()}`,
    init,
  );
}

export function queryProjectDatabase(
  projectId: string,
  input: {
    limit: number;
    path: string;
    sql: string;
  },
  init?: RequestInit,
) {
  return fetchJson<ProjectDatabaseQueryResult>(
    `/api/projects/${encodeURIComponent(projectId)}/databases/query`,
    {
      ...init,
      method: "POST",
      body: JSON.stringify({
        path: input.path,
        sql: input.sql,
        limit: input.limit,
      }),
    },
  );
}
