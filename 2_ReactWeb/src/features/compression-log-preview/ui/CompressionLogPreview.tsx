import { useCallback, useMemo, useState } from "react";
import { CaretDown, CaretRight } from "@phosphor-icons/react";

import { formatTokenCount } from "../../../shared/model/usageFormatting";
import { estimateJsonTokens } from "../../../services/llm/tokenEstimationSettings";
import {
  compressionRatioPercent,
  formatProviderModel,
  formatSource,
  formatTime,
  parseCompressionLog,
  type CompressionItem,
  type CompressionRecord,
  type JsonRecord,
  type ParsedCompressionLine,
} from "../model/compressionLogParser";
import "./compression-log-preview.css";

type CompressionLogPreviewProps = {
  content: string;
  tabId: string;
  onMarkDirty: (id: string) => void;
  onSaveContent: (contentSnapshot: string) => Promise<boolean>;
  onUpdateContent: (id: string, content: string) => void;
};

type ItemDraft = {
  content: string;
  keywords: string;
};

type ItemEditKey = `${number}:${number}`;

type ItemEditState = {
  error: string | null;
  key: ItemEditKey | null;
  saving: boolean;
};

type CompressionRecordLifecycle =
  | "active"
  | "superseded"
  | "running"
  | "pending"
  | "failed"
  | "unknown";

