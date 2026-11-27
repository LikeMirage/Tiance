import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { ArrowClockwise, Check, PencilSimple, Plus, Trash, X } from "@phosphor-icons/react";

import type {
  ProjectMemoryItem,
  ProjectMemoryScope,
} from "../../../entities/project-memory/model/projectMemory";
import { useI18n, type TranslationKey } from "../../../shared/i18n";
import { PaginationControls } from "../../../shared/ui/pagination-controls/PaginationControls";
import { EdgeScrollArea } from "../../../shared/ui/edge-scrollbar/EdgeScrollArea";
import { SettingsViewTabs } from "../../../shared/ui/settings-view-tabs/SettingsViewTabs";
import { MemoryTokenCount } from "../../../shared/ui/memory-token-count/MemoryTokenCount";
import { GlobalMemorySettingsPanel } from "../../global-memory-settings/ui/GlobalMemorySettingsPanel";
import { subscribeMemoryChanges } from "../../../services/memory/memoryChanges";
import {
  applyProjectMemoryOperation,
  getProjectMemory,
} from "../../../services/project/projectMemory";
import "./memory-management.css";

type LoadState = "idle" | "loading" | "ready" | "error";

type DraftState = {
  content: string;
  keywords: string;
  reason: string;
};

const EMPTY_DRAFT: DraftState = { content: "", keywords: "", reason: "" };

type DashboardProps = {
  projectId: string | null;
  inEditor?: boolean;
};

export function MemoryManagementDashboard({ projectId, inEditor = false }: DashboardProps) {
  const [scope, setScope] = useState<ProjectMemoryScope>("project");
  const { t } = useI18n();
  const scopeTabs = (
    <SettingsViewTabs<ProjectMemoryScope> activeView={scope} onChange={setScope}
      ariaLabel={t("aiPanel.memoryDashboard.scope")} compact={!inEditor} tabs={[
        { id: "project", label: t("aiPanel.memoryDashboard.projectMemory") },
        { id: "global", label: t("aiPanel.memoryDashboard.globalMemory") },
      ]} />
  );
  const list = (
    <MemoryList key={`${scope}:${projectId ?? ""}`} projectId={projectId} scope={scope}
      inEditor={inEditor} scopeTabs={inEditor ? null : scopeTabs} />
  );
  if (!inEditor) return list;
  return (
    <EdgeScrollArea frameClassName="project-memory-board" className="project-memory-board__viewport">
      <div className="project-memory-board__content">
        {scopeTabs}
        {scope === "global" ? <GlobalMemorySettingsPanel /> : list}
      </div>
    </EdgeScrollArea>
  );
}

