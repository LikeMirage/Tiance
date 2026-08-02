import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowClockwise, CaretLeft, CaretRight, Database } from "@phosphor-icons/react";

import type {
  ProjectDatabaseCell,
  ProjectDatabaseObject,
  ProjectDatabaseOverview,
  ProjectDatabaseQueryResult,
  ProjectDatabaseRows,
  ProjectDatabaseTableSchema,
} from "../../../services/project/projectDatabase";
import {
  getProjectDatabaseOverview,
  getProjectDatabaseTableData,
  getProjectDatabaseTableSchema,
  queryProjectDatabase,
} from "../../../services/project/projectDatabase";
import { useMinimumLoading } from "../../../shared/model/loading/useMinimumLoading";
import { LoadingStrip } from "../../../shared/ui/loading-strip";

import "./database-preview.css";

type LoadState = "idle" | "loading" | "ready" | "error";
type DatabasePanelMode = "data" | "schema" | "query";

type DatabasePreviewProps = {
  displayPath: string;
  fileName: string;
  path: string | null;
  projectId: string | null;
  refreshKey: number | null;
};

const pageSize = 100;

export function DatabasePreview({
  displayPath,
  fileName,
  path,
  projectId,
  refreshKey,
}: DatabasePreviewProps) {
  const [manualRefreshKey, setManualRefreshKey] = useState(0);
  const [overview, setOverview] = useState<ProjectDatabaseOverview | null>(null);
  const [overviewState, setOverviewState] = useState<LoadState>("idle");
  const [overviewError, setOverviewError] = useState<string | null>(null);
  const [selectedObjectName, setSelectedObjectName] = useState<string | null>(null);
  const [mode, setMode] = useState<DatabasePanelMode>("data");
  const [offset, setOffset] = useState(0);
  const [rows, setRows] = useState<ProjectDatabaseRows | null>(null);
  const [rowsState, setRowsState] = useState<LoadState>("idle");
  const [rowsError, setRowsError] = useState<string | null>(null);
  const [schema, setSchema] = useState<ProjectDatabaseTableSchema | null>(null);
  const [schemaState, setSchemaState] = useState<LoadState>("idle");
  const [schemaError, setSchemaError] = useState<string | null>(null);
  const [querySql, setQuerySql] = useState("");
  const [queryResult, setQueryResult] = useState<ProjectDatabaseQueryResult | null>(null);
  const [queryState, setQueryState] = useState<LoadState>("idle");
  const [queryError, setQueryError] = useState<string | null>(null);
  const queryRequestSeqRef = useRef(0);
  const queryAbortControllerRef = useRef<AbortController | null>(null);
  const isOverviewLoadingVisible = useMinimumLoading(overviewState === "loading" && Boolean(overview));

  const reloadKey = `${refreshKey ?? 0}:${manualRefreshKey}`;

  const tableObjects = useMemo(() => (
    overview?.objects.filter((item) => item.type === "table" || item.type === "view") ?? []
  ), [overview]);
  const indexObjects = useMemo(() => (
    overview?.objects.filter((item) => item.type === "index") ?? []
  ), [overview]);
  const triggerObjects = useMemo(() => (
    overview?.objects.filter((item) => item.type === "trigger") ?? []
  ), [overview]);
  const selectedObject = tableObjects.find((item) => item.name === selectedObjectName) ?? null;

  const loadOverview = useCallback((signal?: AbortSignal) => {
    if (!projectId || !path) {
      setOverview(null);
      setOverviewState("idle");
      setOverviewError(null);
      return;
    }

    setOverviewState("loading");
    setOverviewError(null);
    void getProjectDatabaseOverview(projectId, path, { signal })
      .then((response) => {
        if (signal?.aborted) return;
        setOverview(response);
        setOverviewState("ready");
        setSelectedObjectName((current) => {
          if (current && response.objects.some((item) => item.name === current && (item.type === "table" || item.type === "view"))) {
            return current;
          }
          return response.objects.find((item) => item.type === "table" || item.type === "view")?.name ?? null;
        });
      })
      .catch((err: unknown) => {
        if (signal?.aborted) return;
        setOverview(null);
        setOverviewState("error");
        setOverviewError(err instanceof Error ? err.message : "数据库读取失败。");
      });
  }, [path, projectId]);

  useEffect(() => {
    const controller = new AbortController();
    loadOverview(controller.signal);
    return () => controller.abort();
  }, [loadOverview, reloadKey]);

  useEffect(() => {
    setOffset(0);
  }, [selectedObjectName]);

  useEffect(() => {
    if (!projectId || !path || !selectedObjectName) {
      setRows(null);
      setRowsState("idle");
      setRowsError(null);
      return undefined;
    }
    const controller = new AbortController();
    setRowsState("loading");
    setRowsError(null);
    void getProjectDatabaseTableData(projectId, {
      limit: pageSize,
      objectName: selectedObjectName,
      offset,
      path,
    }, { signal: controller.signal })
      .then((response) => {
        if (controller.signal.aborted) return;
        setRows(response);
        setRowsState("ready");
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        setRows(null);
        setRowsState("error");
        setRowsError(err instanceof Error ? err.message : "表数据读取失败。");
      });
    return () => controller.abort();
  }, [offset, path, projectId, reloadKey, selectedObjectName]);

  useEffect(() => {
    if (!projectId || !path || !selectedObjectName) {
      setSchema(null);
      setSchemaState("idle");
      setSchemaError(null);
      return undefined;
    }
    const controller = new AbortController();
    setSchemaState("loading");
    setSchemaError(null);
    void getProjectDatabaseTableSchema(projectId, {
      objectName: selectedObjectName,
      path,
    }, { signal: controller.signal })
      .then((response) => {
        if (controller.signal.aborted) return;
        setSchema(response);
        setSchemaState("ready");
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        setSchema(null);
        setSchemaState("error");
        setSchemaError(err instanceof Error ? err.message : "表结构读取失败。");
      });
    return () => controller.abort();
  }, [path, projectId, reloadKey, selectedObjectName]);

  useEffect(() => {
    if (!selectedObjectName || querySql.trim()) return;
    setQuerySql(`SELECT * FROM ${quoteSqlIdentifier(selectedObjectName)} LIMIT 100;`);
  }, [querySql, selectedObjectName]);

  useEffect(() => {
    queryRequestSeqRef.current += 1;
    queryAbortControllerRef.current?.abort();
    queryAbortControllerRef.current = null;
    setQueryResult(null);
    setQueryError(null);
    setQueryState("idle");
    return () => {
      queryRequestSeqRef.current += 1;
      queryAbortControllerRef.current?.abort();
      queryAbortControllerRef.current = null;
    };
  }, [path, projectId, reloadKey]);

  const executeQuery = useCallback(() => {
    if (!projectId || !path || !querySql.trim() || queryState === "loading") return;
    const requestSeq = ++queryRequestSeqRef.current;
    const queryProjectId = projectId;
    const queryPath = path;
    const queryText = querySql;
    queryAbortControllerRef.current?.abort();
    const controller = new AbortController();
    queryAbortControllerRef.current = controller;
    setQueryState("loading");
    setQueryError(null);
    setQueryResult(null);
    void queryProjectDatabase(queryProjectId, {
      limit: pageSize,
      path: queryPath,
      sql: queryText,
    }, { signal: controller.signal })
      .then((response) => {
        if (controller.signal.aborted || queryRequestSeqRef.current !== requestSeq) return;
        if (response.project_id !== queryProjectId || response.path !== queryPath) return;
        setQueryResult(response);
        setQueryState("ready");
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted || queryRequestSeqRef.current !== requestSeq) return;
        setQueryError(err instanceof Error ? err.message : "SQL 查询失败。");
        setQueryState("error");
      })
      .finally(() => {
        if (queryRequestSeqRef.current === requestSeq) {
          queryAbortControllerRef.current = null;
        }
      });
  }, [path, projectId, querySql, queryState]);

  if (!projectId || !path) {
    return (
      <div className="database-preview database-preview--empty">
        <p>当前数据库文件没有项目路径。</p>
      </div>
    );
  }

  return (
    <div className="database-preview">
      <header className="database-preview__header">
        <div className="database-preview__title-row">
          <Database size={18} weight="fill" />
          <h2>{fileName}</h2>
          <span title={displayPath}>{displayPath}</span>
        </div>
        <button
          className="database-preview__icon-button"
          type="button"
          title="刷新"
          disabled={overviewState === "loading"}
          onClick={() => setManualRefreshKey((value) => value + 1)}
        >
          <ArrowClockwise size={15} weight="bold" />
        </button>
      </header>

      <section className="database-preview__metrics" aria-label="数据库统计">
        <Metric label="表" value={overview?.tables_count ?? 0} />
        <Metric label="视图" value={overview?.views_count ?? 0} />
        <Metric label="索引" value={overview?.indexes_count ?? 0} />
        <Metric label="触发器" value={overview?.triggers_count ?? 0} />
        <Metric label="大小" value={formatBytes(overview?.size_bytes ?? 0)} />
      </section>

      {overviewError ? <p className="database-preview__error">{overviewError}</p> : null}

      <div className="database-preview__main">
        <aside className="database-preview__sidebar" aria-label="数据库对象">
          {overviewState === "loading" && !overview ? <p className="database-preview__muted">正在读取数据库。</p> : null}
          <ObjectGroup
            objects={tableObjects}
            selectedObjectName={selectedObjectName}
            title="表与视图"
            onSelect={(item) => {
              setSelectedObjectName(item.name);
              setMode("data");
            }}
          />
          <ObjectGroup objects={indexObjects} selectedObjectName={null} title="索引" />
          <ObjectGroup objects={triggerObjects} selectedObjectName={null} title="触发器" />
        </aside>

        <main className="database-preview__content">
          {isOverviewLoadingVisible ? (
            <LoadingStrip mode="fill" surface="dark" visual="ring" />
          ) : !selectedObject ? (
            <div className="database-preview__empty-panel">当前数据库没有可预览的表或视图。</div>
          ) : (
            <>
              <div className="database-preview__object-head">
                <div>
                  <span>{selectedObject.type === "view" ? "视图" : "表"}</span>
                  <strong>{selectedObject.name}</strong>
                </div>
                <div className="database-preview__tabs" role="tablist">
                  <button className={mode === "data" ? "active" : ""} type="button" onClick={() => setMode("data")}>数据</button>
                  <button className={mode === "schema" ? "active" : ""} type="button" onClick={() => setMode("schema")}>结构</button>
                  <button className={mode === "query" ? "active" : ""} type="button" onClick={() => setMode("query")}>查询</button>
                </div>
              </div>

              {mode === "data" ? (
                <DataPanel
                  error={rowsError}
                  offset={offset}
                  rows={rows}
                  state={rowsState}
                  onNext={() => setOffset((value) => value + pageSize)}
                  onPrevious={() => setOffset((value) => Math.max(0, value - pageSize))}
                />
              ) : null}
              {mode === "schema" ? (
                <SchemaPanel error={schemaError} schema={schema} state={schemaState} />
              ) : null}
              {mode === "query" ? (
                <QueryPanel
                  error={queryError}
                  result={queryResult}
                  sql={querySql}
                  state={queryState}
                  onExecute={executeQuery}
                  onSqlChange={setQuerySql}
                />
              ) : null}
            </>
          )}
        </main>
      </div>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="database-preview__metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function ObjectGroup({
  objects,
  selectedObjectName,
  title,
  onSelect,
}: {
  objects: ProjectDatabaseObject[];
  selectedObjectName: string | null;
  title: string;
  onSelect?: (item: ProjectDatabaseObject) => void;
}) {
  if (objects.length === 0) return null;
  return (
    <section className="database-preview__object-group">
      <h3>{title}</h3>
      {objects.map((item) => (
        <button
          className={item.name === selectedObjectName ? "database-preview__object database-preview__object--active" : "database-preview__object"}
          disabled={!onSelect}
          key={`${item.type}:${item.name}`}
          title={item.name}
          type="button"
          onClick={() => onSelect?.(item)}
        >
          <span>{item.name}</span>
          <em>{item.type}</em>
        </button>
      ))}
    </section>
  );
}

