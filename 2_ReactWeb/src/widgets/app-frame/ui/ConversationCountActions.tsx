import { DotsThree } from "@phosphor-icons/react";
import { useEffect, useRef, useState } from "react";

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
type ConversationCountOperation = "clear" | "sync";

export function ConversationCountActions({
  onConversationCountChange,
  onRequestOpen,
}: { onConversationCountChange: (value: number) => void; onRequestOpen: () => void }) {
  const { t } = useI18n();
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
    onRequestOpen();
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
    <div className="workspace-usage-actions" aria-busy={operation !== null}>
      <div className="workspace-usage-panel__header">
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

function isAbortError(error: unknown) {
  return error instanceof DOMException && error.name === "AbortError";
}
