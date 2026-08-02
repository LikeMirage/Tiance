import { useMemo, useState } from "react";
import { CaretDown, CaretRight } from "@phosphor-icons/react";

import "../../conversation-messages-preview/ui/conversation-messages-preview.css";

type JsonObject = Record<string, unknown>;

type SessionIndexRecord = {
  draft: string;
  isActive: boolean;
  messageCount: number;
  raw: JsonObject;
  runtimeStatus: string;
  sequenceNumber: string;
  sessionId: string;
  stateRaw: JsonObject;
  title: string;
  updatedAt: string;
};

type ConversationIndexPreviewProps = {
  content: string;
};

export function ConversationIndexPreview({ content }: ConversationIndexPreviewProps) {
  const parsed = useMemo(() => parseIndex(content), [content]);
  const [expandedSessionIds, setExpandedSessionIds] = useState<Set<string>>(() => new Set());

  if (!content.trim()) {
    return (
      <div className="conversation-messages-preview conversation-messages-preview--empty">
        <p>当前会话索引为空。</p>
      </div>
    );
  }

  if (!parsed.ok) {
    return (
      <div className="conversation-messages-preview conversation-messages-preview--empty">
        <p>{parsed.error}</p>
      </div>
    );
  }

  const records = parsed.records;
  const activeRecord = records.find((record) => record.isActive);
  const totalMessages = records.reduce((total, record) => total + record.messageCount, 0);

  const toggleSession = (record: SessionIndexRecord) => {
    setExpandedSessionIds((current) => {
      const next = new Set(current);
      if (next.has(record.sessionId)) {
        next.delete(record.sessionId);
      } else {
        next.add(record.sessionId);
      }
      return next;
    });
  };

  return (
    <div className="conversation-messages-preview">
      <header className="conversation-messages-preview__header">
        <h2 className="conversation-messages-preview__title">会话索引看板</h2>
        <div className="conversation-messages-preview__metrics" aria-label="会话索引统计">
          <Metric label="会话" value={records.length} />
          <Metric label="消息" value={totalMessages} />
          <Metric label="活动" value={activeRecord ? activeRecord.sequenceNumber || "1" : "-"} />
          <Metric label="运行中" value={records.filter((record) => record.runtimeStatus !== "idle").length} />
        </div>
      </header>

      <section className="conversation-messages-preview__request" aria-label="索引信息">
        <dl className="conversation-messages-preview__request-grid">
          <MetaItem label="活动会话" value={parsed.activeSessionId} />
          <MetaItem label="活动标题" value={activeRecord?.title || ""} />
          <MetaItem label="活动状态" value={activeRecord?.runtimeStatus || ""} />
          <MetaItem label="最后更新时间" value={formatTime(firstNonEmpty(records.map((record) => record.updatedAt).reverse()))} />
        </dl>
      </section>

      <section className="conversation-messages-preview__section" aria-label="会话列表">
        <SectionTitle count={records.length} title="会话列表" />
        {records.length > 0 ? (
          <div className="conversation-messages-preview__message-list">
            {records.map((record, index) => {
              const isCollapsed = !expandedSessionIds.has(record.sessionId);
              return (
                <SessionIndexCard
                  key={record.sessionId || String(index)}
                  index={index + 1}
                  isCollapsed={isCollapsed}
                  record={record}
                  onToggle={() => toggleSession(record)}
                />
              );
            })}
          </div>
        ) : (
          <EmptyLine text="当前索引没有会话。" />
        )}
      </section>
    </div>
  );
}

function SessionIndexCard({
  index,
  isCollapsed,
  onToggle,
  record,
}: {
  index: number;
  isCollapsed: boolean;
  onToggle: () => void;
  record: SessionIndexRecord;
}) {
  return (
    <article className={sessionRecordClassName(record, isCollapsed)}>
      <header
        className="conversation-messages-preview__record-head"
        title={isCollapsed ? "展开会话索引" : "折叠会话索引"}
        onClick={onToggle}
      >
        <div className="conversation-messages-preview__record-title-block">
          <h3 className="conversation-messages-preview__record-title">
            <span className="conversation-messages-preview__record-index">No. {record.sequenceNumber || index}</span>
            <span>{record.title || "未命名会话"}</span>
          </h3>
        </div>
        <div className="conversation-messages-preview__record-controls">
          <span className="conversation-messages-preview__record-source">{formatTime(record.updatedAt)}</span>
          <dl className="conversation-messages-preview__record-facts" aria-label="会话索引属性">
            <div>
              <dt>消息</dt>
              <dd>{record.messageCount}</dd>
            </div>
            <div>
              <dt>状态</dt>
              <dd>{record.runtimeStatus || "-"}</dd>
            </div>
            {record.isActive ? (
              <div>
                <dt>当前</dt>
                <dd>是</dd>
              </div>
            ) : null}
          </dl>
          <button
            className="conversation-messages-preview__record-toggle"
            type="button"
            aria-label={isCollapsed ? "展开会话索引" : "折叠会话索引"}
            aria-expanded={!isCollapsed}
            title={isCollapsed ? "展开" : "折叠"}
            onClick={(event) => {
              event.stopPropagation();
              onToggle();
            }}
          >
            {isCollapsed ? (
              <CaretRight size={14} weight="bold" aria-hidden="true" />
            ) : (
              <CaretDown size={14} weight="bold" aria-hidden="true" />
            )}
          </button>
        </div>
      </header>

      {!isCollapsed ? (
        <>
          <dl className="conversation-messages-preview__meta-grid">
            <MetaItem label="会话 ID" value={record.sessionId} />
            <MetaItem label="标题" value={record.title} />
            <MetaItem label="序号" value={record.sequenceNumber} />
            <MetaItem label="消息数量" value={String(record.messageCount)} />
            <MetaItem label="运行状态" value={record.runtimeStatus} />
            <MetaItem label="草稿" value={record.draft ? "有内容" : "空"} />
            <MetaItem label="更新时间" value={formatTime(record.updatedAt)} />
          </dl>
          <LazyJsonDetails label="查看会话索引 JSON" value={record.raw} />
          {Object.keys(record.stateRaw).length > 0 ? <LazyJsonDetails label="查看会话状态 JSON" value={record.stateRaw} /> : null}
        </>
      ) : null}
    </article>
  );
}

