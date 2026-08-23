import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowClockwise,
  Check,
  PencilSimple,
  Plus,
  Trash,
  X,
} from "@phosphor-icons/react";

import type {
  GlobalMemoryEvent,
  GlobalMemoryRecord,
  GlobalMemoryRecordStatus,
} from "../../../entities/global-memory/model/globalMemory";
import {
  applyGlobalMemoryOperation,
  getGlobalMemoryEvents,
  getGlobalMemoryRecords,
} from "../../../services/memory/globalMemory";
import { useI18n, type TranslationKey } from "../../../shared/i18n";
import { PaginationControls } from "../../../shared/ui/pagination-controls/PaginationControls";
import { SettingsViewStage } from "../../../shared/ui/settings-view-tabs/SettingsViewStage";
import { SettingsViewTabs } from "../../../shared/ui/settings-view-tabs/SettingsViewTabs";

import "./global-memory-settings.css";

type GlobalMemoryView = GlobalMemoryRecordStatus | "events";
type LoadState = "idle" | "loading" | "ready" | "error";
type DraftState = { content: string; keywords: string; reason: string };

const EMPTY_DRAFT: DraftState = { content: "", keywords: "", reason: "" };
const PAGE_SIZE = 50;
const GLOBAL_MEMORY_VIEW_ORDER: readonly GlobalMemoryView[] = ["active", "deleted", "events"];