function DataPanel({
  error,
  offset,
  onNext,
  onPrevious,
  rows,
  state,
}: {
  error: string | null;
  offset: number;
  onNext: () => void;
  onPrevious: () => void;
  rows: ProjectDatabaseRows | null;
  state: LoadState;
}) {
  const isLoadingVisible = useMinimumLoading(state === "loading");

  return (
    <section className="database-preview__panel">
      <div className="database-preview__panel-toolbar">
        <span>{offset + 1}-{offset + (rows?.rows.length ?? 0)}</span>
        <div>
          <button type="button" disabled={offset <= 0 || state === "loading"} onClick={onPrevious}>
            <CaretLeft size={14} weight="bold" />
          </button>
          <button type="button" disabled={!rows?.has_more || state === "loading"} onClick={onNext}>
            <CaretRight size={14} weight="bold" />
          </button>
        </div>
      </div>
      {isLoadingVisible ? (
        <LoadingStrip mode="fill" surface="dark" visual="ring" />
      ) : (
        <>
          {error ? <p className="database-preview__error">{error}</p> : null}
          {rows ? <ResultTable columns={rows.columns} rows={rows.rows} /> : null}
        </>
      )}
    </section>
  );
}

function SchemaPanel({
  error,
  schema,
  state,
}: {
  error: string | null;
  schema: ProjectDatabaseTableSchema | null;
  state: LoadState;
}) {
  const isLoadingVisible = useMinimumLoading(state === "loading");

  return (
    <section className="database-preview__panel">
      {isLoadingVisible ? (
        <LoadingStrip mode="fill" surface="dark" visual="ring" />
      ) : (
        <>
      {error ? <p className="database-preview__error">{error}</p> : null}
      {schema ? (
        <div className="database-preview__schema">
          <h3>字段</h3>
          <table>
            <thead>
              <tr>
                <th>名称</th>
                <th>类型</th>
                <th>非空</th>
                <th>主键</th>
                <th>默认值</th>
              </tr>
            </thead>
            <tbody>
              {schema.columns.map((column) => (
                <tr key={`${column.cid}:${column.name}`}>
                  <td>{column.name}</td>
                  <td>{column.data_type || "-"}</td>
                  <td>{column.not_null ? "是" : "-"}</td>
                  <td>{column.primary_key || "-"}</td>
                  <td>{column.default_value ?? "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <h3>索引</h3>
          {schema.indexes.length > 0 ? (
            <table>
              <thead>
                <tr>
                  <th>名称</th>
                  <th>唯一</th>
                  <th>来源</th>
                  <th>部分索引</th>
                </tr>
              </thead>
              <tbody>
                {schema.indexes.map((index) => (
                  <tr key={index.name}>
                    <td>{index.name}</td>
                    <td>{index.unique ? "是" : "-"}</td>
                    <td>{index.origin || "-"}</td>
                    <td>{index.partial ? "是" : "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : <p className="database-preview__muted">无索引。</p>}
          {schema.create_sql ? (
            <>
              <h3>SQL</h3>
              <pre>{schema.create_sql}</pre>
            </>
          ) : null}
        </div>
      ) : null}
        </>
      )}
    </section>
  );
}

function QueryPanel({
  error,
  onExecute,
  onSqlChange,
  result,
  sql,
  state,
}: {
  error: string | null;
  onExecute: () => void;
  onSqlChange: (value: string) => void;
  result: ProjectDatabaseQueryResult | null;
  sql: string;
  state: LoadState;
}) {
  const isLoadingVisible = useMinimumLoading(state === "loading");

  return (
    <section className="database-preview__panel">
      <div className="database-preview__query">
        <textarea value={sql} spellCheck={false} onChange={(event) => onSqlChange(event.target.value)} />
        <button type="button" disabled={state === "loading" || !sql.trim()} onClick={onExecute}>
          执行
        </button>
      </div>
      {isLoadingVisible ? (
        <LoadingStrip mode="fill" surface="dark" visual="ring" />
      ) : (
        <>
          {error ? <p className="database-preview__error">{error}</p> : null}
          {result?.truncated ? <p className="database-preview__muted">结果已按上限截断。</p> : null}
          {result ? <ResultTable columns={result.columns} rows={result.rows} /> : null}
        </>
      )}
    </section>
  );
}

function ResultTable({
  columns,
  rows,
}: {
  columns: string[];
  rows: ProjectDatabaseCell[][];
}) {
  if (columns.length === 0) {
    return <p className="database-preview__muted">没有可展示的结果。</p>;
  }
  return (
    <div className="database-preview__table-wrap">
      <table className="database-preview__table">
        <thead>
          <tr>
            {columns.map((column, index) => <th key={`${column}:${index}`}>{column || `列 ${index + 1}`}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, rowIndex) => (
            <tr key={rowIndex}>
              {columns.map((_, columnIndex) => (
                <td key={columnIndex} title={cellTitle(row[columnIndex])}>
                  {formatCell(row[columnIndex])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length === 0 ? <p className="database-preview__muted">当前页没有数据。</p> : null}
    </div>
  );
}

function formatCell(cell: ProjectDatabaseCell | undefined) {
  if (!cell || cell.value_type === "null") return <span className="database-preview__null">NULL</span>;
  if (cell.value_type === "blob") return <span className="database-preview__blob">BLOB {formatBytes(cell.size_bytes ?? 0)}</span>;
  const text = String(cell.value ?? "");
  return text;
}

function cellTitle(cell: ProjectDatabaseCell | undefined) {
  if (!cell || cell.value_type === "null") return "NULL";
  if (cell.value_type === "blob") return `BLOB ${formatBytes(cell.size_bytes ?? 0)}`;
  return String(cell.value ?? "");
}

function formatBytes(value: number) {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  if (value < 1024 * 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`;
  return `${(value / 1024 / 1024 / 1024).toFixed(1)} GB`;
}

function quoteSqlIdentifier(identifier: string) {
  return `"${identifier.replaceAll("\"", "\"\"")}"`;
}
