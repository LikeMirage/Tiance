import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowClockwise, CaretDown, CaretRight } from "@phosphor-icons/react";

import type {
  ToolCallRecord,
  ToolCallRecordListItem,
  ToolCallRecordListResponse,
} from "../../../entities/tool/model/toolCallRecord";
import { getToolFolderCallRecord, getToolFolderCallRecords } from "../../../services/tools/toolCallRecords";
import "./tool-call-records-dashboard.css";

type LoadState = "loading" | "ready" | "error";

type ToolCallRecordsDashboardProps = {
  folderId: string;
  toolsetId: string;
};

export function ToolCallRecordsDashboard({
  folderId,
  toolsetId,
}: ToolCallRecordsDashboardProps) {
  return <ToolCallRecordsPage key={`${toolsetId}:${folderId}`} folderId={folderId} toolsetId={toolsetId} />;
}

function ToolCallRecordsPage({ folderId, toolsetId }: ToolCallRecordsDashboardProps) {
  const requestIdRef = useRef(0);
  const requestControllerRef = useRef<AbortController | null>(null);
  const [state, setState] = useState<LoadState>("loading");
  const [report, setReport] = useState<ToolCallRecordListResponse | null>(null);
  const [expandedRecordId, setExpandedRecordId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadRecords = useCallback(async (offset = 0, snapshot?: string | null) => {
    requestControllerRef.current?.abort();
    const controller = new AbortController();
    requestControllerRef.current = controller;
    const { signal } = controller;
    const requestId = requestIdRef.current + 1;
    requestIdRef.current = requestId;
    setState("loading");
    setError(null);
    setExpandedRecordId(null);
    try {
      const nextReport = await getToolFolderCallRecords(toolsetId, folderId, {
        signal,
        offset,
        snapshot,
      });
      if (signal.aborted || requestIdRef.current !== requestId) return;
      setReport(nextReport);
      setState("ready");
    } catch (err) {
      if (signal.aborted || requestIdRef.current !== requestId) return;
      setError(err instanceof Error ? err.message : "调用记录读取失败。");
      setState("error");
    }
  }, [folderId, toolsetId]);

  useEffect(() => {
    void loadRecords();
    return () => {
      requestControllerRef.current?.abort();
      requestIdRef.current += 1;
    };
  }, [loadRecords]);

  const records = report?.items ?? [];

  return (
    <article className="tool-call-records-dashboard">
      <header className="tool-call-records-dashboard__header">
        <div>
          <h1>调用记录</h1>
          <p>
            记录当前工具在项目对话中的真实调用。列表显示调用时间、当前项目名称和当前会话名称，点开后查看调用参数和返回结果。
          </p>
        </div>
        <button
          className="tool-call-records-dashboard__icon-button"
          type="button"
          aria-label="刷新调用记录"
          title="刷新"
          disabled={state === "loading"}
          onClick={() => { void loadRecords(); }}
        >
          <ArrowClockwise size={15} weight="bold" aria-hidden="true" />
        </button>
      </header>

      {error ? (
        <div className="tool-call-records-dashboard__notice tool-call-records-dashboard__notice--error" role="status">
          {error}
        </div>
      ) : null}

      <section className="tool-call-records-dashboard__list" aria-label="调用记录列表">
        <div className="tool-call-records-dashboard__row tool-call-records-dashboard__row--head">
          <span>时间</span>
          <span>项目</span>
          <span>会话</span>
          <span>耗时</span>
          <span>加载</span>
          <span>状态</span>
        </div>
        {state === "loading" && records.length === 0 ? (
          <div className="tool-call-records-dashboard__empty">正在读取调用记录。</div>
        ) : null}
        {state === "ready" && records.length === 0 ? (
          <div className="tool-call-records-dashboard__empty">暂无调用记录。</div>
        ) : null}
        {records.map((record) => (
          <CallRecordRow
            isExpanded={expandedRecordId === record.record_id}
            key={record.record_id}
            record={record}
            folderId={folderId}
            toolsetId={toolsetId}
            onToggle={() => setExpandedRecordId((current) =>
              current === record.record_id ? null : record.record_id,
            )}
          />
        ))}
      </section>
      {report ? (
        <nav className="tool-call-records-dashboard__pagination" aria-label="调用记录分页">
          <span aria-live="polite">
            {records.length ? `${report.offset + 1}–${report.offset + records.length} / ${report.count} 条` : `共 ${report.count} 条`}
          </span>
          <button type="button" disabled={state === "loading" || report.offset === 0}
            onClick={() => { void loadRecords(Math.max(0, report.offset - report.limit), report.snapshot); }}>
            上一页
          </button>
          <button type="button" disabled={state === "loading" || report.offset + report.limit >= report.count}
            onClick={() => { void loadRecords(report.offset + report.limit, report.snapshot); }}>
            下一页
          </button>
        </nav>
      ) : null}
    </article>
  );
}

function CallRecordRow({
  isExpanded,
  onToggle,
  record,
  folderId,
  toolsetId,
}: {
  isExpanded: boolean;
  onToggle: () => void;
  record: ToolCallRecordListItem;
  folderId: string;
  toolsetId: string;
}) {
  return (
    <div className={["tool-call-records-dashboard__record", isExpanded ? "tool-call-records-dashboard__record--expanded" : ""].filter(Boolean).join(" ")}>
      <button
        className="tool-call-records-dashboard__row tool-call-records-dashboard__row--button"
        type="button"
        aria-expanded={isExpanded}
        onClick={onToggle}
      >
        <span className="tool-call-records-dashboard__time">
          <i aria-hidden="true">
            {isExpanded ? <CaretDown size={13} weight="bold" /> : <CaretRight size={13} weight="bold" />}
          </i>
          {formatDateTime(record.created_at)}
        </span>
        <span title={record.source_project_name || undefined}>{record.source_project_name || "未关联项目"}</span>
        <span title={record.session_title || undefined}>{record.session_title || "未关联会话"}</span>
        <span>{formatDuration(record.elapsed_ms)}</span>
        <span>{dynamicLabel(record.dynamic)}</span>
        <span className={record.ok ? "tool-call-records-dashboard__status tool-call-records-dashboard__status--ok" : "tool-call-records-dashboard__status tool-call-records-dashboard__status--error"}>
          {record.ok ? "成功" : "失败"}
        </span>
      </button>

      {isExpanded ? (
        <CallRecordDetail folderId={folderId} toolsetId={toolsetId} recordId={record.record_id} />
      ) : null}
    </div>
  );
}

function CallRecordDetail({ folderId, toolsetId, recordId }: ToolCallRecordsDashboardProps & { recordId: string }) {
  const [record, setRecord] = useState<ToolCallRecord | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setError(null);
    setRecord(null);
    void getToolFolderCallRecord(toolsetId, folderId, recordId, { signal: controller.signal })
      .then((detail) => {
        if (!controller.signal.aborted) setRecord(detail);
      })
      .catch((err: unknown) => {
        if (!controller.signal.aborted) setError(err instanceof Error ? err.message : "调用详情读取失败。");
      });
    return () => controller.abort();
  }, [folderId, toolsetId, recordId, attempt]);

  return (
    <div className="tool-call-records-dashboard__detail">
      {error ? (
        <div role="status" className="tool-call-records-dashboard__notice--error">
          {error} <button type="button" onClick={() => setAttempt((current) => current + 1)}>重试</button>
        </div>
      ) : record ? (
        <>
          <DetailBlock title="调用指令" text={formatCallInstruction(record)} />
          <DetailBlock title="调用结果" text={formatJsonLike(record.result_text)} />
          {record.error ? <DetailBlock title="错误信息" text={record.error} /> : null}
        </>
      ) : <div role="status">正在读取调用详情。</div>}
    </div>
  );
}

function DetailBlock({
  text,
  title,
}: {
  text: string;
  title: string;
}) {
  return (
    <div className="tool-call-records-dashboard__detail-block">
      <span>{title}</span>
      <pre>{text || "空"}</pre>
    </div>
  );
}

function formatDateTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString([], {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function formatJsonLike(value: string) {
  try {
    return JSON.stringify(JSON.parse(value), null, 2);
  } catch {
    return value;
  }
}

function formatCallInstruction(record: ToolCallRecord) {
  return JSON.stringify({
    tool_name: record.tool_name,
    call_id: record.call_id,
    dynamic: record.dynamic,
    elapsed_ms: record.elapsed_ms,
    arguments: parseJsonOrRaw(record.arguments_text),
  }, null, 2);
}

function parseJsonOrRaw(value: string) {
  try {
    return JSON.parse(value);
  } catch {
    return value;
  }
}

function formatDuration(value: number | null) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "-";
  if (value < 1000) return `${value}ms`;
  return `${(value / 1000).toFixed(value < 10000 ? 1 : 0)}s`;
}

function dynamicLabel(value: boolean | null) {
  if (value === true) return "动态";
  if (value === false) return "完整";
  return "-";
}