export function GlobalMemorySettingsPanel({ onReady }: { onReady?: () => void }) {
  const { t } = useI18n();
  const [view, setView] = useState<GlobalMemoryView>("active");
  const [query, setQuery] = useState("");
  const [records, setRecords] = useState<GlobalMemoryRecord[]>([]);
  const [events, setEvents] = useState<GlobalMemoryEvent[]>([]);
  const [state, setState] = useState<LoadState>("idle");
  const [error, setError] = useState<string | null>(null);
  const [addDraft, setAddDraft] = useState<DraftState>(EMPTY_DRAFT);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editDraft, setEditDraft] = useState<DraftState>(EMPTY_DRAFT);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [deleteReason, setDeleteReason] = useState("");
  const [pendingAction, setPendingAction] = useState<string | null>(null);
  const [pagination, setPagination] = useState({
    page: 1,
    pageSize: PAGE_SIZE,
    totalCount: 0,
    totalPages: 1,
  });
  const requestIdRef = useRef(0);
  const readyReportedRef = useRef(false);

  const reportReady = useCallback(() => {
    if (readyReportedRef.current) return;
    readyReportedRef.current = true;
    onReady?.();
  }, [onReady]);

  const load = useCallback(async (page?: number, signal?: AbortSignal) => {
    const requestId = requestIdRef.current + 1;
    requestIdRef.current = requestId;
    setState("loading");
    setError(null);
    try {
      const response = view === "events"
        ? await getGlobalMemoryEvents({
            page: page ?? 1,
            pageSize: PAGE_SIZE,
            query,
            signal,
          })
        : await getGlobalMemoryRecords({
            page,
            pageSize: PAGE_SIZE,
            query,
            signal,
            status: view,
          });
      if (requestIdRef.current !== requestId) return;
      if (view === "events") {
        setEvents(response.items as GlobalMemoryEvent[]);
        setRecords([]);
      } else {
        setRecords(response.items as GlobalMemoryRecord[]);
        setEvents([]);
      }
      setPagination({
        page: response.page,
        pageSize: response.page_size,
        totalCount: response.total_count,
        totalPages: response.total_pages,
      });
      setState("ready");
      reportReady();
    } catch (loadError) {
      if (signal?.aborted || requestIdRef.current !== requestId) return;
      setError(
        loadError instanceof Error
          ? loadError.message
          : t("aiPanel.memoryDashboard.loadFailed"),
      );
      setState("error");
      reportReady();
    }
  }, [query, reportReady, t, view]);

  useEffect(() => {
    const controller = new AbortController();
    void load(undefined, controller.signal);
    return () => {
      controller.abort();
      requestIdRef.current += 1;
    };
  }, [load]);

  const changeView = useCallback((nextView: GlobalMemoryView) => {
    if (nextView === view) return;
    requestIdRef.current += 1;
    setRecords([]);
    setEvents([]);
    setPagination({
      page: 1,
      pageSize: PAGE_SIZE,
      totalCount: 0,
      totalPages: 1,
    });
    setError(null);
    setState("loading");
    setView(nextView);
  }, [view]);

  const addMemory = useCallback(async () => {
    if (!addDraft.content.trim() || !addDraft.reason.trim()) return;
    setPendingAction("add");
    setError(null);
    try {
      await applyGlobalMemoryOperation({
        operation: "add",
        content: addDraft.content,
        keywords: keywordsFromDraft(addDraft.keywords),
        reason: addDraft.reason,
      });
      setAddDraft(EMPTY_DRAFT);
      await load();
    } catch (operationError) {
      setError(
        operationError instanceof Error
          ? operationError.message
          : t("aiPanel.memoryDashboard.addFailed"),
      );
    } finally {
      setPendingAction(null);
    }
  }, [addDraft, load, t]);

  const startEditing = useCallback((record: GlobalMemoryRecord) => {
    setDeletingId(null);
    setDeleteReason("");
    setEditingId(record.id);
    setEditDraft({
      content: record.content,
      keywords: record.keywords.join("，"),
      reason: "",
    });
  }, []);

  const saveMemory = useCallback(async (record: GlobalMemoryRecord) => {
    if (!editDraft.content.trim() || !editDraft.reason.trim()) return;
    setPendingAction(record.id);
    setError(null);
    try {
      await applyGlobalMemoryOperation({
        operation: "update",
        memory_id: record.id,
        content: editDraft.content,
        keywords: keywordsFromDraft(editDraft.keywords),
        reason: editDraft.reason,
      });
      setEditingId(null);
      await load(pagination.page);
    } catch (operationError) {
      setError(
        operationError instanceof Error
          ? operationError.message
          : t("aiPanel.memoryDashboard.updateFailed"),
      );
    } finally {
      setPendingAction(null);
    }
  }, [editDraft, load, pagination.page, t]);

  const deleteMemory = useCallback(async (record: GlobalMemoryRecord) => {
    if (!deleteReason.trim()) return;
    setPendingAction(record.id);
    setError(null);
    try {
      await applyGlobalMemoryOperation({
        operation: "delete",
        memory_id: record.id,
        reason: deleteReason,
      });
      setDeletingId(null);
      setDeleteReason("");
      await load(pagination.page);
    } catch (operationError) {
      setError(
        operationError instanceof Error
          ? operationError.message
          : t("aiPanel.memoryDashboard.deleteFailed"),
      );
    } finally {
      setPendingAction(null);
    }
  }, [deleteReason, load, pagination.page, t]);

  const hasItems = view === "events" ? events.length > 0 : records.length > 0;
  const emptyMessageKey = view === "active"
    ? "globalMemoryManager.emptyActive"
    : view === "deleted"
      ? "globalMemoryManager.emptyDeleted"
      : "globalMemoryManager.emptyEvents";

  return (
    <div className="global-memory-settings">
      <header className="global-memory-settings__head">
        <div>
          <h2>{t("globalMemoryManager.title")}</h2>
        </div>
        <button
          className="global-memory-settings__icon-button"
          type="button"
          aria-label={t("aiPanel.memoryDashboard.refresh")}
          title={t("common.actions.refresh")}
          disabled={state === "loading" || pendingAction !== null}
          onClick={() => { void load(pagination.page); }}
        >
          <ArrowClockwise size={15} weight="bold" aria-hidden="true" />
        </button>
      </header>

      <SettingsViewTabs
        activeView={view}
        ariaLabel={t("globalMemoryManager.views")}
        disabled={pendingAction !== null}
        onChange={changeView}
        tabs={[
          { id: "active", label: t("globalMemoryManager.active") },
          { id: "deleted", label: t("globalMemoryManager.deleted") },
          { id: "events", label: t("globalMemoryManager.eventLog") },
        ]}
      />

      <div className="global-memory-settings__toolbar">
        <input
          className="global-memory-settings__input global-memory-settings__search"
          type="search"
          value={query}
          disabled={pendingAction !== null}
          placeholder={t("globalMemoryManager.search")}
          onChange={(event) => setQuery(event.target.value)}
        />
      </div>

      <SettingsViewStage
        activeView={view}
        className="global-memory-settings__view-stage"
        keepLeavingView
        orderedViews={GLOBAL_MEMORY_VIEW_ORDER}
      >
        {view === "deleted" ? (
          <p className="global-memory-settings__notice">{t("globalMemoryManager.deletedNote")}</p>
        ) : null}
        {error ? <p className="global-memory-settings__error" role="alert">{error}</p> : null}

        {view === "active" ? (
          <section className="global-memory-settings__add" aria-label={t("globalMemoryManager.addTitle") }>
          <h3>{t("globalMemoryManager.addTitle")}</h3>
          <textarea
            className="global-memory-settings__textarea"
            value={addDraft.content}
            disabled={pendingAction !== null}
            placeholder={t("globalMemoryManager.contentPlaceholder")}
            onChange={(event) => setAddDraft((current) => ({ ...current, content: event.target.value }))}
          />
          <div className="global-memory-settings__form-row">
            <input
              className="global-memory-settings__input"
              value={addDraft.keywords}
              disabled={pendingAction !== null}
              placeholder={t("aiPanel.memoryDashboard.keywordsPlaceholder")}
              onChange={(event) => setAddDraft((current) => ({ ...current, keywords: event.target.value }))}
            />
            <input
              className="global-memory-settings__input"
              value={addDraft.reason}
              disabled={pendingAction !== null}
              placeholder={t("aiPanel.memoryDashboard.reasonPlaceholder")}
              onChange={(event) => setAddDraft((current) => ({ ...current, reason: event.target.value }))}
            />
            <button
              className="global-memory-settings__button global-memory-settings__button--primary"
              type="button"
              disabled={pendingAction !== null || !addDraft.content.trim() || !addDraft.reason.trim()}
              onClick={() => { void addMemory(); }}
            >
              <Plus size={14} weight="bold" aria-hidden="true" />
              {t("common.actions.add")}
            </button>
          </div>
          </section>
        ) : null}

        {state === "loading" && !hasItems ? (
          <p className="global-memory-settings__empty">{t("aiPanel.memoryDashboard.loading")}</p>
        ) : null}
        {state !== "loading" && !hasItems ? (
          <p className="global-memory-settings__empty">{t(emptyMessageKey)}</p>
        ) : null}

        {view === "events" ? (
          <section className="global-memory-settings__event-list" aria-label={t("globalMemoryManager.eventLog") }>
            {events.map((event) => <GlobalMemoryEventCard event={event} key={event.event_index} />)}
          </section>
        ) : (
          <section className="global-memory-settings__record-list" aria-label={view === "active" ? t("globalMemoryManager.active") : t("globalMemoryManager.deleted") }>
            {records.map((record) => (
            <GlobalMemoryRecordCard
              deleteReason={deleteReason}
              editDraft={editDraft}
              isDeleting={deletingId === record.id}
              isEditing={editingId === record.id}
              isMutationPending={pendingAction !== null}
              key={record.id}
              record={record}
              onCancelDelete={() => {
                setDeletingId(null);
                setDeleteReason("");
              }}
              onCancelEdit={() => setEditingId(null)}
              onDelete={() => { void deleteMemory(record); }}
              onDeleteReasonChange={setDeleteReason}
              onEditDraftChange={setEditDraft}
              onRequestDelete={() => {
                setEditingId(null);
                setDeletingId(record.id);
                setDeleteReason("");
              }}
              onSave={() => { void saveMemory(record); }}
              onStartEdit={() => startEditing(record)}
            />
            ))}
          </section>
        )}

        {pagination.totalCount > 0 ? (
          <PaginationControls
            isLoading={state === "loading" || pendingAction !== null}
            onPageChange={(page) => load(page)}
            page={pagination.page}
            pageSize={pagination.pageSize}
            totalCount={pagination.totalCount}
            totalPages={pagination.totalPages}
          />
        ) : null}
      </SettingsViewStage>
    </div>
  );
}