function MemoryList({ projectId, scope, inEditor, scopeTabs }: {
  projectId: string | null;
  scope: ProjectMemoryScope;
  inEditor: boolean;
  scopeTabs: ReactNode;
}) {
  const [adding, setAdding] = useState(!inEditor);
  const [totalTokens, setTotalTokens] = useState<number>();
  const [saving, setSaving] = useState(false);
  const [query, setQuery] = useState("");
  const [items, setItems] = useState<ProjectMemoryItem[]>([]);
  const [state, setState] = useState<LoadState>("idle");
  const [error, setError] = useState<string | null>(null);
  const [addDraft, setAddDraft] = useState<DraftState>(EMPTY_DRAFT);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editDraft, setEditDraft] = useState<DraftState>(EMPTY_DRAFT);
  const [confirmingDeleteId, setConfirmingDeleteId] = useState<string | null>(null);
  const [deleteReason, setDeleteReason] = useState("");
  const [pagination, setPagination] = useState({
    page: 1,
    pageSize: 50,
    totalCount: 0,
    totalPages: 1,
  });
  const requestIdRef = useRef(0);
  const currentPage = useRef(1);
  const { t } = useI18n();

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
        query,
        scope,
        signal,
      });
      if (requestIdRef.current !== requestId) return;
      currentPage.current = response.page;
      setItems(response.items);
      setTotalTokens(response.total_estimated_tokens);
      setPagination({
        page: response.page,
        pageSize: response.page_size,
        totalCount: response.total_count,
        totalPages: response.total_pages,
      });
      setState("ready");
    } catch (err) {
      if (signal?.aborted || requestIdRef.current !== requestId) return;
      setError(err instanceof Error ? err.message : t("aiPanel.memoryDashboard.loadFailed"));
      setState("error");
    }
  }, [projectId, query, scope, t]);

  useEffect(() => {
    const controller = new AbortController();
    void load(undefined, controller.signal);
    const unsubscribe = subscribeMemoryChanges((changedProject, change) => {
      if (change.scope === scope && (scope === "global" || changedProject === projectId)) {
        void load(change.operation === "add" ? undefined : currentPage.current, controller.signal);
      }
    });
    return () => {
      unsubscribe();
      controller.abort();
      requestIdRef.current += 1;
    };
  }, [load, projectId, scope]);

  const saveAdd = useCallback(async () => {
    if (!projectId || saving || !addDraft.content.trim() || !addDraft.reason.trim()) return;
    setSaving(true);
    try {
      await applyProjectMemoryOperation(projectId, {
        scope,
        operation: "add",
        content: addDraft.content,
        keywords: keywordsFromDraft(addDraft.keywords),
        reason: addDraft.reason,
      });
      setAddDraft(EMPTY_DRAFT);
      if (inEditor) setAdding(false);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("aiPanel.memoryDashboard.addFailed"));
    } finally {
      setSaving(false);
    }
  }, [addDraft, projectId, inEditor, saving, scope, t]);

  const startEdit = useCallback((item: ProjectMemoryItem) => {
    setEditingId(item.id);
    setConfirmingDeleteId(null);
    setEditDraft({
      content: item.content,
      keywords: item.keywords.join("，"),
      reason: "",
    });
  }, []);

  const saveEdit = useCallback(async (item: ProjectMemoryItem) => {
    if (!projectId || saving || !editDraft.content.trim() || !editDraft.reason.trim()) return;
    setSaving(true);
    try {
      await applyProjectMemoryOperation(projectId, {
        scope,
        operation: "update",
        memory_id: item.id,
        content: editDraft.content,
        keywords: keywordsFromDraft(editDraft.keywords),
        reason: editDraft.reason,
      });
      setEditingId(null);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("aiPanel.memoryDashboard.updateFailed"));
    } finally {
      setSaving(false);
    }
  }, [editDraft, projectId, saving, scope, t]);

  const deleteItem = useCallback(async (item: ProjectMemoryItem) => {
    if (!projectId || saving || !deleteReason.trim()) return;
    setSaving(true);
    try {
      await applyProjectMemoryOperation(projectId, {
        scope,
        operation: "delete",
        memory_id: item.id,
        reason: deleteReason,
      });
      setConfirmingDeleteId(null);
      setDeleteReason("");
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("aiPanel.memoryDashboard.deleteFailed"));
    } finally {
      setSaving(false);
    }
  }, [deleteReason, projectId, saving, scope, t]);

  const scopedTitle = scope === "project"
    ? t("aiPanel.memoryDashboard.projectMemory")
    : t("aiPanel.memoryDashboard.globalMemory");
  const isProjectMissing = !projectId;

  return (
    <section className="ai-panel__memory-dashboard" aria-label={t("aiPanel.memoryDashboard.title")}>
      <header className="ai-panel__memory-dashboard-head">
        <div>
          {inEditor ? <h2>{scopedTitle}</h2> : <>
            <span className="ai-panel__setting-group-title">{t("aiPanel.memoryDashboard.title")}</span>
            <p>{t("aiPanel.memoryDashboard.description")}</p>
          </>}
        </div>
        <MemoryTokenCount count={totalTokens} total />
        <button
          className="ai-panel__tool-settings-refresh"
          type="button"
          aria-label={t("aiPanel.memoryDashboard.refresh")}
          title={t("common.actions.refresh")}
          disabled={state === "loading" || isProjectMissing}
          onClick={() => { void load(pagination.page); }}
        >
          <ArrowClockwise size={14} weight="bold" aria-hidden="true" />
        </button>
      </header>

      <div className="ai-panel__memory-toolbar">
        {scopeTabs}
        <input
          className="ai-panel__text-input"
          placeholder={t("aiPanel.memoryDashboard.search", { scope: scopedTitle })}
          type="search"
          aria-label={t("aiPanel.memoryDashboard.search", { scope: scopedTitle })}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
        {inEditor && <button className="ai-panel__memory-action" type="button" aria-expanded={adding}
          disabled={saving} onClick={() => { setAdding(!adding); setAddDraft(EMPTY_DRAFT); }}>
          {adding ? <X size={14} /> : <Plus size={14} />}
          {t(adding ? "common.actions.cancel" : "common.actions.add")}
        </button>}
      </div>

      {error ? <p className="ai-panel__tool-settings-error">{error}</p> : null}
      {isProjectMissing ? (
        <p className="ai-panel__tool-settings-empty">{t("aiPanel.memoryDashboard.noProject")}</p>
      ) : null}

      {adding && <div className="ai-panel__memory-add" inert={saving}>
        <textarea
          autoFocus={inEditor}
          className="ai-panel__prompt-input"
          placeholder={t("aiPanel.memoryDashboard.add", { scope: scopedTitle })}
          value={addDraft.content}
          onChange={(event) => setAddDraft((current) => ({ ...current, content: event.target.value }))}
        />
        <input
          className="ai-panel__text-input"
          placeholder={t("aiPanel.memoryDashboard.reasonPlaceholder")}
          value={addDraft.reason}
          onChange={(event) => setAddDraft((current) => ({ ...current, reason: event.target.value }))}
        />
        <div className="ai-panel__memory-add-row">
          <input
            className="ai-panel__text-input"
            placeholder={t("aiPanel.memoryDashboard.keywordsPlaceholder")}
            value={addDraft.keywords}
            onChange={(event) => setAddDraft((current) => ({ ...current, keywords: event.target.value }))}
          />
          <button
            className="ai-panel__memory-action ai-panel__memory-action--primary"
            type="button"
            disabled={saving || isProjectMissing || !addDraft.content.trim() || !addDraft.reason.trim()}
            onClick={() => { void saveAdd(); }}
          >
            <Plus size={13} weight="bold" aria-hidden="true" />
            {t("common.actions.add")}
          </button>
        </div>
      </div>}

      <div className="ai-panel__memory-list" inert={saving}>
        {state === "loading" && items.length === 0 ? (
          <p className="ai-panel__tool-settings-empty">{t("aiPanel.memoryDashboard.loading")}</p>
        ) : null}
        {state === "ready" && !isProjectMissing && items.length === 0 ? (
          <p className="ai-panel__tool-settings-empty">
            {t("aiPanel.memoryDashboard.empty", { scope: scopedTitle })}
          </p>
        ) : null}
        {items.map((item) => (
          <MemoryItemRow
            confirmingDeleteId={confirmingDeleteId}
            deleteReason={deleteReason}
            editDraft={editDraft}
            editingId={editingId}
            item={item}
            saving={saving}
            key={item.id}
            onCancelDelete={() => {
              setConfirmingDeleteId(null);
              setDeleteReason("");
            }}
            onCancelEdit={() => setEditingId(null)}
            onDelete={() => { void deleteItem(item); }}
            onDeleteReasonChange={setDeleteReason}
            onEditDraftChange={setEditDraft}
            onRequestDelete={() => {
              setEditingId(null);
              setConfirmingDeleteId(item.id);
              setDeleteReason("");
            }}
            onSaveEdit={() => { void saveEdit(item); }}
            onStartEdit={() => startEdit(item)}
          />
        ))}
      </div>
      {!isProjectMissing && pagination.totalCount > 0 ? (
        <PaginationControls
          isLoading={state === "loading"}
          onPageChange={(page) => load(page)}
          page={pagination.page}
          pageSize={pagination.pageSize}
          totalCount={pagination.totalCount}
          totalPages={pagination.totalPages}
        />
      ) : null}
    </section>
  );
}

