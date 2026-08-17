import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowClockwise, CaretDown, CaretRight } from "@phosphor-icons/react";

import type {
  ProjectMemoryItem,
  ProjectMemoryScope,
} from "../../../entities/project-memory/model/projectMemory";
import { getProjectMemory } from "../../../services/project/projectMemory";
import { PaginationControls } from "../../../shared/ui/pagination-controls/PaginationControls";

import "./project-memory-preview.css";

type LoadState = "idle" | "loading" | "ready" | "error";

type ProjectMemoryPreviewProps = {
  projectId: string | null;
  scope: ProjectMemoryScope;
};

export function ProjectMemoryPreview({ projectId, scope }: ProjectMemoryPreviewProps) {
  const [items, setItems] = useState<ProjectMemoryItem[]>([]);
  const [state, setState] = useState<LoadState>("idle");
  const [error, setError] = useState<string | null>(null);
  const [expandedIds, setExpandedIds] = useState<Set<string>>(() => new Set());
  const [pagination, setPagination] = useState({
    page: 1,
    pageSize: 50,
    totalCount: 0,
    totalPages: 1,
  });
  const requestIdRef = useRef(0);
  const isGlobal = scope === "global";

  const load = useCallback(async (page?: number, signal?: AbortSignal) => {
    if (!projectId) {
      setItems([]);
      setState("idle");
      setError(null);
      return;
    }
    const requestId = requestIdRef.current + 1;
    requestIdRef.current = requestId;
    setState("loading");
    setError(null);
    try {
      const response = await getProjectMemory(projectId, {
        page,
        pageSize: 50,
        scope,
        signal,
      });
      if (requestIdRef.current !== requestId) return;
      setItems(response.items);
      setPagination({
        page: response.page,
        pageSize: response.page_size,
        totalCount: response.total_count,
        totalPages: response.total_pages,
      });
      setState("ready");
    } catch (err) {
      if (signal?.aborted || requestIdRef.current !== requestId) return;
      setError(err instanceof Error ? err.message : "长期记忆读取失败。");
      setState("error");
    }
  }, [projectId, scope]);

  useEffect(() => {
    const controller = new AbortController();
    void load(undefined, controller.signal);
    return () => {
      controller.abort();
      requestIdRef.current += 1;
    };
  }, [load]);

  const stats = useMemo(() => buildMemoryStats(items), [items]);

  const toggleExpanded = useCallback((itemId: string) => {
    setExpandedIds((current) => {
      const next = new Set(current);
      if (next.has(itemId)) {
        next.delete(itemId);
      } else {
        next.add(itemId);
      }
      return next;
    });
  }, []);

  const title = isGlobal ? "全局记忆看板" : "项目记忆看板";
  const fileName = isGlobal ? "global_memory.jsonl" : "project_memory.jsonl";
  const sourceLabel = isGlobal ? "全局运行数据" : "当前项目";

  return (
    <div className="project-memory-preview">
      <header className="project-memory-preview__header">
        <div>
          <h2 className="project-memory-preview__title">{title}</h2>
          <p>
            {isGlobal
              ? "跨项目共用的长期记忆，所有项目和会话读取同一份全局数据。"
              : "当前项目共用的长期记忆，同一项目内所有会话读取同一份项目数据。"}
          </p>
        </div>
        <button
          className="project-memory-preview__refresh"
          type="button"
          aria-label="刷新长期记忆"
          title="刷新"
          disabled={state === "loading" || !projectId}
          onClick={() => { void load(pagination.page); }}
        >
          <ArrowClockwise size={14} weight="bold" aria-hidden="true" />
        </button>
      </header>

      <section className="project-memory-preview__metrics" aria-label="长期记忆统计">
        <Metric label="记忆" value={pagination.totalCount} />
        <Metric label="本页" value={items.length} />
        <Metric label="本页事件" value={stats.eventCount} />
        <Metric label="新增" value={stats.addCount} />
        <Metric label="更新" value={stats.updateCount} />
        <Metric label="删除" value={stats.deleteCount} />
      </section>

      <section className="project-memory-preview__source" aria-label="数据源">
        <MetaItem label="数据源" value={fileName} />
        <MetaItem label="范围" value={sourceLabel} />
        <MetaItem label="项目 ID" value={projectId ?? "-"} />
      </section>

      {error ? <p className="project-memory-preview__error">{error}</p> : null}
      {!projectId ? <p className="project-memory-preview__empty">当前没有项目，无法读取长期记忆。</p> : null}
      {state === "loading" && items.length === 0 ? (
        <p className="project-memory-preview__empty">正在读取长期记忆。</p>
      ) : null}
      {state !== "loading" && projectId && items.length === 0 ? (
        <p className="project-memory-preview__empty">暂无{isGlobal ? "全局" : "项目"}记忆。</p>
      ) : null}

      {items.length > 0 ? (
        <>
          <PaginationControls
            isLoading={state === "loading"}
            onPageChange={(page) => load(page)}
            page={pagination.page}
            pageSize={pagination.pageSize}
            totalCount={pagination.totalCount}
            totalPages={pagination.totalPages}
          />
          <section className="project-memory-preview__list" aria-label="长期记忆列表">
            {items.map((item, index) => {
              const isExpanded = expandedIds.has(item.id);
              return (
                <MemoryRecord
                  index={(pagination.page - 1) * pagination.pageSize + index + 1}
                  isExpanded={isExpanded}
                  item={item}
                  key={item.id}
                  onToggle={() => toggleExpanded(item.id)}
                />
              );
            })}
          </section>
        </>
      ) : null}
    </div>
  );
}