function GlobalMemoryRecordCard({
  deleteReason,
  editDraft,
  isDeleting,
  isEditing,
  isMutationPending,
  onCancelDelete,
  onCancelEdit,
  onDelete,
  onDeleteReasonChange,
  onEditDraftChange,
  onRequestDelete,
  onSave,
  onStartEdit,
  record,
}: {
  deleteReason: string;
  editDraft: DraftState;
  isDeleting: boolean;
  isEditing: boolean;
  isMutationPending: boolean;
  onCancelDelete: () => void;
  onCancelEdit: () => void;
  onDelete: () => void;
  onDeleteReasonChange: (value: string) => void;
  onEditDraftChange: (value: DraftState) => void;
  onRequestDelete: () => void;
  onSave: () => void;
  onStartEdit: () => void;
  record: GlobalMemoryRecord;
}) {
  const { t } = useI18n();
  const isActive = record.status === "active";
  const source = useMemo(() => sourceLabel(record.source, t), [record.source, t]);

  return (
    <article className="global-memory-settings__record">
      <header className="global-memory-settings__record-head">
        <div>
          <strong>{record.id}</strong>
          <span title={record.source}>{source}</span>
          <span>{t("aiPanel.memoryDashboard.eventCount", { count: record.event_count })}</span>
        </div>
        {isActive ? (
          <div className="global-memory-settings__record-actions">
            {isEditing ? (
              <>
                <button className="global-memory-settings__icon-button" type="button" aria-label={t("common.actions.save")} disabled={isMutationPending || !editDraft.content.trim() || !editDraft.reason.trim()} onClick={onSave}>
                  <Check size={14} weight="bold" aria-hidden="true" />
                </button>
                <button className="global-memory-settings__icon-button" type="button" aria-label={t("common.actions.cancel")} disabled={isMutationPending} onClick={onCancelEdit}>
                  <X size={14} weight="bold" aria-hidden="true" />
                </button>
              </>
            ) : isDeleting ? (
              <>
                <button className="global-memory-settings__button global-memory-settings__button--danger" type="button" disabled={isMutationPending || !deleteReason.trim()} onClick={onDelete}>
                  {t("aiPanel.memoryDashboard.confirmDelete")}
                </button>
                <button className="global-memory-settings__icon-button" type="button" aria-label={t("aiPanel.memoryDashboard.cancelDelete")} disabled={isMutationPending} onClick={onCancelDelete}>
                  <X size={14} weight="bold" aria-hidden="true" />
                </button>
              </>
            ) : (
              <>
                <button className="global-memory-settings__icon-button" type="button" aria-label={t("common.actions.edit")} disabled={isMutationPending} onClick={onStartEdit}>
                  <PencilSimple size={14} weight="bold" aria-hidden="true" />
                </button>
                <button className="global-memory-settings__icon-button global-memory-settings__icon-button--danger" type="button" aria-label={t("common.actions.delete")} disabled={isMutationPending} onClick={onRequestDelete}>
                  <Trash size={14} weight="bold" aria-hidden="true" />
                </button>
              </>
            )}
          </div>
        ) : null}
      </header>

      {isEditing ? (
        <div className="global-memory-settings__edit">
          <textarea className="global-memory-settings__textarea" value={editDraft.content} disabled={isMutationPending} onChange={(event) => onEditDraftChange({ ...editDraft, content: event.target.value })} />
          <input className="global-memory-settings__input" value={editDraft.keywords} disabled={isMutationPending} placeholder={t("aiPanel.memoryDashboard.keywordsPlaceholder")} onChange={(event) => onEditDraftChange({ ...editDraft, keywords: event.target.value })} />
          <input className="global-memory-settings__input" value={editDraft.reason} disabled={isMutationPending} placeholder={t("aiPanel.memoryDashboard.reasonPlaceholder")} onChange={(event) => onEditDraftChange({ ...editDraft, reason: event.target.value })} />
        </div>
      ) : (
        <>
          {isDeleting ? (
            <div className="global-memory-settings__delete-confirm">
              <p>{t("globalMemoryManager.deleteMessage")}</p>
              <input autoFocus className="global-memory-settings__input" value={deleteReason} disabled={isMutationPending} placeholder={t("aiPanel.memoryDashboard.deleteReasonPlaceholder")} onChange={(event) => onDeleteReasonChange(event.target.value)} />
            </div>
          ) : null}
          <p className="global-memory-settings__content">{record.content}</p>
          <KeywordList keywords={record.keywords} />
          <dl className="global-memory-settings__meta">
            <Meta label={t("globalMemoryManager.createdAt")} value={formatDateTime(record.created_at)} />
            <Meta label={t("globalMemoryManager.updatedAt")} value={formatDateTime(record.updated_at)} />
            {record.deleted_at ? <Meta label={t("globalMemoryManager.deletedAt")} value={formatDateTime(record.deleted_at)} /> : null}
          </dl>
          <details className="global-memory-settings__history">
            <summary>{t("globalMemoryManager.history")}</summary>
            <div className="global-memory-settings__event-list global-memory-settings__event-list--nested">
              {[...record.events].reverse().map((event) => <GlobalMemoryEventCard compact event={event} key={event.event_index} />)}
            </div>
          </details>
        </>
      )}
    </article>
  );
}