function LazyJsonDetails({ label, value }: { label: string; value: unknown }) {
  const [isOpen, setIsOpen] = useState(false);
  const jsonText = useMemo(() => isOpen ? JSON.stringify(value, null, 2) : "", [isOpen, value]);

  return (
    <details
      className="conversation-messages-preview__raw"
      onToggle={(event) => setIsOpen(event.currentTarget.open)}
    >
      <summary>{label}</summary>
      {isOpen ? <pre>{jsonText}</pre> : null}
    </details>
  );
}

function parseIndex(content: string):
  | { ok: true; activeSessionId: string; records: SessionIndexRecord[] }
  | { ok: false; error: string } {
  try {
    const value = JSON.parse(content) as unknown;
    if (!value || typeof value !== "object" || Array.isArray(value)) {
      return { ok: false, error: "index.json 必须是 JSON 对象。" };
    }
    const index = value as JsonObject;
    const activeSessionId = stringValue(index.active_session_id);
    const states = objectValue(index.session_states);
    return {
      ok: true,
      activeSessionId,
      records: arrayValue(index.sessions)
        .map((session) => toSessionRecord(session, states, activeSessionId))
        .filter((record): record is SessionIndexRecord => record !== null),
    };
  } catch {
    return { ok: false, error: "index.json 不是有效 JSON。" };
  }
}

function toSessionRecord(value: unknown, states: JsonObject, activeSessionId: string): SessionIndexRecord | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const raw = value as JsonObject;
  const sessionId = stringValue(raw.session_id);
  const stateRaw = objectValue(states[sessionId]);
  return {
    draft: stringValue(stateRaw.draft),
    isActive: sessionId === activeSessionId,
    messageCount: numberValue(raw.message_count),
    raw,
    runtimeStatus: stringValue(stateRaw.runtime_status) || "-",
    sequenceNumber: stringValue(raw.sequence_number),
    sessionId,
    stateRaw,
    title: stringValue(raw.title),
    updatedAt: stringValue(stateRaw.updated_at) || stringValue(raw.updated_at),
  };
}

function sessionRecordClassName(record: SessionIndexRecord, isCollapsed: boolean): string {
  const classNames = ["conversation-messages-preview__record"];
  if (isCollapsed) classNames.push("conversation-messages-preview__record--collapsed");
  if (record.isActive) classNames.push("conversation-messages-preview__record--user");
  if (record.runtimeStatus && record.runtimeStatus !== "idle" && record.runtimeStatus !== "-") {
    classNames.push("conversation-messages-preview__record--tool-call");
  }
  return classNames.join(" ");
}

function SectionTitle({ count, title }: { count: number; title: string }) {
  return (
    <header className="conversation-messages-preview__section-title">
      <h2>{title}</h2>
      <span>{count} 条</span>
    </header>
  );
}

function Metric({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="conversation-messages-preview__metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function MetaItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="conversation-messages-preview__meta">
      <dt>{label}</dt>
      <dd title={value || "-"}>{value || "-"}</dd>
    </div>
  );
}

function EmptyLine({ text }: { text: string }) {
  return <p className="conversation-messages-preview__empty-line">{text}</p>;
}

function objectValue(value: unknown): JsonObject {
  return value && typeof value === "object" && !Array.isArray(value) ? value as JsonObject : {};
}

function arrayValue(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function stringValue(value: unknown): string {
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return "";
}

function numberValue(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function firstNonEmpty(values: string[]): string {
  return values.find((value) => value.trim()) || "";
}

function formatTime(value: string): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", { hour12: false });
}
