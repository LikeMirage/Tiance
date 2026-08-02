import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowClockwise, CaretDown, CaretRight } from "@phosphor-icons/react";

import type {
  ToolCallRecord,
  ToolCallRecordListResponse,
} from "../../../entities/tool/model/toolCallRecord";
import { getToolFolderCallRecords } from "../../../services/tools/toolCallRecords";
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
  const targetKey = `${toolsetId}:${folderId}`;
  const activeTargetKeyRef = useRef(targetKey);
  const requestIdRef = useRef(0);
  const [state, setState] = useState<LoadState>("loading");
  const [report, setReport] = useState<ToolCallRecordListResponse | null>(null);
  const [expandedRecordId, setExpandedRecordId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    activeTargetKeyRef.current = targetKey;
    requestIdRef.current += 1;
    setReport(null);
    setExpandedRecordId(null);
    setError(null);
  }, [targetKey]);

  const loadRecords = useCallback(async (signal?: AbortSignal) => {
    const requestId = requestIdRef.current + 1;
    requestIdRef.current = requestId;
    setState("loading");
    setError(null);
    try {
      const nextReport = await getToolFolderCallRecords(toolsetId, folderId, {
        signal,
      });
      if (activeTargetKeyRef.current !== targetKey || requestIdRef.current !== requestId) return;
      setReport(nextReport);
      setState("ready");
    } catch (err) {
      if (signal?.aborted || activeTargetKeyRef.current !== targetKey || requestIdRef.current !== requestId) return;
      setError(err instanceof Error ? err.message : "调用记录读取失败。");
      setState("error");
    }
  }, [folderId, targetKey, toolsetId]);

  useEffect(() => {
    const controller = new AbortController();
    void loadRecords(controller.signal);
    return () => {
      controller.abort();
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
        {state !== "loading" && records.length === 0 ? (
          <div className="tool-call-records-dashboard__empty">暂无调用记录。</div>
        ) : null}
        {records.map((record) => (
          <CallRecordRow
            isExpanded={expandedRecordId === record.record_id}
            key={record.record_id}
            record={record}
            onToggle={() => setExpandedRecordId((current) =>
              current === record.record_id ? null : record.record_id,
            )}
          />
        ))}
      </section>
    </article>
  );
}

function CallRecordRow({
  isExpanded,
  onToggle,
  record,
}: {
  isExpanded: boolean;
  onToggle: () => void;
  record: ToolCallRecord;
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
        <div className="tool-call-records-dashboard__detail">
          <DetailBlock title="调用指令" text={formatCallInstruction(record)} />
          <DetailBlock title="调用结果" text={formatJsonLike(record.result_text)} />
          {record.error ? <DetailBlock title="错误信息" text={record.error} /> : null}
        </div>
      ) : null}
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