function GlobalMemoryEventCard({ event, compact = false }: { event: GlobalMemoryEvent; compact?: boolean }) {
  const { t } = useI18n();
  return (
    <article className={compact ? "global-memory-settings__event global-memory-settings__event--compact" : "global-memory-settings__event"}>
      <header>
        <strong>{operationLabel(event.operation, t)}</strong>
        <code>{event.memory_id}</code>
        <span>#{event.event_index}</span>
        <time>{formatDateTime(event.created_at)}</time>
      </header>
      <div className="global-memory-settings__change">
        <MemoryValue label={t("globalMemoryManager.before")} value={event.before} />
        <MemoryValue label={t("globalMemoryManager.after")} value={event.after} />
      </div>
      <footer>
        <span title={event.source}>{sourceLabel(event.source, t)}</span>
        {event.source ? <code>{event.source}</code> : null}
        <p>{event.reason || t("aiPanel.memoryDashboard.reasonUnavailable")}</p>
      </footer>
    </article>
  );
}

function MemoryValue({ label, value }: { label: string; value: GlobalMemoryEvent["before"] }) {
  const { t } = useI18n();
  return (
    <div>
      <span>{label}</span>
      {value ? (
        <>
          <p>{value.content}</p>
          <KeywordList keywords={value.keywords} />
        </>
      ) : <p className="global-memory-settings__missing">{t("globalMemoryManager.noValue")}</p>}
    </div>
  );
}

