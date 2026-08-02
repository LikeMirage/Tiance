import { useCallback, useMemo, useState } from "react";
import { CaretDown, CaretRight } from "@phosphor-icons/react";

import "./conversation-messages-preview.css";

type JsonObject = Record<string, unknown>;

type ConversationMessageRecord = {
  content: string;
  contentParts: JsonObject[];
  createdAt: string;
  index: number;
  lineNumber: number;
  messageId: string;
  modelId: string;
  name: string;
  parseError: string;
  providerId: string;
  raw: JsonObject;
  role: string;
  sessionId: string;
  status: string;
  targetModelId: string;
  targetProviderId: string;
  thinkingContent: string;
  toolCallId: string;
  toolCalls: JsonObject[];
  updatedAt: string;
  usage: JsonObject;
};

type ParsedMessages = {
  invalidCount: number;
  records: ConversationMessageRecord[];
};

type ConversationMessagesPreviewProps = {
  content: string;
};

export function ConversationMessagesPreview({ content }: ConversationMessagesPreviewProps) {
  const parsed = useMemo(() => parseMessagesJsonl(content), [content]);
  const [expandedMessageKeys, setExpandedMessageKeys] = useState<Set<string>>(() => new Set());
  const validRecords = parsed.records.filter((record) => !record.parseError);
  const sessionId = firstNonEmpty(validRecords.map((record) => record.sessionId));
  const latestModel = firstNonEmpty([...validRecords].reverse().map(modelLabel));
  const totalTokens = validRecords.reduce((total, record) => total + usageTotal(record.usage), 0);

  const toggleMessageExpanded = useCallback((record: ConversationMessageRecord) => {
    const key = messageCollapseKey(record);
    setExpandedMessageKeys((current) => {
      const next = new Set(current);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  }, []);

  if (!content.trim()) {
    return (
      <div className="conversation-messages-preview conversation-messages-preview--empty">
        <p>当前消息记录为空。</p>
      </div>
    );
  }

  return (
    <div className="conversation-messages-preview">
      <header className="conversation-messages-preview__header">
        <h2 className="conversation-messages-preview__title">会话消息看板</h2>
        <div className="conversation-messages-preview__metrics" aria-label="消息统计">
          <Metric label="消息" value={validRecords.length} />
          <Metric label="用户" value={countRole(validRecords, "user")} />
          <Metric label="助手" value={countRole(validRecords, "assistant")} />
          <Metric label="工具" value={countRole(validRecords, "tool")} />
          <Metric label="Tokens" value={formatNumber(totalTokens)} />
          {parsed.invalidCount > 0 ? <Metric label="异常行" value={parsed.invalidCount} /> : null}
        </div>
      </header>

      <section className="conversation-messages-preview__request" aria-label="会话信息">
        <dl className="conversation-messages-preview__request-grid">
          <MetaItem label="会话 ID" value={sessionId} />
          <MetaItem label="最新模型" value={latestModel} />
          <MetaItem label="记录行数" value={String(parsed.records.length)} />
          <MetaItem label="最后消息时间" value={formatTime(firstNonEmpty([...validRecords].reverse().map((record) => record.createdAt)))} />
        </dl>
      </section>

      <section className="conversation-messages-preview__section" aria-label="消息列表">
        <SectionTitle count={parsed.records.length} title="消息记录" />
        {parsed.records.length > 0 ? (
          <div className="conversation-messages-preview__message-list">
            {parsed.records.map((record) => {
              const key = messageCollapseKey(record);
              const isCollapsed = !expandedMessageKeys.has(key);
              return (
                <ConversationMessageCard
                  key={key}
                  isCollapsed={isCollapsed}
                  record={record}
                  onToggle={() => toggleMessageExpanded(record)}
                />
              );
            })}
          </div>
        ) : (
          <EmptyLine text="当前文件没有可展示的消息。" />
        )}
      </section>
    </div>
  );
}

function ConversationMessageCard({
  isCollapsed,
  onToggle,
  record,
}: {
  isCollapsed: boolean;
  onToggle: () => void;
  record: ConversationMessageRecord;
}) {
  return (
    <article className={messageRecordClassName(record, isCollapsed)}>
      <header
        className="conversation-messages-preview__record-head"
        title={isCollapsed ? "展开消息" : "折叠消息"}
        onClick={onToggle}
      >
        <div className="conversation-messages-preview__record-title-block">
          <h3 className="conversation-messages-preview__record-title">
            <span className="conversation-messages-preview__record-index">No. {record.index}</span>
            <span>{messageTitle(record)}</span>
          </h3>
        </div>
        <div className="conversation-messages-preview__record-controls">
          <span className="conversation-messages-preview__record-source">
            {record.parseError ? `第 ${record.lineNumber} 行` : formatTime(record.createdAt)}
          </span>
          <dl className="conversation-messages-preview__record-facts" aria-label="消息属性">
            <div>
              <dt>角色</dt>
              <dd>{messageRoleLabel(record.role)}</dd>
            </div>
            {record.status ? (
              <div>
                <dt>状态</dt>
                <dd>{record.status}</dd>
              </div>
            ) : null}
            {usageTotal(record.usage) > 0 ? (
              <div>
                <dt>Tokens</dt>
                <dd>{formatNumber(usageTotal(record.usage))}</dd>
              </div>
            ) : null}
          </dl>
          <button
            className="conversation-messages-preview__record-toggle"
            type="button"
            aria-label={isCollapsed ? "展开消息" : "折叠消息"}
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
          {record.parseError ? (
            <div className="conversation-messages-preview__error-line">{record.parseError}</div>
          ) : (
            <MessageMetaGrid record={record} />
          )}
          {record.content ? <pre>{record.content}</pre> : <EmptyLine text="这条消息没有文本内容。" />}
          {record.thinkingContent ? <LazyJsonDetails label="查看思考内容" value={record.thinkingContent} /> : null}
          {record.toolCalls.length > 0 ? <LazyJsonDetails label="查看工具调用" value={record.toolCalls} /> : null}
          {record.contentParts.length > 0 ? <LazyJsonDetails label="查看多模态内容" value={record.contentParts} /> : null}
          {Object.keys(record.usage).length > 0 ? <LazyJsonDetails label="查看用量明细" value={record.usage} /> : null}
          <LazyJsonDetails label="查看原始 JSON" value={record.raw} />
        </>
      ) : null}
    </article>
  );
}

