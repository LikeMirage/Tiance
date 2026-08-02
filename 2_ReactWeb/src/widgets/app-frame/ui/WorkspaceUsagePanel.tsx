import { DotsThree } from "@phosphor-icons/react";
import { useEffect, useRef, useState, type ReactNode } from "react";

import {
  clearWorkspaceConversationCount,
  synchronizeWorkspaceConversationCount,
} from "../../../services/workspace/getWorkspaceActivitySummary";
import { useI18n } from "../../../shared/i18n";
import { ConfirmModal } from "../../../shared/ui/confirm-modal/ConfirmModal";
import {
  ContextMenu,
  ContextMenuItem,
  ContextMenuSeparator,
  type ContextMenuPosition,
} from "../../../shared/ui/context-menu";
import type {
  TopToolsState,
  UsageMetricState,
  WorkspaceUsageSummary,
} from "../model/useWorkspaceUsageSummary";

type WorkspaceUsagePanelProps = {
  onConversationCountChange: (value: number) => void;
  summary: WorkspaceUsageSummary;
};

type ConversationCountOperation = "clear" | "sync";

export function WorkspaceUsagePanel({
  onConversationCountChange,
  summary,
}: WorkspaceUsagePanelProps) {
  const { language, t } = useI18n();
  const actionButtonRef = useRef<HTMLButtonElement>(null);
  const mountedRef = useRef(true);
  const requestControllerRef = useRef<AbortController | null>(null);
  const [menuPosition, setMenuPosition] = useState<ContextMenuPosition | null>(null);
  const [showClearConfirmation, setShowClearConfirmation] = useState(false);
  const [operation, setOperation] = useState<ConversationCountOperation | null>(null);
  const [operationFailed, setOperationFailed] = useState(false);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      requestControllerRef.current?.abort();
    };
  }, []);

  const focusActionButton = () => {
    window.requestAnimationFrame(() => actionButtonRef.current?.focus());
  };

  const runOperation = async (nextOperation: ConversationCountOperation) => {
    if (operation || requestControllerRef.current) {
      return;
    }

    const controller = new AbortController();
    requestControllerRef.current = controller;
    setOperation(nextOperation);
    setOperationFailed(false);
    try {
      const response =
        nextOperation === "clear"
          ? await clearWorkspaceConversationCount({ signal: controller.signal })
          : await synchronizeWorkspaceConversationCount({ signal: controller.signal });
      if (mountedRef.current) {
        onConversationCountChange(response.conversation_count);
        setShowClearConfirmation(false);
      }
    } catch (error: unknown) {
      if (mountedRef.current && !isAbortError(error)) {
        setOperationFailed(true);
        setShowClearConfirmation(false);
      }
    } finally {
      if (requestControllerRef.current === controller) {
        requestControllerRef.current = null;
      }
      if (mountedRef.current) {
        setOperation(null);
        focusActionButton();
      }
    }
  };

  return (
    <div className="workspace-usage-panel" aria-busy={operation !== null}>
      <div className="workspace-usage-panel__header">
        <span>{t("appFrame.metrics.usageSummary")}</span>
        <button
          ref={actionButtonRef}
          type="button"
          className="workspace-usage-panel__actions"
          aria-expanded={menuPosition !== null}
          aria-haspopup="menu"
          disabled={operation !== null}
          onClick={() => {
            if (menuPosition) {
              setMenuPosition(null);
              return;
            }
            const rect = actionButtonRef.current?.getBoundingClientRect();
            if (rect) {
              setMenuPosition({ x: rect.right - 176, y: rect.bottom + 4 });
            }
          }}
        >
          <DotsThree size={15} weight="bold" aria-hidden="true" />
          <span>{t("appFrame.metrics.usageActions")}</span>
        </button>
      </div>
      <UsageRow
        label={t("appFrame.metrics.totalTokens")}
        value={formatMetric(summary.tokenTotal, language, t)}
        state={summary.tokenTotal.state}
      />
      <UsageRow
        label={t("appFrame.metrics.toolCalls")}
        value={formatMetric(summary.toolCallTotal, language, t)}
        state={summary.toolCallTotal.state}
      />
      <TopToolsRanking state={summary.topTools} language={language} t={t} />
      <UsageRow
        label={t("appFrame.metrics.conversationTotal")}
        value={formatMetric(summary.conversationTotal, language, t)}
        state={summary.conversationTotal.state}
      />
      <UsageRow
        label={t("appFrame.metrics.sentMessages")}
        value={formatMetric(summary.sentMessageTotal, language, t)}
        state={summary.sentMessageTotal.state}
      />
      <UsageRow
        label={t("appFrame.metrics.aiRuntime")}
        value={formatDurationMetric(summary.aiRuntimeTotal, t)}
        state={summary.aiRuntimeTotal.state}
      />
      {operationFailed ? (
        <div className="workspace-usage-panel__error" role="alert">
          {t("appFrame.metrics.usageOperationFailed")}
        </div>
      ) : null}
      {menuPosition ? (
        <ContextMenu
          minWidth={176}
          position={menuPosition}
          onClose={() => setMenuPosition(null)}
        >
          <ContextMenuItem
            disabled={operation !== null}
            onSelect={() => {
              setMenuPosition(null);
              void runOperation("sync");
            }}
          >
            {t("appFrame.metrics.syncConversationCount")}
          </ContextMenuItem>
          <ContextMenuSeparator />
          <ContextMenuItem
            danger
            disabled={operation !== null}
            onSelect={() => {
              setMenuPosition(null);
              setShowClearConfirmation(true);
            }}
          >
            {t("appFrame.metrics.clearConversationCount")}
          </ContextMenuItem>
        </ContextMenu>
      ) : null}
      {showClearConfirmation ? (
        <ConfirmModal
          cancelDisabled={operation !== null}
          confirmDisabled={operation !== null}
          confirmLabel={
            operation === "clear"
              ? t("appFrame.metrics.usageOperationInProgress")
              : t("appFrame.metrics.clearConversationConfirm")
          }
          danger
          message={t("appFrame.metrics.clearConversationMessage")}
          onCancel={() => {
            setShowClearConfirmation(false);
            focusActionButton();
          }}
          onConfirm={() => void runOperation("clear")}
          title={t("appFrame.metrics.clearConversationTitle")}
        />
      ) : null}
    </div>
  );
}