export function CompressionLogPreview({
  content,
  onMarkDirty,
  onSaveContent,
  onUpdateContent,
  tabId,
}: CompressionLogPreviewProps) {
  const parseResult = useMemo(() => parseCompressionLog(content), [content]);
  const [itemDraft, setItemDraft] = useState<ItemDraft>({ content: "", keywords: "" });
  const [itemEditState, setItemEditState] = useState<ItemEditState>({
    error: null,
    key: null,
    saving: false,
  });
  const [expandedRecordKeys, setExpandedRecordKeys] = useState<Set<string>>(() => new Set());
  const { parsedLines, totalLineCount } = parseResult;
  const records = parsedLines
    .filter((line): line is Extract<ParsedCompressionLine, { kind: "record" }> =>
      line.kind === "record",
    )
    .map((line) => line.record);
  const errors = parsedLines.filter((line) => line.kind === "error");
  const completedCount = records.filter((record) => record.status === "completed").length;
  const failedCount = records.filter((record) => record.status === "failed").length;
  const runningCount = records.filter(
    (record) => record.status === "pending" || record.status === "running",
  ).length;
  const activeRecord = [...records].reverse().find((record) => record.status === "completed");
  const displayRecords = [...records].reverse();
  const activeItemCount = activeRecord?.items.length ?? 0;
  const activeSourceCount = activeRecord
    ? activeRecord.sourceMessageCount || activeRecord.sourceMessageIds.length
    : 0;
  const historicalResultCount = Math.max(0, completedCount - (activeRecord ? 1 : 0));

  const startItemEdit = useCallback((record: CompressionRecord, itemIndex: number) => {
    const item = record.items[itemIndex];
    if (!item) return;
    setItemDraft({
      content: item.content,
      keywords: item.keywords.join("，"),
    });
    setItemEditState({
      error: null,
      key: itemEditKey(record, itemIndex),
      saving: false,
    });
  }, []);

  const cancelItemEdit = useCallback(() => {
    setItemDraft({ content: "", keywords: "" });
    setItemEditState({ error: null, key: null, saving: false });
  }, []);

  const toggleRecordExpanded = useCallback((record: CompressionRecord) => {
    const key = recordCollapseKey(record);
    setExpandedRecordKeys((current) => {
      const next = new Set(current);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  }, []);

  const saveItemEdit = useCallback(async (record: CompressionRecord, itemIndex: number) => {
    const key = itemEditKey(record, itemIndex);
    if (!itemDraft.content.trim()) {
      setItemEditState({ error: "压缩事项内容不能为空。", key, saving: false });
      return;
    }
    setItemEditState({ error: null, key, saving: true });
    try {
      const nextContent = await updateCompressionItemInContent(
        content,
        record.lineNumber,
        itemIndex,
        {
          content: itemDraft.content.trim(),
          keywords: keywordsFromDraft(itemDraft.keywords),
        },
      );
      onUpdateContent(tabId, nextContent);
      onMarkDirty(tabId);
      const saved = await onSaveContent(nextContent);
      if (!saved) {
        setItemEditState({ error: "保存压缩记录失败。", key, saving: false });
        return;
      }
      setItemDraft({ content: "", keywords: "" });
      setItemEditState({ error: null, key: null, saving: false });
    } catch (err) {
      setItemEditState({
        error: err instanceof Error ? err.message : "更新压缩事项失败。",
        key,
        saving: false,
      });
    }
  }, [content, itemDraft, onMarkDirty, onSaveContent, onUpdateContent, tabId]);

  if (!content.trim()) {
    return (
      <div className="compression-log-preview compression-log-preview--empty">
        <p>当前压缩日志为空。</p>
      </div>
    );
  }

  return (
    <div className="compression-log-preview">
      <header className="compression-log-preview__header">
        <h2 className="compression-log-preview__title">记忆压缩记录</h2>
        <div className="compression-log-preview__metrics" aria-label="压缩日志统计">
          <Metric label="记录" value={totalLineCount} />
          <Metric label="当前覆盖" value={activeSourceCount} />
          <Metric label="当前事项" value={activeItemCount} />
          {historicalResultCount > 0 ? (
            <Metric label="历史结果" value={historicalResultCount} />
          ) : null}
          {runningCount > 0 ? <Metric label="进行中" value={runningCount} /> : null}
          {failedCount > 0 ? <Metric label="失败" tone="danger" value={failedCount} /> : null}
          {errors.length > 0 ? <Metric label="解析失败" tone="danger" value={errors.length} /> : null}
        </div>
      </header>

      {errors.length > 0 ? (
        <section className="compression-log-preview__errors" aria-label="解析失败行">
          {errors.map((error) => (
            <div key={`error-${error.lineNumber}`} className="compression-log-preview__error">
              <strong>第 {error.lineNumber} 行解析失败</strong>
              <span>{error.message}</span>
            </div>
          ))}
        </section>
      ) : null}

      <div className="compression-log-preview__list">
        {displayRecords.map((record) => {
          const recordKey = recordCollapseKey(record);
          const isCollapsed = !expandedRecordKeys.has(recordKey);
          const lifecycle = resolveRecordLifecycle(record, activeRecord);
          return (
            <article
              key={recordKey}
              className={[
                "compression-log-preview__record",
                `compression-log-preview__record--${lifecycle}`,
                isCollapsed ? "compression-log-preview__record--collapsed" : "",
              ].filter(Boolean).join(" ")}
            >
              <header
                className="compression-log-preview__record-head"
                title={isCollapsed ? "展开压缩记录" : "折叠压缩记录"}
                onClick={() => toggleRecordExpanded(record)}
              >
                <div className="compression-log-preview__record-title-block">
                  <h3 className="compression-log-preview__record-title">
                    <span className="compression-log-preview__record-index">No. {record.lineNumber}</span>
                    <span>{recordLifecycleTitle(lifecycle)}</span>
                  </h3>
                </div>
                <div className="compression-log-preview__record-controls">
                  <span className="compression-log-preview__record-source">{formatSource(record)}</span>
                  <dl className="compression-log-preview__record-facts" aria-label="压缩记录属性">
                    <div className={`compression-log-preview__record-fact--${lifecycle}`}>
                      <dt>状态</dt>
                      <dd>{recordLifecycleLabel(lifecycle)}</dd>
                    </div>
                    <div>
                      <dt>模式</dt>
                      <dd>{record.mode === "session" ? "缓存优化" : "选定模型"}</dd>
                    </div>
                  </dl>
                  <button
                    className="compression-log-preview__record-toggle"
                    type="button"
                    aria-label={isCollapsed ? "展开压缩记录" : "折叠压缩记录"}
                    aria-expanded={!isCollapsed}
                    title={isCollapsed ? "展开" : "折叠"}
                    onClick={(event) => {
                      event.stopPropagation();
                      toggleRecordExpanded(record);
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
                  <dl className="compression-log-preview__meta">
                    <MetaItem label="模型" value={formatProviderModel(record.providerId, record.modelId)} />
                    <MetaItem label="覆盖原文" value={String(record.sourceMessageCount || record.sourceMessageIds.length)} />
                    <MetaItem label="本次吸收" value={String(record.newlyCoveredMessageCount)} />
                    <MetaItem label="任务会话" value={record.functionSessionId || "-"} />
                    <MetaItem label="创建" value={formatTime(record.createdAt)} />
                    <MetaItem label="完成" value={formatTime(record.completedAt)} />
                    <MetaItem highlight label="原文" value={`${formatTokenCount(record.sourceTokenCount)} tokens`} />
                    <MetaItem highlight label="压缩后" value={`${formatTokenCount(record.compressedTokenCount)} tokens`} />
                    <MetaItem
                      highlight
                      label="比例"
                      tone={compressionRatioTone(record.compressionRatio)}
                      value={formatCompressionRatio(record.compressionRatio)}
                    />
                  </dl>

                  {record.status === "failed" ? (
                    <CompressionFailureView record={record} />
                  ) : (
                    <>
                      <CompressionItemsView
                        draft={itemDraft}
                        editState={itemEditState}
                        items={record.items}
                        record={record}
                        onCancelEdit={cancelItemEdit}
                        onDraftChange={setItemDraft}
                        onSaveEdit={saveItemEdit}
                        onStartEdit={startItemEdit}
                      />
                      <CompressionHandoffView handoff={record.handoff} />
                    </>
                  )}

                  <RawJsonDetails raw={record.raw} />
                </>
              ) : null}
            </article>
          );
        })}
      </div>
    </div>
  );
}

function resolveRecordLifecycle(
  record: CompressionRecord,
  activeRecord: CompressionRecord | undefined,
): CompressionRecordLifecycle {
  if (record.status === "failed") return "failed";
  if (record.status === "running") return "running";
  if (record.status === "pending") return "pending";
  if (record.status === "completed") {
    return record === activeRecord ? "active" : "superseded";
  }
  return "unknown";
}

function recordLifecycleLabel(lifecycle: CompressionRecordLifecycle) {
  if (lifecycle === "active") return "生效中";
  if (lifecycle === "superseded") return "已替代";
  if (lifecycle === "running") return "压缩中";
  if (lifecycle === "pending") return "等待中";
  if (lifecycle === "failed") return "失败";
  return "未知";
}

function recordLifecycleTitle(lifecycle: CompressionRecordLifecycle) {
  if (lifecycle === "active") return "当前摘要";
  if (lifecycle === "superseded") return "历史压缩结果";
  if (lifecycle === "running") return "正在压缩";
  if (lifecycle === "pending") return "等待压缩";
  if (lifecycle === "failed") return "压缩失败";
  return "记忆压缩记录";
}

function CompressionFailureView({ record }: { record: CompressionRecord }) {
  const failure = record.failure;
  return (
    <section className="compression-log-preview__failure" aria-label="压缩失败原因">
      <header className="compression-log-preview__section-head">
        <h4>压缩失败</h4>
        <span>{failure?.stage || "-"}</span>
      </header>
      <dl>
        <div>
          <dt>原因</dt>
          <dd>{failure?.reason || "-"}</dd>
        </div>
        <div>
          <dt>说明</dt>
          <dd>{failure?.message || "没有返回失败说明。"}</dd>
        </div>
      </dl>
    </section>
  );
}

function RawJsonDetails({ raw }: { raw: JsonRecord }) {
  const [isOpen, setIsOpen] = useState(false);
  const rawJson = useMemo(() => isOpen ? JSON.stringify(raw, null, 2) : "", [isOpen, raw]);

  return (
    <details
      className="compression-log-preview__raw"
      onToggle={(event) => setIsOpen(event.currentTarget.open)}
    >
      <summary>原始 JSON</summary>
      {isOpen ? <pre>{rawJson}</pre> : null}
    </details>
  );
}

function Metric({
  label,
  tone = "default",
  value,
}: {
  label: string;
  tone?: "danger" | "default";
  value: number;
}) {
  return (
    <div className={`compression-log-preview__metric compression-log-preview__metric--${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function MetaItem({
  highlight = false,
  label,
  tone = "default",
  value,
}: {
  highlight?: boolean;
  label: string;
  tone?: "bad" | "default" | "good" | "warn";
  value: string;
}) {
  const classNames = [
    "compression-log-preview__meta-item",
    highlight ? "compression-log-preview__meta-item--highlight" : "",
    tone !== "default" ? `compression-log-preview__meta-item--${tone}` : "",
  ].filter(Boolean).join(" ");

  return (
    <div className={classNames}>
      <dt>{label}</dt>
      <dd>{value || "-"}</dd>
    </div>
  );
}

function formatCompressionRatio(value: number) {
  if (!Number.isFinite(value) || value <= 0) return "-";
  return `${value.toFixed(1).replace(/\.0$/, "")}%`;
}

function compressionRatioTone(value: number): "bad" | "default" | "good" | "warn" {
  if (!Number.isFinite(value) || value <= 0) return "default";
  if (value <= 45) return "good";
  if (value <= 80) return "warn";
  return "bad";
}

function CompressionItemsView({
  draft,
  editState,
  items,
  record,
  onCancelEdit,
  onDraftChange,
  onSaveEdit,
  onStartEdit,
}: {
  draft: ItemDraft;
  editState: ItemEditState;
  items: CompressionItem[];
  record: CompressionRecord;
  onCancelEdit: () => void;
  onDraftChange: (value: ItemDraft) => void;
  onSaveEdit: (record: CompressionRecord, itemIndex: number) => Promise<void>;
  onStartEdit: (record: CompressionRecord, itemIndex: number) => void;
}) {
  return (
    <section className="compression-log-preview__items" aria-label="压缩事项">
      <header className="compression-log-preview__section-head">
        <h4>压缩事项</h4>
        <span>{items.length} 条</span>
      </header>
      {items.length > 0 ? (
        <div className="compression-log-preview__item-list">
          {items.map((item, index) => {
            const key = itemEditKey(record, index);
            const isEditing = editState.key === key;
            return (
              <article className="compression-log-preview__item" key={`${record.compressionId}-${index}`}>
                <header className="compression-log-preview__item-head">
                  <div className="compression-log-preview__item-title">
                    <strong>事项 {index + 1}</strong>
                  </div>
                  <button
                    className="compression-log-preview__item-edit-button"
                    type="button"
                    disabled={editState.saving}
                    onClick={() => onStartEdit(record, index)}
                  >
                    编辑
                  </button>
                </header>
                {isEditing ? (
                  <div className="compression-log-preview__item-edit">
                    <textarea
                      value={draft.content}
                      disabled={editState.saving}
                      onChange={(event) => onDraftChange({ ...draft, content: event.target.value })}
                    />
                    <input
                      value={draft.keywords}
                      disabled={editState.saving}
                      placeholder="关键词，用逗号、分号或空格分隔"
                      onChange={(event) => onDraftChange({ ...draft, keywords: event.target.value })}
                    />
                    {editState.error ? <p>{editState.error}</p> : null}
                    <div className="compression-log-preview__item-edit-actions">
                      <button
                        type="button"
                        disabled={editState.saving || !draft.content.trim()}
                        onClick={() => { void onSaveEdit(record, index); }}
                      >
                        {editState.saving ? "保存中" : "保存"}
                      </button>
                      <button
                        type="button"
                        disabled={editState.saving}
                        onClick={onCancelEdit}
                      >
                        取消
                      </button>
                    </div>
                  </div>
                ) : (
                  <>
                    <p>{item.content || "无内容"}</p>
                    {item.keywords.length > 0 ? (
                      <div className="compression-log-preview__keywords" aria-label="关键词">
                        {item.keywords.map((keyword) => (
                          <span key={`${record.compressionId}-${index}-${keyword}`}>{keyword}</span>
                        ))}
                      </div>
                    ) : null}
                  </>
                )}
              </article>
            );
          })}
        </div>
      ) : (
        <p className="compression-log-preview__empty-text">无压缩事项。</p>
      )}
    </section>
  );
}

function CompressionHandoffView({ handoff }: { handoff: string }) {
  return (
    <section className="compression-log-preview__handoff" aria-label="交接总结">
      <header className="compression-log-preview__section-head">
        <h4>交接总结</h4>
      </header>
      <p className="compression-log-preview__handoff-content">
        {handoff || "无交接总结。"}
      </p>
    </section>
  );
}

function itemEditKey(record: CompressionRecord, itemIndex: number): ItemEditKey {
  return `${record.lineNumber}:${itemIndex}`;
}

function recordCollapseKey(record: CompressionRecord): string {
  return `${record.lineNumber}:${record.compressionId || record.rawLine}`;
}

async function updateCompressionItemInContent(
  content: string,
  lineNumber: number,
  itemIndex: number,
  draft: Pick<CompressionItem, "content" | "keywords">,
) {
  const newline = content.includes("\r\n") ? "\r\n" : "\n";
  const lines = content.split(/\r?\n/);
  const lineIndex = lineNumber - 1;
  const line = lines[lineIndex];
  if (!line?.trim()) {
    throw new Error("找不到对应的压缩记录行。");
  }

  const raw = JSON.parse(line) as unknown;
  if (!isRecord(raw)) {
    throw new Error("对应行不是 JSON 对象。");
  }

  const result = isRecord(raw.result) ? raw.result : {};
  const items = Array.isArray(result.items) ? [...result.items] : [];
  const currentItem = items[itemIndex];
  if (!isRecord(currentItem)) {
    throw new Error("找不到对应的压缩事项。");
  }

  const nextItems = items.map((item, index) => {
    if (index !== itemIndex || !isRecord(item)) return item;
    return {
      ...item,
      content: draft.content,
      keywords: draft.keywords,
    };
  });
  const nextResult = {
    ...result,
    items: nextItems,
  };
  const { token_count: compressedTokenCount } = await estimateJsonTokens(
    nextResult,
  );
  const sourceTokenCount = typeof raw.source_token_count === "number"
    ? raw.source_token_count
    : 0;

  raw.result = nextResult;
  raw.compressed_token_count = compressedTokenCount;
  raw.compressed_token_source = "local_estimate";
  raw.compression_ratio = compressionRatioPercent(
    sourceTokenCount,
    compressedTokenCount,
  );
  lines[lineIndex] = JSON.stringify(raw);
  return lines.join(newline);
}

function isRecord(value: unknown): value is JsonRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function keywordsFromDraft(value: string): string[] {
  return Array.from(new Set(
    value
      .split(/[\s,，;；]+/)
      .map((item) => item.trim())
      .filter(Boolean),
  ));
}