function MessageMetaGrid({ record }: { record: ConversationMessageRecord }) {
  return (
    <dl className="conversation-messages-preview__meta-grid">
      <MetaItem label="消息 ID" value={record.messageId} />
      <MetaItem label="会话 ID" value={record.sessionId} />
      <MetaItem label="模型" value={modelLabel(record)} />
      <MetaItem label="创建时间" value={formatTime(record.createdAt)} />
      <MetaItem label="更新时间" value={formatTime(record.updatedAt)} />
      <MetaItem label="工具名" value={record.name} />
      <MetaItem label="工具调用 ID" value={record.toolCallId} />
    </dl>
  );
}

function LazyJsonDetails({ label, value }: { label: string; value: unknown }) {
  const [isOpen, setIsOpen] = useState(false);
  const jsonText = useMemo(() => isOpen ? stringifyValue(value) : "", [isOpen, value]);

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

function SectionTitle({ count, title }: { count: number; title: string }) {
  return (
    <header className="conversation-messages-preview__section-title">
      <h2>{title}</h2>
      <span>{count} 条</span>
    </header>
  );
}

function Metric({ label, value }: { label: number | string; value: number | string }) {
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
      <dd>{value || "-"}</dd>
    </div>
  );
}

function EmptyLine({ text }: { text: string }) {
  return <p className="conversation-messages-preview__empty-line">{text}</p>;
}

function parseMessagesJsonl(content: string): ParsedMessages {
  const records: ConversationMessageRecord[] = [];
  let invalidCount = 0;

  content.split(/\r?\n/).forEach((line, lineIndex) => {
    const trimmed = line.trim();
    if (!trimmed) return;
    try {
      const raw = JSON.parse(trimmed) as unknown;
      if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
        invalidCount += 1;
        records.push(toInvalidRecord(records.length + 1, lineIndex + 1, trimmed, "这一行不是 JSON 对象。"));
        return;
      }
      records.push(toMessageRecord(records.length + 1, lineIndex + 1, raw as JsonObject));
    } catch (error) {
      invalidCount += 1;
      records.push(toInvalidRecord(records.length + 1, lineIndex + 1, trimmed, errorMessage(error)));
    }
  });

  return { invalidCount, records };
}