function KeywordList({ keywords }: { keywords: string[] }) {
  if (keywords.length === 0) return null;
  return (
    <div className="global-memory-settings__keywords">
      {keywords.map((keyword) => <span key={keyword}>{keyword}</span>)}
    </div>
  );
}

function Meta({ label, value }: { label: string; value: string }) {
  return <div><dt>{label}</dt><dd>{value || "-"}</dd></div>;
}

function keywordsFromDraft(value: string): string[] {
  return value.split(/[\s,，;；]+/).map((item) => item.trim()).filter(Boolean);
}

function sourceLabel(value: string, t: (key: TranslationKey) => string): string {
  if (!value) return t("aiPanel.memoryDashboard.source.none");
  if (value.startsWith("manual_")) return t("aiPanel.memoryDashboard.source.manual");
  if (value.startsWith("ai_")) return t("aiPanel.memoryDashboard.source.aiManagement");
  if (value.startsWith("cmp_")) return t("aiPanel.memoryDashboard.source.compression");
  return value;
}

function operationLabel(value: GlobalMemoryEvent["operation"], t: (key: TranslationKey) => string): string {
  if (value === "add") return t("aiPanel.memoryDashboard.operation.add");
  if (value === "update") return t("aiPanel.memoryDashboard.operation.update");
  return t("aiPanel.memoryDashboard.operation.delete");
}

function formatDateTime(value: string): string {
  if (!value) return "-";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}