type TopToolsRankingProps = {
  language: string;
  state: TopToolsState;
  t: ReturnType<typeof useI18n>["t"];
};

function TopToolsRanking({ language, state, t }: TopToolsRankingProps) {
  let content: ReactNode;
  if (state.state === "loading") {
    content = <div className="workspace-usage-panel__ranking-empty">{t("appFrame.metrics.reading")}</div>;
  } else if (state.state === "error") {
    content = (
      <div className="workspace-usage-panel__ranking-empty">
        {t("appFrame.metrics.usageReadFailed")}
      </div>
    );
  } else if (state.items.length === 0) {
    content = (
      <div className="workspace-usage-panel__ranking-empty">
        {t("appFrame.metrics.noToolUsage")}
      </div>
    );
  } else {
    content = (
      <ol className="workspace-usage-panel__ranking-list">
        {state.items.map((item, index) => (
          <li key={item.tool_name} className="workspace-usage-panel__ranking-item">
            <span className="workspace-usage-panel__ranking-position">{index + 1}</span>
            <span className="workspace-usage-panel__ranking-name" title={item.display_name}>
              {item.display_name}
            </span>
            <span>
              {t("appFrame.metrics.toolCallCount", {
                count: new Intl.NumberFormat(language).format(item.call_count),
              })}
            </span>
          </li>
        ))}
      </ol>
    );
  }

  return (
    <section className="workspace-usage-panel__ranking">
      <div className="workspace-usage-panel__ranking-title">
        {t("appFrame.metrics.mostUsedTools")}
      </div>
      {content}
    </section>
  );
}

type UsageRowProps = {
  label: string;
  value: string;
  state?: UsageMetricState["state"];
};

function UsageRow({ label, value, state }: UsageRowProps) {
  return (
    <div className="workspace-usage-panel__row">
      <span>{label}</span>
      <span
        className={state === "ready" ? "workspace-usage-panel__value--ready" : undefined}
      >
        {value}
      </span>
    </div>
  );
}

function formatMetric(
  metric: UsageMetricState,
  language: string,
  t: ReturnType<typeof useI18n>["t"],
) {
  if (metric.state === "loading") {
    return t("appFrame.metrics.reading");
  }
  if (metric.state === "error") {
    return t("appFrame.metrics.usageReadFailed");
  }
  return new Intl.NumberFormat(language).format(metric.value);
}

function formatDurationMetric(
  metric: UsageMetricState,
  t: ReturnType<typeof useI18n>["t"],
) {
  if (metric.state === "loading") {
    return t("appFrame.metrics.reading");
  }
  if (metric.state === "error") {
    return t("appFrame.metrics.usageReadFailed");
  }
  const totalSeconds = Math.floor(metric.value / 1000);
  if (totalSeconds < 60) {
    return `${totalSeconds}s`;
  }
  const totalMinutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  if (totalMinutes < 60) {
    return seconds > 0 ? `${totalMinutes}m ${seconds}s` : `${totalMinutes}m`;
  }
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  return minutes > 0 ? `${hours}h ${minutes}m` : `${hours}h`;
}

function isAbortError(error: unknown) {
  return error instanceof DOMException && error.name === "AbortError";
}