function toMessageRecord(index: number, lineNumber: number, raw: JsonObject): ConversationMessageRecord {
  return {
    content: contentText(raw.content),
    contentParts: arrayValue(raw.content_parts).map(objectValue),
    createdAt: stringValue(raw.created_at),
    index,
    lineNumber,
    messageId: stringValue(raw.message_id),
    modelId: stringValue(raw.model_id),
    name: stringValue(raw.name),
    parseError: "",
    providerId: stringValue(raw.provider_id),
    raw,
    role: stringValue(raw.role) || "unknown",
    sessionId: stringValue(raw.session_id),
    status: stringValue(raw.status),
    targetModelId: stringValue(raw.target_model_id),
    targetProviderId: stringValue(raw.target_provider_id),
    thinkingContent: contentText(raw.thinking_content),
    toolCallId: stringValue(raw.tool_call_id),
    toolCalls: arrayValue(raw.tool_calls).map(objectValue),
    updatedAt: stringValue(raw.updated_at),
    usage: objectValue(raw.usage),
  };
}

function toInvalidRecord(index: number, lineNumber: number, content: string, parseError: string): ConversationMessageRecord {
  return {
    content,
    contentParts: [],
    createdAt: "",
    index,
    lineNumber,
    messageId: "",
    modelId: "",
    name: "",
    parseError,
    providerId: "",
    raw: { line: content },
    role: "invalid",
    sessionId: "",
    status: "",
    targetModelId: "",
    targetProviderId: "",
    thinkingContent: "",
    toolCallId: "",
    toolCalls: [],
    updatedAt: "",
    usage: {},
  };
}

function messageRecordClassName(record: ConversationMessageRecord, isCollapsed: boolean): string {
  const classNames = ["conversation-messages-preview__record"];
  if (isCollapsed) classNames.push("conversation-messages-preview__record--collapsed");
  if (record.parseError) {
    classNames.push("conversation-messages-preview__record--invalid");
  } else if (record.role === "tool") {
    classNames.push("conversation-messages-preview__record--tool-result");
  } else if (record.role === "assistant" && record.toolCalls.length > 0) {
    classNames.push("conversation-messages-preview__record--tool-call");
  } else if (record.role === "user") {
    classNames.push("conversation-messages-preview__record--user");
  } else if (record.role === "assistant") {
    classNames.push("conversation-messages-preview__record--assistant");
  }
  return classNames.join(" ");
}

function messageTitle(record: ConversationMessageRecord): string {
  if (record.parseError) return "无法解析的 JSONL 行";
  const content = firstLine(record.content);
  if (content) return content;
  if (record.toolCalls.length > 0) return "工具调用";
  if (record.role === "tool") return record.name ? `${record.name} 返回结果` : "工具返回结果";
  if (record.contentParts.length > 0) return "多模态消息";
  return `${messageRoleLabel(record.role)} 消息`;
}

function messageCollapseKey(record: ConversationMessageRecord): string {
  return `${record.lineNumber}:${record.messageId || ""}:${record.role}:${record.toolCallId || ""}`;
}

function modelLabel(record: ConversationMessageRecord): string {
  const provider = record.providerId || record.targetProviderId;
  const model = record.modelId || record.targetModelId;
  return [provider, model].filter(Boolean).join(" / ");
}

function countRole(records: ConversationMessageRecord[], role: string): number {
  return records.filter((record) => record.role === role).length;
}

function usageTotal(usage: JsonObject): number {
  const total = numberValue(usage.total_tokens);
  if (total > 0) return total;
  return numberValue(usage.prompt_tokens) + numberValue(usage.completion_tokens) + numberValue(usage.reasoning_tokens);
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

function contentText(value: unknown): string {
  if (typeof value === "string") return value;
  if (value === null || value === undefined) return "";
  return stringifyValue(value);
}

function stringifyValue(value: unknown): string {
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function firstLine(value: string): string {
  return value.trim().split(/\r?\n/, 1)[0]?.trim() || "";
}

function firstNonEmpty(values: string[]): string {
  return values.find((value) => value.trim()) || "";
}

function messageRoleLabel(role: string): string {
  if (role === "system") return "system";
  if (role === "user") return "user";
  if (role === "assistant") return "assistant";
  if (role === "tool") return "tool";
  if (role === "invalid") return "异常";
  return role || "unknown";
}

function formatNumber(value: number): string {
  return Number.isFinite(value) ? value.toLocaleString("zh-CN") : "0";
}

function formatTime(value: string): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", { hour12: false });
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "JSON 解析失败。";
}