function MemoryRecord({
  index,
  isExpanded,
  item,
  onToggle,
}: {
  index: number;
  isExpanded: boolean;
  item: ProjectMemoryItem;
  onToggle: () => void;
}) {
  return (
    <article className="project-memory-preview__record">
      <header
        className="project-memory-preview__record-head"
        title={isExpanded ? "折叠记忆" : "展开记忆"}
        onClick={onToggle}
      >
        <h3>
          <span>No. {index}</span>
          <strong>{itemTitle(item)}</strong>
        </h3>
        <div className="project-memory-preview__record-actions">
          <span>{operationLabel(item.last_operation)}</span>
          <span>{item.event_count} 事件</span>
          <button
            className="project-memory-preview__toggle"
            type="button"
            aria-label={isExpanded ? "折叠记忆" : "展开记忆"}
            aria-expanded={isExpanded}
            onClick={(event) => {
              event.stopPropagation();
              onToggle();
            }}
          >
            {isExpanded ? (
              <CaretDown size={14} weight="bold" aria-hidden="true" />
            ) : (
              <CaretRight size={14} weight="bold" aria-hidden="true" />
            )}
          </button>
        </div>
      </header>

      {isExpanded ? (
        <div className="project-memory-preview__record-body">
          <p>{item.content}</p>
          {item.keywords.length > 0 ? (
            <div className="project-memory-preview__keywords" aria-label="关键词">
              {item.keywords.map((keyword) => <span key={keyword}>{keyword}</span>)}
            </div>
          ) : null}
          <dl className="project-memory-preview__meta-grid">
            <MetaItem label="记忆 ID" value={item.id} />
            <MetaItem label="创建时间" value={formatTime(item.created_at)} />
            <MetaItem label="更新时间" value={formatTime(item.updated_at)} />
            <MetaItem label="来源" value={item.source} />
          </dl>
          {item.events.length > 0 ? (
            <div className="project-memory-preview__events">
              <h4>最近事件</h4>
              {item.events.map((event, eventIndex) => (
                <div className="project-memory-preview__event" key={`${event.memory_id}-${event.created_at}-${eventIndex}`}>
                  <span>{operationLabel(event.operation)}</span>
                  <time>{formatTime(event.created_at)}</time>
                  <p>{event.reason || "无原因说明"}</p>
                  {event.source ? <small>{event.source}</small> : null}
                </div>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}
    </article>
  );
}

function Metric({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="project-memory-preview__metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function MetaItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="project-memory-preview__meta">
      <dt>{label}</dt>
      <dd>{value || "-"}</dd>
    </div>
  );
}

function buildMemoryStats(items: ProjectMemoryItem[]) {
  const events = items.flatMap((item) => item.events);
  return {
    addCount: events.filter((event) => event.operation === "add").length,
    deleteCount: events.filter((event) => event.operation === "delete").length,
    eventCount: items.reduce((total, item) => total + item.event_count, 0),
    updateCount: events.filter((event) => event.operation === "update").length,
  };
}

function itemTitle(item: ProjectMemoryItem) {
  const firstLine = item.content.split(/\r?\n/).map((line) => line.trim()).find(Boolean) ?? "";
  if (!firstLine) return item.id;
  return firstLine;
}

function operationLabel(operation: string) {
  if (operation === "add") return "新增";
  if (operation === "update") return "更新";
  if (operation === "delete") return "删除";
  return operation || "-";
}

function formatTime(value: string) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}