function MemoryItemRow({
  confirmingDeleteId,
  deleteReason,
  editDraft,
  editingId,
  item,
  saving,
  onCancelDelete,
  onCancelEdit,
  onDelete,
  onDeleteReasonChange,
  onEditDraftChange,
  onRequestDelete,
  onSaveEdit,
  onStartEdit,
}: {
  confirmingDeleteId: string | null;
  deleteReason: string;
  editDraft: DraftState;
  editingId: string | null;
  item: ProjectMemoryItem;
  saving: boolean;
  onCancelDelete: () => void;
  onCancelEdit: () => void;
  onDelete: () => void;
  onDeleteReasonChange: (value: string) => void;
  onEditDraftChange: (value: DraftState) => void;
  onRequestDelete: () => void;
  onSaveEdit: () => void;
  onStartEdit: () => void;
}) {
  const { t } = useI18n();
  const isEditing = editingId === item.id;
  const isConfirmingDelete = confirmingDeleteId === item.id;
  const sourceLabel = useMemo(() => formatMemorySource(item.source, t), [item.source, t]);

  return (
    <article className="ai-panel__memory-item">
      <header className="ai-panel__memory-item-head">
        <div>
          <strong title={item.id}>{item.id}</strong>
          <span>{sourceLabel}</span>
          <span>{t("aiPanel.memoryDashboard.eventCount", { count: item.event_count })}</span>
          <MemoryTokenCount count={item.estimated_tokens} />
        </div>
        <div className="ai-panel__memory-actions">
          {isEditing ? (
            <>
              <button
                className="ai-panel__memory-icon-button"
                type="button"
                aria-label={t("common.actions.save")}
                disabled={saving || !editDraft.content.trim() || !editDraft.reason.trim()}
                onClick={onSaveEdit}
              >
                <Check size={13} weight="bold" aria-hidden="true" />
              </button>
              <button className="ai-panel__memory-icon-button" type="button" aria-label={t("common.actions.cancel")} onClick={onCancelEdit}>
                <X size={13} weight="bold" aria-hidden="true" />
              </button>
            </>
          ) : isConfirmingDelete ? (
            <>
              <button
                className="ai-panel__memory-danger-text"
                type="button"
                disabled={saving || !deleteReason.trim()}
                onClick={onDelete}
              >
                {t("aiPanel.memoryDashboard.confirmDelete")}
              </button>
              <button className="ai-panel__memory-icon-button" type="button" aria-label={t("aiPanel.memoryDashboard.cancelDelete")} onClick={onCancelDelete}>
                <X size={13} weight="bold" aria-hidden="true" />
              </button>
            </>
          ) : (
            <>
              <button className="ai-panel__memory-icon-button" type="button" aria-label={t("common.actions.edit")} onClick={onStartEdit}>
                <PencilSimple size={13} weight="bold" aria-hidden="true" />
              </button>
              <button className="ai-panel__memory-icon-button ai-panel__memory-icon-button--danger" type="button" aria-label={t("common.actions.delete")} onClick={onRequestDelete}>
                <Trash size={13} weight="bold" aria-hidden="true" />
              </button>
            </>
          )}
        </div>
      </header>

      {isEditing ? (
        <div className="ai-panel__memory-edit">
          <textarea
            className="ai-panel__prompt-input"
            value={editDraft.content}
            onChange={(event) => onEditDraftChange({ ...editDraft, content: event.target.value })}
          />
          <input
            className="ai-panel__text-input"
            value={editDraft.keywords}
            onChange={(event) => onEditDraftChange({ ...editDraft, keywords: event.target.value })}
          />
          <input
            className="ai-panel__text-input"
            placeholder={t("aiPanel.memoryDashboard.reasonPlaceholder")}
            value={editDraft.reason}
            onChange={(event) => onEditDraftChange({ ...editDraft, reason: event.target.value })}
          />
        </div>
      ) : (
        <>
          {isConfirmingDelete ? (
            <div className="ai-panel__memory-edit">
              <input
                autoFocus
                className="ai-panel__text-input"
                placeholder={t("aiPanel.memoryDashboard.deleteReasonPlaceholder")}
                value={deleteReason}
                onChange={(event) => onDeleteReasonChange(event.target.value)}
              />
            </div>
          ) : null}
          <p>{item.content}</p>
          {item.keywords.length > 0 ? (
            <div className="ai-panel__memory-keywords">
              {item.keywords.map((keyword) => <span key={keyword}>{keyword}</span>)}
            </div>
          ) : null}
          <details className="ai-panel__memory-events">
            <summary>{t("aiPanel.memoryDashboard.eventSource")}</summary>
            {item.events.length > 0 ? (
              <ul>
                {item.events.map((event, index) => (
                  <li key={`${event.operation}-${event.created_at}-${index}`}>
                    <span>{operationLabel(event.operation, t)}</span>
                    <span>{formatMemorySource(event.source, t)}</span>
                    <time>{formatDateTime(event.created_at)}</time>
                    <span>{event.reason || t("aiPanel.memoryDashboard.reasonUnavailable")}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p>{t("aiPanel.memoryDashboard.noEvents")}</p>
            )}
          </details>
        </>
      )}
    </article>
  );
}

function keywordsFromDraft(value: string): string[] {
  return value
    .split(/[\s,，;；]+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function formatMemorySource(value: string, t: (key: TranslationKey) => string): string {
  if (!value) return t("aiPanel.memoryDashboard.source.none");
  if (value.startsWith("manual_")) return t("aiPanel.memoryDashboard.source.manual");
  if (value.startsWith("ai_")) return t("aiPanel.memoryDashboard.source.aiManagement");
  if (value.startsWith("cmp_")) return t("aiPanel.memoryDashboard.source.compression");
  return value;
}

function operationLabel(value: string, t: (key: TranslationKey) => string): string {
  if (value === "add") return t("aiPanel.memoryDashboard.operation.add");
  if (value === "update") return t("aiPanel.memoryDashboard.operation.update");
  if (value === "delete") return t("aiPanel.memoryDashboard.operation.delete");
  return value || t("aiPanel.memoryDashboard.operation.fallback");
}

function formatDateTime(value: string): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString([], {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}
